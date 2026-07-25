package com.crate.ui.review

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.FactCheck
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.crate.BuildConfig
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.Caption
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.EmptyState
import design.pulse.ui.components.ErrorState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.PulseSelectableCard

/** The review stack: every queued capture lands here as an editable draft. Nothing posts
 * to eBay without the explicit Post tap on each draft. */
@Composable
fun ReviewScreen(
    viewModel: ReviewViewModel = hiltViewModel(),
) {
    val drafts by viewModel.drafts.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Review",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.weight(1f),
            )
            PulseButton(text = "Refresh", onClick = { viewModel.refresh() }, compact = true, tonal = true)
        }
        Spacer(Modifier.size(CrateTheme.spacing.md))

        when (val state = drafts) {
            is UiState.Loading, UiState.Idle -> Box(
                Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator(color = CrateTheme.colors.copper.base) }

            is UiState.Error -> ErrorState(
                icon = Icons.Outlined.CloudOff,
                title = "Couldn't load drafts",
                detail = state.message,
                onRetry = { viewModel.refresh() },
            )

            is UiState.Success -> if (state.data.isEmpty()) {
                EmptyState(
                    icon = Icons.Outlined.FactCheck,
                    title = "Review stack is clear",
                    subtitle = "Captured items land here identified, cleaned up, and priced.",
                )
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
                    items(state.data, key = { it.id }) { item ->
                        DraftCard(
                            item = item,
                            onSave = { update, done -> viewModel.saveEdits(item.id, update, done) },
                            onDismiss = { viewModel.dismiss(item.id) },
                            onChoosePrice = { price -> viewModel.choosePrice(item.id, price) },
                            onPost = { done -> viewModel.post(item.id, done) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
internal fun DraftCard(
    item: ItemDto,
    onSave: (ItemUpdateRequest, (Boolean) -> Unit) -> Unit,
    onDismiss: () -> Unit,
    onChoosePrice: (String) -> Unit,
    onPost: ((String?) -> Unit) -> Unit,
) {
    var editing by remember { mutableStateOf(false) }
    var customPrice by remember { mutableStateOf(false) }
    var postError by remember { mutableStateOf<String?>(null) }
    var posting by remember { mutableStateOf(false) }

    PanelCard {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.photos.isNotEmpty()) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(item.photos, key = { it.id }) { photo ->
                        AsyncImage(
                            model = photoUrl(item.id, photo.id),
                            contentDescription = "item photo",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier
                                .size(120.dp)
                                .clip(RoundedCornerShape(12.dp)),
                        )
                    }
                }
            }

            if (item.processedAt == null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(
                        color = CrateTheme.colors.attention.base,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.size(8.dp))
                    Text("Identifying…", style = MaterialTheme.typography.bodySmall)
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        item.title ?: "Unidentified item",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    if (item.templateId != null) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            ChannelDot(color = CrateTheme.colors.provenance.base)
                            Spacer(Modifier.size(6.dp))
                            Text(
                                "From template — this model sold before",
                                style = MaterialTheme.typography.labelSmall,
                                color = CrateTheme.colors.provenance.base,
                            )
                        }
                    }
                    val subtitle = listOfNotNull(
                        item.brand,
                        item.model,
                        item.condition?.replace('_', ' '),
                    ).joinToString(" · ")
                    if (subtitle.isNotBlank()) {
                        Text(subtitle, style = MaterialTheme.typography.bodySmall)
                    }
                }
                item.description?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, maxLines = 4)
                }
                item.scanError?.let { error ->
                    Text(
                        when {
                            error == "low_confidence" ->
                                "Low-confidence identification — check everything."
                            error.startsWith("identify_unavailable") ->
                                "Identification unavailable ($error)"
                            else -> error
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = CrateTheme.colors.attention.base,
                    )
                }

                Spacer(Modifier.size(4.dp))
                if (item.quickSalePrice != null || item.patientPrice != null) {
                    Caption(text = "Pick a price strategy (live-market prices)")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item.quickSalePrice?.let { price ->
                            PulseSelectableCard(
                                label = "Quick · $$price",
                                selected = item.chosenPrice == price,
                                onClick = { onChoosePrice(price) },
                                channel = CrateTheme.colors.pricing.base,
                                channelDim = CrateTheme.colors.pricing.dim,
                                modifier = Modifier.weight(1f),
                            )
                        }
                        item.patientPrice?.let { price ->
                            PulseSelectableCard(
                                label = "Patient · $$price",
                                selected = item.chosenPrice == price,
                                onClick = { onChoosePrice(price) },
                                channel = CrateTheme.colors.pricing.base,
                                channelDim = CrateTheme.colors.pricing.dim,
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                    PulseButton(
                        text = "Custom price…",
                        onClick = { customPrice = true },
                        compact = true,
                        tonal = true,
                    )
                } else {
                    Text(
                        "No market comps yet — link eBay in Settings, or set your own price.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    PulseButton(
                        text = "Custom price…",
                        onClick = { customPrice = true },
                        compact = true,
                        tonal = true,
                    )
                }

                Spacer(Modifier.size(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    // The money-adjacent tap: only ever explicit, never automated (house rule).
                    PulseButton(
                        text = if (posting) "Posting…" else "Post to eBay",
                        onClick = {
                            posting = true
                            postError = null
                            onPost { error ->
                                posting = false
                                postError = error
                            }
                        },
                        enabled = !posting && item.title != null && item.chosenPrice != null,
                        gradient = if (!posting && item.title != null && item.chosenPrice != null) {
                            CrateTheme.colors.heroGradient
                        } else {
                            null
                        },
                        compact = true,
                    )
                    PulseButton(
                        text = "Edit",
                        onClick = { editing = true },
                        compact = true,
                        tonal = true,
                    )
                    PulseButton(text = "Dismiss", onClick = onDismiss, compact = true, tonal = true)
                }
                if (item.chosenPrice == null) {
                    Text(
                        "Pick a price to enable posting.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                postError?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }

    if (customPrice) {
        CustomPriceDialog(
            initial = item.chosenPrice ?: item.quickSalePrice ?: "",
            onSave = { price ->
                onChoosePrice(price)
                customPrice = false
            },
            onCancel = { customPrice = false },
        )
    }

    if (editing) {
        EditDialog(
            item = item,
            onSave = { update -> onSave(update) { ok -> if (ok) editing = false } },
            onCancel = { editing = false },
        )
    }
}

@Composable
private fun EditDialog(
    item: ItemDto,
    onSave: (ItemUpdateRequest) -> Unit,
    onCancel: () -> Unit,
) {
    var title by remember { mutableStateOf(item.title ?: "") }
    var brand by remember { mutableStateOf(item.brand ?: "") }
    var model by remember { mutableStateOf(item.model ?: "") }
    var condition by remember { mutableStateOf(item.condition ?: "") }
    var description by remember { mutableStateOf(item.description ?: "") }

    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Edit draft") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(title, { title = it }, label = { Text("Title (80 max)") })
                OutlinedTextField(brand, { brand = it }, label = { Text("Brand") })
                OutlinedTextField(model, { model = it }, label = { Text("Model") })
                OutlinedTextField(
                    condition,
                    { condition = it },
                    label = { Text("Condition (new/like_new/good/fair/poor)") },
                )
                OutlinedTextField(
                    description,
                    { description = it },
                    label = { Text("Description") },
                    minLines = 3,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSave(
                    // "" clears server-side; null (absent) leaves untouched — send the field
                    // as typed so emptying a field actually empties it.
                    ItemUpdateRequest(
                        title = title.take(80),
                        brand = brand,
                        model = model,
                        condition = condition.ifBlank { null },
                        description = description,
                    )
                )
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onCancel) { Text("Cancel") } },
    )
}

@Composable
private fun CustomPriceDialog(
    initial: String,
    onSave: (String) -> Unit,
    onCancel: () -> Unit,
) {
    var value by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Set a price") },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { input -> value = input.filter { it.isDigit() || it == '.' } },
                label = { Text("USD") },
            )
        },
        confirmButton = {
            TextButton(
                onClick = { value.toDoubleOrNull()?.let { onSave(value) } },
            ) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onCancel) { Text("Cancel") } },
    )
}

private fun photoUrl(itemId: String, photoId: String): String =
    BuildConfig.SERVER_URL.trimEnd('/') + "/items/$itemId/photos/$photoId/file"
