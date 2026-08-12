package com.crate.ui.components

import com.crate.data.remote.ItemDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The pure display helpers behind the garment surfaces. The server owns the vocabularies and
 * decides what is missing (CLAUDE.md §9); these only format, so the interesting cases are
 * partial records — the normal state of an archive that is still being filled in.
 */
class ApparelFieldsTest {

    private fun item(
        kind: String = "clothing",
        department: String? = "mens",
        size: String? = "M",
        color: String? = "Navy",
        style: String? = "Button-Up",
        measurements: Map<String, Double>? = null,
    ) = ItemDto(
        id = "i1",
        status = "draft",
        createdAt = "2026-08-12",
        itemKind = kind,
        department = department,
        size = size,
        color = color,
        style = style,
        measurementsIn = measurements,
    )

    @Test
    fun `apparel summary joins the known fields in order`() {
        assertEquals("mens · M · Navy · Button-Up", apparelSummary(item()))
    }

    @Test
    fun `apparel summary skips what has not been recorded`() {
        assertEquals("M · Navy", apparelSummary(item(department = null, style = null)))
        assertEquals("", apparelSummary(item(department = null, size = null, color = null, style = null)))
    }

    @Test
    fun `general goods have no garment line`() {
        // A lure has no size or department; rendering an empty garment row on it would be noise.
        assertEquals("", apparelSummary(item(kind = "general")))
    }

    @Test
    fun `measurement summary shows only the measurements actually taken`() {
        val summary = measurementSummary(item(measurements = mapOf("chest" to 21.0, "length" to 29.0)))
        assertEquals("21\" chest · 29\" length", summary)
    }

    @Test
    fun `measurement summary keeps a fractional reading but trims a whole one`() {
        // Tape readings are typically to the half inch; 21.0 should not render as 21.0".
        val summary = measurementSummary(item(measurements = mapOf("chest" to 21.5, "length" to 29.0)))
        assertEquals("21.5\" chest · 29\" length", summary)
    }

    @Test
    fun `measurement summary is ordered by garment convention not map order`() {
        // Buyers ask for pit-to-pit first; a map's iteration order must not decide that.
        val summary = measurementSummary(
            item(measurements = linkedMapOf("inseam" to 32.0, "chest" to 21.0, "waist" to 17.0))
        )
        assertEquals("21\" chest · 17\" waist · 32\" inseam", summary)
    }

    @Test
    fun `no measurements renders nothing`() {
        assertEquals("", measurementSummary(item(measurements = null)))
        assertEquals("", measurementSummary(item(measurements = emptyMap())))
    }

    @Test
    fun `unknown measurement keys are ignored rather than rendered raw`() {
        assertEquals("21\" chest", measurementSummary(item(measurements = mapOf("chest" to 21.0, "collar" to 16.0))))
    }

    @Test
    fun `field labels are human readable`() {
        assertEquals("Size type", fieldLabel("size_type"))
        assertEquals("Measurements", fieldLabel("measurements"))
        assertEquals("Brand", fieldLabel("brand"))
    }

    @Test
    fun `unknown field names still render legibly`() {
        // The server can add a completeness field before the client knows its label; the
        // fallback must stay readable rather than printing a raw snake_case key.
        assertEquals("Some new field", fieldLabel("some_new_field"))
    }

    @Test
    fun `defaults keep pre-apparel items intact`() {
        // A server that has not yet been redeployed omits the apparel block entirely.
        val legacy = ItemDto(id = "i1", status = "draft", createdAt = "2026-08-12")
        assertEquals("general", legacy.itemKind)
        assertTrue(legacy.missingHandOnly.isEmpty())
        assertEquals("", apparelSummary(legacy))
    }
}
