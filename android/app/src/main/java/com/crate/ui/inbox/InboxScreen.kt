package com.crate.ui.inbox

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.crate.ui.theme.CrateTheme
import com.crate.util.UiState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

@Composable
fun InboxScreen(
    viewModel: InboxViewModel = hiltViewModel(),
) {
    val messages by viewModel.messages.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        SectionHeader(label = "Buyer messages", channel = CrateTheme.colors.attention.base)
        Text(
            "Crate flags — replies happen in the eBay app.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        when (val state = messages) {
            is UiState.Loading, UiState.Idle -> Box(
                Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator(color = CrateTheme.colors.attention.base) }

            is UiState.Error -> PanelCard {
                Text(state.message, color = MaterialTheme.colorScheme.error)
            }

            is UiState.Success -> if (state.data.isEmpty()) {
                PanelCard { Text("No buyer messages. Quiet is good.") }
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
                    items(state.data, key = { it.id }) { message ->
                        PanelCard {
                            Text(
                                message.messageType.replace('_', ' ').uppercase(),
                                style = MaterialTheme.typography.labelSmall,
                                color = if (message.messageType == "return_request") {
                                    MaterialTheme.colorScheme.error
                                } else {
                                    CrateTheme.colors.attention.base
                                },
                            )
                            Text(message.content, style = MaterialTheme.typography.bodyMedium)
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                if (!message.resolved) {
                                    PulseButton(
                                        text = "Mark resolved",
                                        onClick = { viewModel.resolve(message.id) },
                                        compact = true,
                                    )
                                } else {
                                    Text(
                                        "RESOLVED",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = CrateTheme.colors.sold.base,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
