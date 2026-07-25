package com.crate.ui.ship

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Print
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.crate.data.remote.ItemDto
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

/**
 * The confirm-then-buy flow (locked decision): the AI's weight/dims guess arrives
 * pre-filled and editable; rates are quoted only against confirmed numbers; one explicit
 * tap buys the label (real money) and pushes tracking to the eBay order.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipScreen(
    onBack: () -> Unit = {},
    viewModel: ShipViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val itemState by viewModel.item.collectAsState()
    val rates by viewModel.rates.collectAsState()
    val label by viewModel.label.collectAsState()
    val buyError by viewModel.buyError.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ship") },
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

                is UiState.Success -> {
                    val item = state.data
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(CrateTheme.spacing.lg),
                        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
                    ) {
                        Text(
                            item.title ?: "Ship item",
                            style = MaterialTheme.typography.headlineSmall,
                        )

                        if (label != null) {
                            LabelBought(
                                tracking = label!!.trackingNumber ?: "—",
                                labelUrl = label!!.labelUrl,
                                onOpen = { url ->
                                    context.startActivity(
                                        Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                    )
                                },
                            )
                        } else {
                            WeightConfirmCard(item = item, onConfirm = viewModel::confirmWeight)

                            when (val rateState = rates) {
                                is UiState.Idle -> {}
                                is UiState.Loading -> CircularProgressIndicator(
                                    color = CrateTheme.colors.pricing.base
                                )
                                is UiState.Error -> PanelCard {
                                    Text(
                                        rateState.message,
                                        color = MaterialTheme.colorScheme.error,
                                    )
                                }
                                is UiState.Success -> {
                                    SectionHeader(
                                        label = "Rates",
                                        channel = CrateTheme.colors.pricing.base,
                                    )
                                    val cheapest = rateState.data
                                        .minByOrNull { it.amount.toDoubleOrNull() ?: Double.MAX_VALUE }
                                    rateState.data.forEach { rate ->
                                        RateRow(
                                            rate = rate,
                                            cheapest = rate.rateId == cheapest?.rateId,
                                            onBuy = { viewModel.buyLabel(rate) },
                                        )
                                    }
                                }
                            }

                            buyError?.let {
                                Text(
                                    it,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun RateRow(
    rate: com.crate.data.remote.RateDto,
    onBuy: () -> Unit,
    cheapest: Boolean = false,
) {
    PanelCard(channel = if (cheapest) CrateTheme.colors.sold.base else null) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    "${rate.provider} · ${rate.service}",
                    style = MaterialTheme.typography.titleSmall,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        rate.estimatedDays?.let { "~$it days" } ?: "",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (cheapest) {
                        Text(
                            "  ·  CHEAPEST",
                            style = MaterialTheme.typography.labelSmall,
                            color = CrateTheme.colors.sold.base,
                        )
                    }
                }
            }
            PulseButton(
                text = "Buy $${rate.amount}",
                onClick = onBuy,
                compact = true,
            )
        }
    }
}

@Composable
internal fun WeightConfirmCard(
    item: ItemDto,
    onConfirm: (String, Double, Double, Double) -> Unit,
) {
    var weight by remember { mutableStateOf(item.weightOzEst ?: "") }
    var l by remember { mutableStateOf(item.dimsInEst?.get("l")?.toString() ?: "") }
    var w by remember { mutableStateOf(item.dimsInEst?.get("w")?.toString() ?: "") }
    var h by remember { mutableStateOf(item.dimsInEst?.get("h")?.toString() ?: "") }

    SectionHeader(label = "Confirm weight & size", channel = CrateTheme.colors.attention.base)
    PanelCard {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            if (item.weightConfirmed) {
                "Confirmed — edit and re-confirm if the box changed."
            } else {
                "AI estimate pre-filled. Wrong-weight labels cost real money — check the scale."
            },
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedTextField(
            value = weight,
            onValueChange = { weight = it.filter { c -> c.isDigit() || c == '.' } },
            label = { Text("Weight (oz, packed)") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            OutlinedTextField(
                value = l,
                onValueChange = { l = it.filter { c -> c.isDigit() || c == '.' } },
                label = { Text("L in") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = w,
                onValueChange = { w = it.filter { c -> c.isDigit() || c == '.' } },
                label = { Text("W in") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = h,
                onValueChange = { h = it.filter { c -> c.isDigit() || c == '.' } },
                label = { Text("H in") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1f),
            )
        }
        PulseButton(
            text = "Confirm & get rates",
            onClick = {
                val ld = l.toDoubleOrNull()
                val wd = w.toDoubleOrNull()
                val hd = h.toDoubleOrNull()
                if (weight.toDoubleOrNull() != null && ld != null && wd != null && hd != null) {
                    onConfirm(weight, ld, wd, hd)
                }
            },
            enabled = weight.isNotBlank() && l.isNotBlank() && w.isNotBlank() && h.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        )
        }
    }
}

@Composable
internal fun LabelBought(
    tracking: String,
    labelUrl: String?,
    onOpen: (String) -> Unit,
) {
    SectionHeader(label = "Label bought", channel = CrateTheme.colors.sold.base)
    PanelCard {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Tracking: $tracking", style = MaterialTheme.typography.bodyMedium)
        Text(
            "Tracking was pushed to the eBay order. Print the label, box it up, done.",
            style = MaterialTheme.typography.bodySmall,
        )
        labelUrl?.let { url ->
            Spacer(Modifier.size(4.dp))
            PulseButton(
                text = "Open label PDF",
                onClick = { onOpen(url) },
                leadingIcon = {
                    Icon(
                        Icons.Outlined.Print,
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
}
