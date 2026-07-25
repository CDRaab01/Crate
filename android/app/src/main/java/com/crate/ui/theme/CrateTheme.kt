package com.crate.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import design.pulse.ui.theme.LocalDataTypography
import design.pulse.ui.theme.LocalSpacing
import design.pulse.ui.theme.PulseAccent
import design.pulse.ui.theme.PulseChannel
import design.pulse.ui.theme.PulseDataTypography
import design.pulse.ui.theme.PulseTheme
import design.pulse.ui.theme.Spacing
import design.pulse.ui.theme.darkAmberChannel
import design.pulse.ui.theme.darkBlueChannel
import design.pulse.ui.theme.darkCopperChannel
import design.pulse.ui.theme.darkGreenChannel
import design.pulse.ui.theme.darkPulseStructure
import design.pulse.ui.theme.darkVioletChannel
import design.pulse.ui.theme.lightAmberChannel
import design.pulse.ui.theme.lightBlueChannel
import design.pulse.ui.theme.lightCopperChannel
import design.pulse.ui.theme.lightGreenChannel
import design.pulse.ui.theme.lightPulseStructure
import design.pulse.ui.theme.lightVioletChannel

/**
 * Crate's semantic layer over PULSE — the selling pipeline's channel map (CLAUDE.md §3):
 *  - copper:     hero/primary actions and the listing lifecycle (capture → post)
 *  - sold:       recovery green — sold/shipped/done states
 *  - pricing:    electric blue — comps, price data, money readouts
 *  - attention:  streak amber — stale listing, buyer message, action needed
 *  - provenance: violet — supporting accent (templates, history)
 * Structure (hairlines/panels/glow) and the gradient voices ride along so screens have one stop.
 */
@Immutable
data class CrateColors(
    val copper: PulseChannel,
    val sold: PulseChannel,
    val pricing: PulseChannel,
    val attention: PulseChannel,
    val provenance: PulseChannel,
    val hairline: Color,
    val hairlineStrong: Color,
    val panel: Color,
    val panelHigh: Color,
    val glow: Color,
    /** Heated-metal sweep (OrangeDeep → CopperDeep), Crate's lead voice. */
    val heroGradient: Brush,
)

private fun crateColors(dark: Boolean): CrateColors {
    val structure =
        if (dark) darkPulseStructure(PulseAccent.Copper) else lightPulseStructure(PulseAccent.Copper)
    return CrateColors(
        copper = if (dark) darkCopperChannel() else lightCopperChannel(),
        sold = if (dark) darkGreenChannel() else lightGreenChannel(),
        pricing = if (dark) darkBlueChannel() else lightBlueChannel(),
        attention = if (dark) darkAmberChannel() else lightAmberChannel(),
        provenance = if (dark) darkVioletChannel() else lightVioletChannel(),
        hairline = structure.hairline,
        hairlineStrong = structure.hairlineStrong,
        panel = structure.panel,
        panelHigh = structure.panelHigh,
        glow = structure.glow,
        heroGradient = structure.heroGradient,
    )
}

val LocalCrateColors = staticCompositionLocalOf { crateColors(dark = true) }

@Composable
fun CrateTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    PulseTheme(darkTheme = darkTheme, accent = PulseAccent.Copper) {
        CompositionLocalProvider(
            LocalCrateColors provides crateColors(darkTheme),
        ) {
            content()
        }
    }
}

/** Convenience accessors mirroring `MaterialTheme.*`. */
object CrateTheme {
    val colors: CrateColors
        @Composable @ReadOnlyComposable get() = LocalCrateColors.current
    val dataType: PulseDataTypography
        @Composable @ReadOnlyComposable get() = LocalDataTypography.current
    val spacing: Spacing
        @Composable @ReadOnlyComposable get() = LocalSpacing.current
}
