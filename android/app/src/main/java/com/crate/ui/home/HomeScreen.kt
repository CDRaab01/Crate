package com.crate.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.crate.ui.theme.CrateTheme
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

@Composable
fun HomeScreen(
    onCapture: () -> Unit = {},
    onReview: () -> Unit = {},
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.lg),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(CrateTheme.colors.heroGradient)
                .padding(CrateTheme.spacing.lg),
        ) {
            Text(
                text = "Crate",
                style = MaterialTheme.typography.headlineMedium,
                color = Color.White,
            )
            Text(
                text = "Photo → listed → sold → shipped.",
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        SectionHeader(label = "Pipeline", channel = CrateTheme.colors.copper.base)
        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            PulseButton(
                text = "Capture",
                onClick = onCapture,
                modifier = Modifier.weight(1f),
            )
            PulseButton(
                text = "Review",
                onClick = onReview,
                tonal = true,
                modifier = Modifier.weight(1f),
            )
        }
        PanelCard {
            Text(
                text = "Snap items in a batch — each becomes a cleaned-up, identified draft " +
                    "in the review stack. Pricing, posting, and shipping arrive phase by phase.",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
