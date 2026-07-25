package com.crate.util

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import java.io.ByteArrayOutputStream

/**
 * Downscale a photo before upload. Camera captures on modern phones routinely exceed the
 * server's 8 MB cap (and the vision model reads a 1600px item photo just as well), so both
 * the camera and gallery paths route through this — it's a requirement, not an optimization.
 * (Suite-shared idiom, ported from Cookbook's util/ImageBytes.kt.)
 */
object ImageBytes {

    private const val MAX_DIMENSION = 1600
    private const val JPEG_QUALITY = 85

    /** Re-encode as JPEG with the long edge capped at [MAX_DIMENSION]px. Returns the original
     * bytes when decoding fails (let the server reject what it can't read). */
    fun downscaleToJpeg(bytes: ByteArray): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return bytes

        // Power-of-two subsampling gets within 2x of the target cheaply...
        var sampleSize = 1
        val longEdge = maxOf(bounds.outWidth, bounds.outHeight)
        while (longEdge / (sampleSize * 2) >= MAX_DIMENSION) {
            sampleSize *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sampleSize }
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options) ?: return bytes

        // ...then an exact scale lands on the cap when still over it.
        val scale = MAX_DIMENSION.toFloat() / maxOf(decoded.width, decoded.height)
        val bitmap = if (scale < 1f) {
            Bitmap.createScaledBitmap(
                decoded,
                (decoded.width * scale).toInt().coerceAtLeast(1),
                (decoded.height * scale).toInt().coerceAtLeast(1),
                true,
            ).also { if (it != decoded) decoded.recycle() }
        } else {
            decoded
        }

        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
        bitmap.recycle()
        return out.toByteArray()
    }
}
