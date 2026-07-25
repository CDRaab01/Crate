package com.crate.ui.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.crate.BuildConfig
import com.crate.ui.auth.AuthViewModel
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.Caption
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.ProfileHeader
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.PulseSegmentedControl
import design.pulse.ui.components.SettingsSection

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSignedOut: () -> Unit,
    onBack: () -> Unit = {},
    viewModel: SettingsViewModel = hiltViewModel(),
    authViewModel: AuthViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val ebay by viewModel.ebayStatus.collectAsState()
    val connectUrl by viewModel.connectUrl.collectAsState()
    val user by viewModel.user.collectAsState()
    val userSettings by viewModel.userSettings.collectAsState()

    // The one-time seller consent runs in the browser (redirect lands on the server's
    // tailnet callback, not in the app).
    LaunchedEffect(connectUrl) {
        connectUrl?.let { url ->
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            viewModel.connectUrlConsumed()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = CrateTheme.spacing.lg)
                .padding(bottom = CrateTheme.spacing.xl),
            verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
        ) {
            user?.let {
                ProfileHeader(
                    name = it.name,
                    email = it.email,
                    channel = CrateTheme.colors.copper.base,
                    channelDim = CrateTheme.colors.copper.dim,
                )
            }

            SettingsSection(title = "eBay") {
                when (val state = ebay) {
                    is UiState.Loading, UiState.Idle -> PanelCard { Text("Checking connection…") }
                    is UiState.Error -> PanelCard {
                        Text(state.message, color = MaterialTheme.colorScheme.error)
                    }
                    is UiState.Success -> PanelCard {
                        val s = state.data
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                ChannelDot(
                                    color = if (s.connected) {
                                        CrateTheme.colors.sold.base
                                    } else {
                                        CrateTheme.colors.attention.base
                                    },
                                )
                                Text(
                                    text = when {
                                        !s.configured -> "  Not connected"
                                        s.connected -> "  Connected (${s.environment})"
                                        else -> "  Ready to connect"
                                    },
                                    style = MaterialTheme.typography.titleSmall,
                                )
                            }
                            Text(
                                when {
                                    !s.configured -> "eBay isn't set up on the server yet. " +
                                        "Pricing and posting switch on once it's connected."
                                    s.connected -> "Renews automatically — access expires " +
                                        "${s.refreshExpiresAt?.take(10) ?: "—"}."
                                    else -> "Link your seller account to enable pricing " +
                                        "and posting."
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (s.configured && !s.connected) {
                                Spacer(Modifier.size(4.dp))
                                PulseButton(
                                    text = "Connect eBay",
                                    onClick = { viewModel.startConnect() },
                                    gradient = CrateTheme.colors.heroGradient,
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
                }
            }

            userSettings?.let { s ->
                SettingsSection(title = "Selling") {
                    DropPolicyCard(
                        enabled = s.dropsEnabled,
                        intervalDays = s.dropIntervalDays,
                        stepPercent = s.dropStepPercent,
                        preference = s.shippingPreference,
                        onSave = viewModel::saveDropPolicy,
                    )
                }
            }

            SettingsSection(title = "Account") {
                PulseButton(
                    text = "Sign out",
                    onClick = {
                        authViewModel.signOut()
                        onSignedOut()
                    },
                    tonal = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Caption(text = "Crate ${BuildConfig.VERSION_NAME}")
            }
        }
    }
}

@Composable
internal fun DropPolicyCard(
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
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(
                Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text("Automatic price drops", style = MaterialTheme.typography.titleSmall)
                Text(
                    "Unsold listings drop $step% every $interval days, never below your " +
                        "quick-sale floor. Every drop is logged and you're notified.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.size(12.dp))
            Switch(checked = dropsOn, onCheckedChange = { dropsOn = it })
        }
        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            OutlinedTextField(
                value = interval,
                onValueChange = { interval = it.filter(Char::isDigit).take(2) },
                label = { Text("Every N days") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = step,
                onValueChange = { step = it.filter { c -> c.isDigit() || c == '.' } },
                label = { Text("Step %") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1f),
            )
        }
        Caption(text = "Shipping preference")
        PulseSegmentedControl(
            options = listOf("Cheapest", "Fastest"),
            selectedIndex = if (fastest) 1 else 0,
            onSelect = { fastest = it == 1 },
            channel = CrateTheme.colors.copper.base,
            channelDim = CrateTheme.colors.copper.dim,
        )
        PulseButton(
            text = "Save",
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
}
