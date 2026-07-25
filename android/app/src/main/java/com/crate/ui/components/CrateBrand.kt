package com.crate.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.crate.ui.theme.CrateBrandFont
import com.crate.ui.theme.CrateTheme

/** The brand mark: an isometric open shipping crate. Rim corners sit at L(8,22) B(24,14)
 * R(40,22) F(24,30) on a 48-unit grid; flaps hinge off the back rim edges. */
private object GlyphPaths {
    const val INTERIOR = "M8,22 L24,14 L40,22 L24,30 Z"
    const val LEFT_FACE = "M8,22 L24,30 L24,44 L8,36 Z"
    const val RIGHT_FACE = "M24,30 L40,22 L40,36 L24,44 Z"
    const val LEFT_FLAP = "M8,22 L24,14 L18,3.5 L2,11.5 Z"
    const val RIGHT_FLAP = "M40,22 L24,14 L30,3.5 L46,11.5 Z"
    const val TAPE = "M31,25.5 L34,24 L34,38.2 L31,39.7 Z"
}

private fun buildCrateGlyph(
    interior: Color,
    leftFace: Color,
    rightFace: Color,
    flaps: Color,
    tape: Color,
): ImageVector = ImageVector.Builder(
    name = "CrateGlyph",
    defaultWidth = 24.dp,
    defaultHeight = 24.dp,
    viewportWidth = 48f,
    viewportHeight = 48f,
).apply {
    listOf(
        GlyphPaths.INTERIOR to interior,
        GlyphPaths.LEFT_FACE to leftFace,
        GlyphPaths.RIGHT_FACE to rightFace,
        GlyphPaths.LEFT_FLAP to flaps,
        GlyphPaths.RIGHT_FLAP to flaps,
        GlyphPaths.TAPE to tape,
    ).forEach { (data, color) ->
        path(fill = SolidColor(color)) { addPath(data) }
    }
}.build()

private fun androidx.compose.ui.graphics.vector.PathBuilder.addPath(data: String) {
    // Parse the tiny M/L/Z subset used above — keeps the path constants readable.
    var i = 0
    while (i < data.length) {
        when (data[i]) {
            'M', 'L' -> {
                val end = data.indexOfAny(charArrayOf('M', 'L', 'Z'), i + 1)
                    .let { if (it == -1) data.length else it }
                val (x, y) = data.substring(i + 1, end).trim().split(",").map { it.trim().toFloat() }
                if (data[i] == 'M') moveTo(x, y) else lineTo(x, y)
                i = end
            }
            'Z' -> { close(); i++ }
            else -> i++
        }
    }
}

/**
 * The Crate mark. Full-color copper by default; pass [monochrome] (e.g. white) for
 * on-gradient / single-tint contexts — depth then comes from alpha steps.
 */
@Composable
fun CrateGlyph(
    modifier: Modifier = Modifier,
    size: Dp = 24.dp,
    monochrome: Color? = null,
) {
    val vector = remember(monochrome) {
        if (monochrome != null) {
            buildCrateGlyph(
                interior = monochrome.copy(alpha = 0.45f),
                leftFace = monochrome,
                rightFace = monochrome.copy(alpha = 0.80f),
                flaps = monochrome.copy(alpha = 0.90f),
                tape = monochrome.copy(alpha = 0.55f),
            )
        } else {
            buildCrateGlyph(
                interior = Color(0xFF6B3512),
                leftFace = Color(0xFFC2410C),
                rightFace = Color(0xFF9A4D1B),
                flaps = Color(0xFFD98A5B),
                tape = Color(0xFF6B3512),
            )
        }
    }
    Image(
        imageVector = vector,
        contentDescription = null,
        modifier = modifier.size(size),
    )
}

/** "CRATE" in the stencil brand face — wordmark only, never body text. */
@Composable
fun CrateWordmark(
    modifier: Modifier = Modifier,
    large: Boolean = false,
    color: Color = Color.White,
) {
    Text(
        text = "CRATE",
        modifier = modifier,
        fontFamily = CrateBrandFont,
        fontSize = if (large) 40.sp else 22.sp,
        letterSpacing = 0.12.em,
        color = color,
    )
}

/** The app tile (suite BrandLogo precedent): hero-gradient rounded square + white glyph. */
@Composable
fun BrandLogo(
    modifier: Modifier = Modifier,
    size: Dp = 80.dp,
) {
    Box(
        modifier = modifier
            .size(size)
            .background(CrateTheme.colors.heroGradient, RoundedCornerShape(size / 3.5f)),
        contentAlignment = Alignment.Center,
    ) {
        CrateGlyph(size = size * 0.55f, monochrome = Color.White)
    }
}
