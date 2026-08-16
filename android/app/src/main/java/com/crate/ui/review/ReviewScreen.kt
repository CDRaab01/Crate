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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import com.crate.data.remote.CategorySuggestionDto
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.data.remote.VocabulariesDto
import com.crate.ui.components.DropdownField
import com.crate.ui.components.ArchiveGapRow
import com.crate.ui.components.GarmentDetailsDialog
import com.crate.ui.components.apparelSummary
import com.crate.ui.components.measurementSummary
import com.crate.ui.theme.CrateTheme
import com.crate.util.OnResumeEffect
import com.crate.util.UiState
import design.pulse.ui.components.Caption
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.DataText
import design.pulse.ui.components.EmptyState
import design.pulse.ui.components.ErrorState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.PulseRefreshBox
import design.pulse.ui.components.PulseSelectableCard

/** The review stack: every queued capture lands here as an editable draft. Nothing posts
 * to eBay without the explicit Post tap on each draft. */
@Composable
fun ReviewScreen(
    viewModel: ReviewViewModel = hiltViewModel(),
) {
    val drafts by viewModel.drafts.collectAsState()
    val refreshing by viewModel.refreshing.collectAsState()
    val vocabularies by viewModel.vocabularies.collectAsState()
    val categorySuggestions by viewModel.categorySuggestions.collectAsState()

    OnResumeEffect { viewModel.refresh() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
    ) {
        Text("Review", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.size(CrateTheme.spacing.md))

        PulseRefreshBox(
            isRefreshing = refreshing,
            onRefresh = viewModel::refresh,
            channel = CrateTheme.colors.copper.base,
            modifier = Modifier.weight(1f),
        ) {
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
                    Column(
                        Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState()),
                    ) {
                        EmptyState(
                            icon = Icons.Outlined.FactCheck,
                            title = "Review stack is clear",
                            subtitle = "Captured items land here identified, cleaned up, " +
                                "and priced.",
                        )
                    }
                } else {
                    LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        items(state.data, key = { it.id }) { item ->
                            DraftCard(
                                item = item,
                                onSave = { update, done ->
                                    viewModel.saveEdits(item.id, update, done)
                                },
                                onDismiss = { viewModel.dismiss(item.id) },
                                onChoosePrice = { price -> viewModel.choosePrice(item.id, price) },
                                onPost = { done -> viewModel.post(item.id, done) },
                                vocabularies = vocabularies,
                                categorySuggestions = categorySuggestions[item.id].orEmpty(),
                                onLoadCategories = {
                                    viewModel.loadCategorySuggestions(item.id)
                                },
                            )
                        }
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
    vocabularies: VocabulariesDto = VocabulariesDto(),
    categorySuggestions: List<CategorySuggestionDto> = emptyList(),
    onLoadCategories: () -> Unit = {},
) {
    var editing by remember { mutableStateOf(false) }
    var editingGarment by remember { mutableStateOf(false) }
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
                    val garment = apparelSummary(item)
                    if (garment.isNotBlank()) {
                        Text(garment, style = MaterialTheme.typography.bodySmall)
                    }
                    val measured = measurementSummary(item)
                    if (measured.isNotBlank()) {
                        Caption(text = measured)
                    }
                }
                // The archive-first nag: what still needs the garment physically in hand.
                ArchiveGapRow(item)
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
                    item.quickSalePrice?.let { price ->
                        PriceStrategyCard(
                            name = "Quick sale",
                            price = price,
                            selected = item.chosenPrice == price,
                            onClick = { onChoosePrice(price) },
                        )
                    }
                    item.patientPrice?.let { price ->
                        PriceStrategyCard(
                            name = "Patient",
                            price = price,
                            selected = item.chosenPrice == price,
                            onClick = { onChoosePrice(price) },
                        )
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
                        enabled = !posting && readyToPost(item),
                        gradient = if (!posting && readyToPost(item)) {
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
                // Second row: the tag/tape fields. Offered for every draft (a general good
                // reclassified as clothing needs a way in), but labelled by urgency so an
                // incomplete garment reads as unfinished rather than merely editable.
                PulseButton(
                    text = if (item.missingHandOnly.isNotEmpty()) {
                        "Add tag + measurements"
                    } else {
                        "Garment details"
                    },
                    onClick = { editingGarment = true },
                    compact = true,
                    tonal = true,
                )
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
            vocabularies = vocabularies,
            categorySuggestions = categorySuggestions,
            onLoadCategories = onLoadCategories,
            onSave = { update -> onSave(update) { ok -> if (ok) editing = false } },
            onCancel = { editing = false },
        )
    }

    if (editingGarment) {
        GarmentDetailsDialog(
            item = item,
            onSave = { update -> onSave(update) { ok -> if (ok) editingGarment = false } },
            onCancel = { editingGarment = false },
        )
    }
}

