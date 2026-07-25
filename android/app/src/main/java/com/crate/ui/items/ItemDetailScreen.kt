package com.crate.ui.items

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.crate.data.remote.ItemDto
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

@Composable
fun ItemDetailScreen(
    onShip: (String) -> Unit = {},
    viewModel: ItemDetailViewModel = hiltViewModel(),
) {
    val itemState by viewModel.item.collectAsState()
    val priceEvents by viewModel.priceEvents.collectAsState()
    val sale by viewModel.sale.collectAsState()

    when (val state = itemState) {
        is UiState.Loading, UiState.Idle -> Box(
            Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center,
        ) { CircularProgressIndicator(color = CrateTheme.colors.copper.base) }

        is UiState.Error -> Box(Modifier.fillMaxSize().padding(CrateTheme.spacing.lg)) {
            PanelCard { Text(state.message, color = MaterialTheme.colorScheme.error) }
        }

        is UiState.Success -> Detail(state.data, priceEvents, sale, onShip)
    }
}

@Composable
private fun Detail(
    item: ItemDto,
    priceEvents: List<com.crate.data.remote.PriceEventDto>,
    sale: com.crate.data.remote.SaleDto?,
    onShip: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        if (item.photos.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(item.photos, key = { it.id }) { photo ->
                    AsyncImage(
                        model = itemPhotoUrl(item.id, photo.id),
                        contentDescription = "item photo",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(140.dp)
                            .clip(RoundedCornerShape(12.dp)),
                    )
                }
            }
        }

        Text(item.title ?: "Unidentified item", style = MaterialTheme.typography.headlineSmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                item.status.uppercase(),
                style = MaterialTheme.typography.labelMedium,
                color = statusColor(item.status),
            )
            if (item.templateId != null) {
                Spacer(Modifier.size(8.dp))
                Text(
                    "FROM TEMPLATE",
                    style = MaterialTheme.typography.labelSmall,
                    color = CrateTheme.colors.provenance.base,
                )
            }
        }

        val subtitle = listOfNotNull(item.brand, item.model, item.condition?.replace('_', ' '))
            .joinToString(" · ")
        if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodyMedium)

        item.description?.let { PanelCard { Text(it, style = MaterialTheme.typography.bodyMedium) } }

        SectionHeader(label = "Pricing", channel = CrateTheme.colors.pricing.base)
        PanelCard {
            PriceLine("Quick sale", item.quickSalePrice)
            PriceLine("Patient", item.patientPrice)
            PriceLine("Chosen", item.chosenPrice)
            if (item.quickSalePrice == null && item.patientPrice == null) {
                Text(
                    "No prices yet — pricing research arrives in Phase 4.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (priceEvents.isNotEmpty()) {
            SectionHeader(label = "Price history", channel = CrateTheme.colors.pricing.base)
            PanelCard {
                priceEvents.forEach { event ->
                    Row {
                        Text(
                            "$${event.oldPrice} → $${event.newPrice}",
                            style = CrateTheme.dataType.numeral,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            event.reason.replace('_', ' '),
                            style = MaterialTheme.typography.labelSmall,
                            color = CrateTheme.colors.attention.base,
                        )
                    }
                }
            }
        }

        if (sale != null) {
            SectionHeader(label = "Sale", channel = CrateTheme.colors.sold.base)
            PanelCard {
                Text(
                    "Sold to ${sale.buyerUsername} for $${sale.salePrice}",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "Ship status: ${sale.shipStatus.replace('_', ' ')}" +
                        (sale.trackingNumber?.let { "  ·  $it" } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                )
                sale.buyerAddress?.let { address ->
                    Text(
                        address.toString(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (item.status == "sold") {
                    PulseButton(
                        text = "Ship it",
                        onClick = { onShip(item.id) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        SectionHeader(label = "Shipping estimate", channel = CrateTheme.colors.copper.base)
        PanelCard {
            Text(
                buildString {
                    append(item.weightOzEst?.let { "$it oz" } ?: "no weight estimate")
                    item.dimsInEst?.let { d ->
                        append("  ·  ${d["l"]}×${d["w"]}×${d["h"]} in")
                    }
                    if (!item.weightConfirmed) append("  (unconfirmed)")
                },
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun PriceLine(label: String, value: String?) {
    if (value == null) return
    Row {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text(
            "$$value",
            style = CrateTheme.dataType.numeral,
            color = CrateTheme.colors.pricing.base,
        )
    }
}
