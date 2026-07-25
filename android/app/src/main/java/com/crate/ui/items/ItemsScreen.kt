package com.crate.ui.items

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.crate.BuildConfig
import com.crate.data.remote.ItemDto
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.SectionHeader

@Composable
fun ItemsScreen(
    onItem: (String) -> Unit,
    viewModel: ItemsViewModel = hiltViewModel(),
) {
    val items by viewModel.items.collectAsState()
    val filter by viewModel.filter.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        SectionHeader(label = "Registry", channel = CrateTheme.colors.copper.base)

        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(listOf<String?>(null) + ItemsViewModel.STATUSES) { status ->
                FilterChip(
                    selected = filter == status,
                    onClick = { viewModel.setFilter(status) },
                    label = { Text(status ?: "all") },
                )
            }
        }

        when (val state = items) {
            is UiState.Loading, UiState.Idle -> Box(
                Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator(color = CrateTheme.colors.copper.base) }

            is UiState.Error -> PanelCard {
                Text(state.message, color = MaterialTheme.colorScheme.error)
            }

            is UiState.Success -> if (state.data.isEmpty()) {
                PanelCard { Text("Nothing here yet.") }
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
                    items(state.data, key = { it.id }) { item ->
                        ItemRow(item = item, onClick = { onItem(item.id) })
                    }
                }
            }
        }
    }
}

@Composable
fun statusColor(status: String): Color = when (status) {
    "sold", "shipped" -> CrateTheme.colors.sold.base
    "active" -> CrateTheme.colors.copper.base
    "returned", "delisted" -> CrateTheme.colors.attention.base
    else -> MaterialTheme.colorScheme.onSurfaceVariant // draft
}

@Composable
private fun ItemRow(item: ItemDto, onClick: () -> Unit) {
    PanelCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val photo = item.photos.firstOrNull()
            if (photo != null) {
                AsyncImage(
                    model = itemPhotoUrl(item.id, photo.id),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .size(56.dp)
                        .clip(RoundedCornerShape(8.dp)),
                )
                Spacer(Modifier.size(12.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    item.title ?: "Unidentified item",
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        item.status.uppercase(),
                        style = MaterialTheme.typography.labelSmall,
                        color = statusColor(item.status),
                    )
                    item.chosenPrice?.let {
                        Spacer(Modifier.size(8.dp))
                        Text(
                            "$$it",
                            style = CrateTheme.dataType.numeral,
                            color = CrateTheme.colors.pricing.base,
                        )
                    }
                    if (item.templateId != null) {
                        Spacer(Modifier.size(8.dp))
                        Text(
                            "FROM TEMPLATE",
                            style = MaterialTheme.typography.labelSmall,
                            color = CrateTheme.colors.provenance.base,
                        )
                    }
                }
            }
        }
    }
}

fun itemPhotoUrl(itemId: String, photoId: String): String =
    BuildConfig.SERVER_URL.trimEnd('/') + "/items/$itemId/photos/$photoId/file"
