package com.crate.ui.items

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.crate.BuildConfig
import com.crate.data.remote.ItemDto
import com.crate.ui.theme.CrateTheme
import com.crate.util.OnResumeEffect
import com.crate.util.UiState
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.EmptyState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseRefreshBox
import design.pulse.ui.components.PulseSegmentedControl

/** View-side projection of the segmented filter onto ItemsViewModel.setFilter — the
 * remaining statuses (shipped/returned/delisted) surface under "All" via status colors. */
private val FILTER_SEGMENTS = listOf(
    "All" to null,
    "Active" to "active",
    "Sold" to "sold",
    "Drafts" to "draft",
)

@Composable
fun ItemsScreen(
    onItem: (String) -> Unit,
    viewModel: ItemsViewModel = hiltViewModel(),
) {
    val items by viewModel.items.collectAsState()
    val filter by viewModel.filter.collectAsState()
    val refreshing by viewModel.refreshing.collectAsState()

    OnResumeEffect { viewModel.refresh() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        Text("Registry", style = MaterialTheme.typography.headlineSmall)

        PulseSegmentedControl(
            options = FILTER_SEGMENTS.map { it.first },
            selectedIndex = FILTER_SEGMENTS.indexOfFirst { it.second == filter }
                .coerceAtLeast(0),
            onSelect = { index -> viewModel.setFilter(FILTER_SEGMENTS[index].second) },
            channel = CrateTheme.colors.copper.base,
            channelDim = CrateTheme.colors.copper.dim,
        )

        PulseRefreshBox(
            isRefreshing = refreshing,
            onRefresh = viewModel::refresh,
            channel = CrateTheme.colors.copper.base,
            modifier = Modifier.weight(1f),
        ) {
            when (val state = items) {
                is UiState.Loading, UiState.Idle -> Box(
                    Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator(color = CrateTheme.colors.copper.base) }

                is UiState.Error -> PanelCard {
                    Text(state.message, color = MaterialTheme.colorScheme.error)
                }

                is UiState.Success -> if (state.data.isEmpty()) {
                    Column(
                        Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState()),
                    ) {
                        EmptyState(
                            icon = Icons.Outlined.Inventory2,
                            title = "Registry is empty",
                            subtitle = "Everything you list lives here, draft to shipped.",
                        )
                    }
                } else {
                    LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        items(state.data, key = { it.id }) { item ->
                            ItemRow(item = item, onClick = { onItem(item.id) })
                        }
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
internal fun ItemRow(item: ItemDto, onClick: () -> Unit) {
    PanelCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val photo = item.photos.firstOrNull()
            if (photo != null) {
                AsyncImage(
                    model = itemPhotoUrl(item.id, photo.id),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .size(64.dp)
                        .clip(RoundedCornerShape(8.dp)),
                )
                Spacer(Modifier.size(12.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    item.title ?: "Unidentified item",
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.size(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ChannelDot(color = statusColor(item.status))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        item.status.uppercase(),
                        style = MaterialTheme.typography.labelSmall,
                        color = statusColor(item.status),
                    )
                    if (item.templateId != null) {
                        Spacer(Modifier.width(8.dp))
                        ChannelDot(color = CrateTheme.colors.provenance.base)
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "TEMPLATE",
                            style = MaterialTheme.typography.labelSmall,
                            color = CrateTheme.colors.provenance.base,
                        )
                    }
                }
            }
            item.chosenPrice?.let {
                Text(
                    "$$it",
                    style = CrateTheme.dataType.numeral,
                    color = CrateTheme.colors.pricing.base,
                )
            }
        }
    }
}

fun itemPhotoUrl(itemId: String, photoId: String): String =
    BuildConfig.SERVER_URL.trimEnd('/') + "/items/$itemId/photos/$photoId/file"
