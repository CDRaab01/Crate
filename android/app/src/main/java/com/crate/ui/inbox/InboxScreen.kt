package com.crate.ui.inbox

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Inbox
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
import com.crate.util.OnResumeEffect
import com.crate.util.UiState
import design.pulse.ui.components.Caption
import design.pulse.ui.components.ChannelDot
import design.pulse.ui.components.EmptyState
import design.pulse.ui.components.ErrorState
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.PulseRefreshBox

@Composable
fun InboxScreen(
    viewModel: InboxViewModel = hiltViewModel(),
) {
    val messages by viewModel.messages.collectAsState()
    val refreshing by viewModel.refreshing.collectAsState()

    OnResumeEffect { viewModel.refresh() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        Text("Inbox", style = MaterialTheme.typography.headlineSmall)
        Caption(text = "Crate flags — replies happen in the eBay app.")

        PulseRefreshBox(
            isRefreshing = refreshing,
            onRefresh = viewModel::refresh,
            channel = CrateTheme.colors.attention.base,
            modifier = Modifier.weight(1f),
        ) {
            when (val state = messages) {
                is UiState.Loading, UiState.Idle -> Box(
                    Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator(color = CrateTheme.colors.attention.base) }

                is UiState.Error -> ErrorState(
                    icon = Icons.Outlined.CloudOff,
                    title = "Couldn't load messages",
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
                            icon = Icons.Outlined.Inbox,
                            title = "No buyer messages",
                            subtitle = "Quiet is good.",
                        )
                    }
                } else {
                    LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        items(state.data, key = { it.id }) { message ->
                            MessageCard(
                                message = message,
                                onResolve = { viewModel.resolve(message.id) },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun MessageCard(
    message: com.crate.data.remote.MessageDto,
    onResolve: () -> Unit,
) {
    val typeColor = if (message.messageType == "return_request") {
        MaterialTheme.colorScheme.error
    } else {
        CrateTheme.colors.attention.base
    }
    PanelCard(channel = if (!message.resolved) CrateTheme.colors.attention.base else null) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ChannelDot(color = typeColor)
                Spacer(Modifier.size(6.dp))
                Text(
                    message.messageType.replace('_', ' ').uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = typeColor,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    message.flaggedAt.take(10),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(message.content, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!message.resolved) {
                    PulseButton(
                        text = "Mark resolved",
                        onClick = onResolve,
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
