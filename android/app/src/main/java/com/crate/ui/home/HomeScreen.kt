package com.crate.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.SectionHeader
import com.crate.ui.theme.CrateTheme

/**
 * Phase 0 placeholder: proves the copper theme + Pulse components render. The real home surface
 * (capture queue, review stack, registry) arrives with Phases 2-3.
 */
@Composable
fun HomeScreen() {
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
        PanelCard {
            Text(
                text = "Nothing in the crate yet. Capture, review, and selling arrive in the next phases.",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
