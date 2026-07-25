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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.LocalShipping
import androidx.compose.material.icons.outlined.Scale
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import com.crate.data.remote.ItemDto
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader
import design.pulse.ui.components.Sparkline
import kotlinx.serialization.json.JsonPrimitive

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ItemDetailScreen(
    onShip: (String) -> Unit = {},
    onBack: () -> Unit = {},
    viewModel: ItemDetailViewModel = hiltViewModel(),
) {
    val itemState by viewModel.item.collectAsState()
    val priceEvents by viewModel.priceEvents.collectAsState()
    val sale by viewModel.sale.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        (itemState as? UiState.Success)?.data?.title ?: "Item",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when (val state = itemState) {
                is UiState.Loading, UiState.Idle -> Box(
                    Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator(color = CrateTheme.colors.copper.base) }

                is UiState.Error -> Box(Modifier.fillMaxSize().padding(CrateTheme.spacing.lg)) {
                    PanelCard { Text(state.message, color = MaterialTheme.colorScheme.error) }
                }

                is UiState.Success -> Detail(
                    item = state.data,
                    priceEvents = priceEvents,
                    sale = sale,
                    onShip = onShip,
                    onDelist = { viewModel.delist {} },
                    onRelist = { viewModel.relist {} },
                )
            }
        }
    }
}

@Composable
internal fun Detail(
    item: ItemDto,
    priceEvents: List<com.crate.data.remote.PriceEventDto>,
    sale: com.crate.data.remote.SaleDto?,
    onShip: (String) -> Unit,
    onDelist: () -> Unit = {},
    onRelist: () -> Unit = {},
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
                            .size(160.dp)
                            .clip(RoundedCornerShape(16.dp)),
                    )
                }
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            ChannelDot(color = statusColor(item.status))
            Spacer(Modifier.size(6.dp))
            Text(
                item.status.uppercase(),
                style = MaterialTheme.typography.labelMedium,
                color = statusColor(item.status),
            )
            if (item.templateId != null) {
                Spacer(Modifier.size(12.dp))
                ChannelDot(color = CrateTheme.colors.provenance.base)
                Spacer(Modifier.size(6.dp))
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
                    "Pricing appears once your eBay account is linked in Settings.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (priceEvents.isNotEmpty()) {
            SectionHeader(label = "Price history", channel = CrateTheme.colors.pricing.base)
            PanelCard {
                if (priceEvents.size >= 3) {
                    val points = (listOf(priceEvents.first().oldPrice) +
                        priceEvents.map { it.newPrice })
                        .mapNotNull { it.toFloatOrNull() }
                    if (points.size >= 2) {
                        Sparkline(
                            values = points,
                            channel = CrateTheme.colors.pricing.base,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
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
                    val readable = address.values.joinToString(", ") { value ->
                        (value as? JsonPrimitive)?.content ?: value.toString()
                    }
                    Text(
                        readable,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (item.status == "sold") {
                    PulseButton(
                        text = "Ship it",
                        onClick = { onShip(item.id) },
                        gradient = CrateTheme.colors.heroGradient,
                        leadingIcon = {
                            Icon(
                                Icons.Outlined.LocalShipping,
                                contentDescription = null,
                                tint = Color.White,
                                modifier = Modifier.size(18.dp),
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        SectionHeader(label = "Shipping estimate", channel = CrateTheme.colors.copper.base)
        PanelCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Outlined.Scale,
                    contentDescription = null,
                    tint = CrateTheme.colors.copper.base,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.size(10.dp))
                Text(
                    buildString {
                        append(item.weightOzEst?.let { "$it oz" } ?: "No weight estimate")
                        item.dimsInEst?.let { d ->
                            append("  ·  ${d["l"]}×${d["w"]}×${d["h"]} in")
                        }
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            if (!item.weightConfirmed) {
                Text(
                    "You'll confirm the packed weight at ship time.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        when (item.status) {
            "active" -> PulseButton(
                text = "Delist from eBay",
                onClick = onDelist,
                tonal = true,
                compact = true,
            )
            "delisted", "returned" -> PulseButton(
                text = "Relist on eBay",
                onClick = onRelist,
                compact = true,
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
