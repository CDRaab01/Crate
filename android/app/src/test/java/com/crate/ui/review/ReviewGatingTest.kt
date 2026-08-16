package com.crate.ui.review

import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemPhotoDto
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The "Post to eBay" gate must mirror the server's `sell._require_ready`.
 *
 * This matters more than a normal disabled-button check. eBay validates clothing item
 * specifics at **publish** — after the photos have been pushed to eBay Picture Services, the
 * inventory item created and the offer created. A hopeful tap on an incomplete draft doesn't
 * produce a tidy error; it leaves a half-built listing stranded on eBay, which is exactly how
 * offer 11447191010 was orphaned on the first real post.
 */
class ReviewGatingTest {

    private fun draft(
        itemKind: String = "general",
        title: String? = "A thing",
        chosenPrice: String? = "15.00",
        condition: String? = "good",
        categoryId: String? = "185101",
        brand: String? = "Lands End",
        color: String? = "White",
        size: String? = "M/L",
        sizeStandard: String? = "S",
        sizeType: String? = "regular",
        department: String? = "mens",
    ) = ItemDto(
        id = "draft-1",
        title = title,
        condition = condition,
        status = "draft",
        chosenPrice = chosenPrice,
        categoryId = categoryId,
        itemKind = itemKind,
        brand = brand,
        color = color,
        size = size,
        sizeStandard = sizeStandard,
        sizeType = sizeType,
        department = department,
        createdAt = "2026-08-16T14:00:00Z",
        photos = listOf(ItemPhotoDto(id = "p1", order = 0, cleaned = true)),
    )

    @Test
    fun `a complete garment is postable`() {
        assertTrue(readyToPost(draft(itemKind = "clothing")))
    }

    @Test
    fun `a complete general item is postable without the apparel specifics`() {
        assertTrue(
            readyToPost(
                draft(
                    itemKind = "general",
                    size = null,
                    sizeStandard = null,
                    sizeType = null,
                    department = null,
                )
            )
        )
    }

    @Test
    fun `an unlistable tag reading does not block a garment that has an eBay size`() {
        // "M/L" is a real tag reading eBay would block. Crate keeps it in the archive and
        // lists under the standardized value the human picked, so this must stay postable.
        assertTrue(readyToPost(draft(itemKind = "clothing", size = "M/L", sizeStandard = "M")))
    }

    @Test
    fun `every ebay-required clothing specific blocks the post when missing`() {
        // Named individually rather than looped so a failure says which field regressed.
        assertFalse("brand", readyToPost(draft(itemKind = "clothing", brand = null)))
        assertFalse("color", readyToPost(draft(itemKind = "clothing", color = null)))
        // The tag text is archive data; eBay is sent sizeStandard, so THAT is what gates.
        assertFalse("eBay size", readyToPost(draft(itemKind = "clothing", sizeStandard = null)))
        assertFalse("size type", readyToPost(draft(itemKind = "clothing", sizeType = null)))
        assertFalse("department", readyToPost(draft(itemKind = "clothing", department = null)))
    }

    @Test
    fun `category is required for everything, not just clothing`() {
        assertFalse(readyToPost(draft(itemKind = "general", categoryId = null)))
        assertFalse(readyToPost(draft(itemKind = "clothing", categoryId = null)))
    }

    @Test
    fun `the universal requirements still hold`() {
        assertFalse("title", readyToPost(draft(title = null)))
        assertFalse("blank title", readyToPost(draft(title = "   ")))
        assertFalse("price", readyToPost(draft(chosenPrice = null)))
        assertFalse("condition", readyToPost(draft(condition = null)))
    }

    @Test
    fun `a draft with no photos is not postable`() {
        val noPhotos = draft().copy(photos = emptyList())
        assertFalse(readyToPost(noPhotos))
    }

    @Test
    fun `blank strings count as missing, not as answers`() {
        // The edit dialog writes "" to clear a field server-side, so empty must not read as set.
        assertFalse(readyToPost(draft(itemKind = "clothing", sizeType = "")))
        assertFalse(readyToPost(draft(itemKind = "clothing", sizeStandard = "")))
        assertFalse(readyToPost(draft(categoryId = "")))
    }
}
