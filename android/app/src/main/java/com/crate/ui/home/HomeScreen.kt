package com.crate.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import com.crate.ui.components.CrateGlyph
import com.crate.ui.components.CrateWordmark
import com.crate.ui.items.itemPhotoUrl
import com.crate.ui.items.statusColor
import com.crate.ui.theme.CrateTheme
import com.crate.util.OnResumeEffect
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.EmptyState
import design.pulse.ui.components.HeroPanel
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.SectionHeader
import design.pulse.ui.components.StatTile

@Composable
fun HomeScreen(
    onSettings: () -> Unit = {},
    onItem: (String) -> Unit = {},
    onGoReview: () -> Unit = {},
    onGoInbox: () -> Unit = {},
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val stats by viewModel.stats.collectAsState()
    OnResumeEffect { viewModel.refresh() }
    HomeContent(
        stats = stats,
        onSettings = onSettings,
        onItem = onItem,
        onGoReview = onGoReview,
        onGoInbox = onGoInbox,
    )
}

@Composable
internal fun HomeContent(
    stats: HomeStats,
    onSettings: () -> Unit = {},
    onItem: (String) -> Unit = {},
    onGoReview: () -> Unit = {},
    onGoInbox: () -> Unit = {},
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.lg),
    ) {
        HeroPanel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CrateGlyph(size = 30.dp, monochrome = Color.White)
                Spacer(Modifier.width(10.dp))
                CrateWordmark()
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onSettings) {
                    Icon(
                        Icons.Outlined.Settings,
                        contentDescription = "Settings",
                        tint = Color.White.copy(alpha = 0.9f),
                    )
                }
            }
            Text(
                text = "Photo in. Package out.",
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        val empty = stats.loaded &&
            stats.active == 0 && stats.sold == 0 && stats.drafts == 0 && stats.recent.isEmpty()
        if (empty) {
            EmptyState(
                icon = Icons.Outlined.PhotoCamera,
                title = "Nothing in the pipeline",
                subtitle = "Snap your first item from the Sell tab — it comes back " +
                    "identified, cleaned up, and priced for review.",
            )
            return@Column
        }

        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            StatTile(
                label = "Active",
                value = stats.active.toString(),
                channel = CrateTheme.colors.copper.base,
                dense = true,
                modifier = Modifier.weight(1f),
            )
            StatTile(
                label = "Sold",
                value = stats.sold.toString(),
                channel = CrateTheme.colors.sold.base,
                dense = true,
                modifier = Modifier.weight(1f),
            )
            StatTile(
                label = "Drafts",
                value = stats.drafts.toString(),
                channel = CrateTheme.colors.pricing.base,
                dense = true,
                onClick = onGoReview,
                modifier = Modifier.weight(1f),
            )
        }

        if (stats.unresolvedMessages > 0) {
            PanelCard(channel = CrateTheme.colors.attention.base, onClick = onGoInbox) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ChannelDot(color = CrateTheme.colors.attention.base)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = if (stats.unresolvedMessages == 1) {
                            "1 buyer message waiting"
                        } else {
                            "${stats.unresolvedMessages} buyer messages waiting"
                        },
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }

        if (stats.recent.isNotEmpty()) {
            SectionHeader(label = "Recent items", channel = CrateTheme.colors.copper.base)
            LazyRow(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
                items(stats.recent, key = { it.id }) { item ->
                    PanelCard(
                        onClick = { onItem(item.id) },
                        modifier = Modifier.width(140.dp),
                    ) {
                        if (item.photos.isNotEmpty()) {
                            AsyncImage(
                                model = itemPhotoUrl(item.id, item.photos.first().id),
                                contentDescription = null,
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .size(72.dp)
                                    .clip(RoundedCornerShape(8.dp)),
                            )
                            Spacer(Modifier.size(6.dp))
                        }
                        Text(
                            item.title ?: "Unidentified item",
                            style = MaterialTheme.typography.labelMedium,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            item.status.uppercase(),
                            style = MaterialTheme.typography.labelSmall,
                            color = statusColor(item.status),
                        )
                    }
                }
            }
        }
    }
}
