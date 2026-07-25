package com.crate.ui.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.hilt.navigation.compose.hiltViewModel
import com.crate.ui.auth.AuthViewModel
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

@Composable
fun SettingsScreen(
    onSignedOut: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel(),
    authViewModel: AuthViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val ebay by viewModel.ebayStatus.collectAsState()
    val connectUrl by viewModel.connectUrl.collectAsState()

    // The one-time seller consent runs in the browser (redirect lands on the server's
    // tailnet callback, not in the app).
    LaunchedEffect(connectUrl) {
        connectUrl?.let { url ->
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            viewModel.connectUrlConsumed()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        SectionHeader(label = "eBay", channel = CrateTheme.colors.copper.base)
        when (val state = ebay) {
            is UiState.Loading, UiState.Idle -> PanelCard { Text("Checking connection…") }
            is UiState.Error -> PanelCard {
                Text(state.message, color = MaterialTheme.colorScheme.error)
            }
            is UiState.Success -> PanelCard {
                val s = state.data
                Text(
                    when {
                        !s.configured -> "Keyset not configured on the server yet — pricing " +
                            "and posting stay off until the eBay developer account exists."
                        s.connected -> "Connected (${s.environment}). Refresh token expires " +
                            "${s.refreshExpiresAt?.take(10) ?: "—"} (~18-month lifetime; " +
                            "Crate will warn well before)."
                        else -> "Keyset configured, seller account not connected."
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (state.data.configured && !state.data.connected) {
                    PulseButton(
                        text = "Connect eBay (one-time consent)",
                        onClick = { viewModel.startConnect() },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                PulseButton(
                    text = "Refresh status",
                    onClick = { viewModel.refresh() },
                    tonal = true,
                    compact = true,
                )
            }
        }

        val userSettings by viewModel.userSettings.collectAsState()
        userSettings?.let { s ->
            SectionHeader(label = "Price drops", channel = CrateTheme.colors.pricing.base)
            DropPolicyCard(
                enabled = s.dropsEnabled,
                intervalDays = s.dropIntervalDays,
                stepPercent = s.dropStepPercent,
                preference = s.shippingPreference,
                onSave = viewModel::saveDropPolicy,
            )
        }

        SectionHeader(label = "Account", channel = CrateTheme.colors.attention.base)
        PulseButton(
            text = "Sign out",
            onClick = {
                authViewModel.signOut()
                onSignedOut()
            },
            tonal = true,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun DropPolicyCard(
    enabled: Boolean,
    intervalDays: Int,
    stepPercent: String,
    preference: String,
    onSave: (Boolean, Int, String, String) -> Unit,
) {
    var dropsOn by remember(enabled) { mutableStateOf(enabled) }
    var interval by remember(intervalDays) { mutableStateOf(intervalDays.toString()) }
    var step by remember(stepPercent) { mutableStateOf(stepPercent) }
    var fastest by remember(preference) { mutableStateOf(preference == "fastest") }

    PanelCard {
        Text(
            "Unsold listings drop -$step% every $interval days, never below the quick-sale " +
                "floor. Deterministic policy — every drop is logged and pinged.",
            style = MaterialTheme.typography.bodySmall,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Auto price drops", modifier = Modifier.weight(1f))
            Switch(checked = dropsOn, onCheckedChange = { dropsOn = it })
        }
        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            OutlinedTextField(
                value = interval,
                onValueChange = { interval = it.filter(Char::isDigit).take(2) },
                label = { Text("Every N days") },
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = step,
                onValueChange = { step = it.filter { c -> c.isDigit() || c == '.' } },
                label = { Text("Step %") },
                modifier = Modifier.weight(1f),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Prefer fastest shipping (default: cheapest)", modifier = Modifier.weight(1f))
            Switch(checked = fastest, onCheckedChange = { fastest = it })
        }
        PulseButton(
            text = "Save policy",
            onClick = {
                interval.toIntOrNull()?.let { days ->
                    onSave(dropsOn, days, step, if (fastest) "fastest" else "cheapest")
                }
            },
            enabled = interval.toIntOrNull() != null && step.toDoubleOrNull() != null,
            compact = true,
        )
    }
}