/** Strategy name on the left, mono price on the right — the price never wraps. */
/**
 * Whether the server will accept a post, mirroring `sell._require_ready`.
 *
 * Deliberately duplicated rather than inferred from a server flag: the point is that the
 * button is *not offered* until the draft is complete. eBay enforces the clothing specifics
 * at publish — after photos, the inventory item and the offer have all been created — so a
 * hopeful tap costs a half-built listing on eBay, not just an error toast.
 *
 * The list stays in step with the server by test, not by hope: `ReviewGatingTest` asserts
 * the same field names the API requires.
 */
internal fun readyToPost(item: ItemDto): Boolean {
    if (item.title.isNullOrBlank() || item.chosenPrice == null) return false
    if (item.condition.isNullOrBlank() || item.categoryId.isNullOrBlank()) return false
    if (item.photos.isEmpty()) return false
    if (item.itemKind == "clothing") {
        return !item.brand.isNullOrBlank() &&
            !item.color.isNullOrBlank() &&
            !item.size.isNullOrBlank() &&
            !item.sizeType.isNullOrBlank() &&
            !item.department.isNullOrBlank()
    }
    return true
}

@Composable
private fun PriceStrategyCard(
    name: String,
    price: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    PulseSelectableCard(
        label = name,
        selected = selected,
        onClick = onClick,
        channel = CrateTheme.colors.pricing.base,
        channelDim = CrateTheme.colors.pricing.dim,
        trailing = {
            DataText(
                text = "$$price",
                color = CrateTheme.colors.pricing.base,
            )
        },
        modifier = modifier,
    )
}

@Composable
private fun EditDialog(
    item: ItemDto,
    vocabularies: VocabulariesDto,
    categorySuggestions: List<CategorySuggestionDto>,
    onLoadCategories: () -> Unit,
    onSave: (ItemUpdateRequest) -> Unit,
    onCancel: () -> Unit,
) {
    var title by remember { mutableStateOf(item.title ?: "") }
    var brand by remember { mutableStateOf(item.brand ?: "") }
    var model by remember { mutableStateOf(item.model ?: "") }
    var condition by remember { mutableStateOf(item.condition) }
    var description by remember { mutableStateOf(item.description ?: "") }
    var categoryId by remember { mutableStateOf(item.categoryId) }
    var sizeType by remember { mutableStateOf(item.sizeType) }
    var department by remember { mutableStateOf(item.department) }

    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Edit draft") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(title, { title = it }, label = { Text("Title (80 max)") })
                OutlinedTextField(brand, { brand = it }, label = { Text("Brand") })
                OutlinedTextField(model, { model = it }, label = { Text("Model") })
                // Controlled vocabularies are dropdowns, not free text: every one of these
                // is validated server-side, so a typo here used to surface as a 422 at post
                // time — after the human had already put the garment back in the box.
                DropdownField(
                    label = "Condition",
                    value = condition,
                    options = vocabularies.conditions.map { it.value to it.label },
                    onSelect = { condition = it },
                )
                DropdownField(
                    label = "eBay category",
                    value = categoryId,
                    // Labelled by breadcrumb, not leaf name: "Polos" alone does not say
                    // whether it sits under Men, Women or Boys.
                    options = categorySuggestions.map {
                        it.categoryId to listOf(it.path, it.name).filter(String::isNotBlank)
                            .joinToString(" > ")
                    },
                    onSelect = { categoryId = it },
                    placeholder = "Tap to load eBay suggestions",
                    supporting = "Suggested by eBay from the title — required to post",
                    onOpen = onLoadCategories,
                )
                if (item.itemKind == "clothing") {
                    DropdownField(
                        label = "Department",
                        value = department,
                        options = vocabularies.departments.map { it.value to it.label },
                        onSelect = { department = it },
                        supporting = "Required by eBay for clothing",
                    )
                    DropdownField(
                        label = "Size type",
                        value = sizeType,
                        options = vocabularies.sizeTypes.map { it.value to it.label },
                        onSelect = { sizeType = it },
                        // Tags print "S", not "S Regular", so the label pass legitimately
                        // returns null here on most garments. This is a human call, and
                        // eBay refuses the listing without it.
                        supporting = "Usually Regular — tags rarely print this",
                    )
                }
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
                        condition = condition,
                        description = description,
                        categoryId = categoryId,
                        sizeType = sizeType,
                        department = department,
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
