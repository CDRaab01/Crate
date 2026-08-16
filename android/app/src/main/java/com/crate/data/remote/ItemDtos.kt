package com.crate.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ItemPhotoDto(
    val id: String,
    val order: Int,
    val cleaned: Boolean,
    @SerialName("ebay_url") val ebayUrl: String? = null,
)

@Serializable
data class ItemDto(
    val id: String,
    val title: String? = null,
    val description: String? = null,
    val brand: String? = null,
    val model: String? = null,
    @SerialName("category_id") val categoryId: String? = null,
    val condition: String? = null,
    val status: String,
    @SerialName("quick_sale_price") val quickSalePrice: String? = null,
    @SerialName("patient_price") val patientPrice: String? = null,
    @SerialName("chosen_price") val chosenPrice: String? = null,
    val currency: String = "USD",
    @SerialName("ebay_listing_id") val ebayListingId: String? = null,
    @SerialName("weight_oz_est") val weightOzEst: String? = null,
    @SerialName("dims_in_est") val dimsInEst: Map<String, Double>? = null,
    @SerialName("weight_confirmed") val weightConfirmed: Boolean = false,
    @SerialName("template_id") val templateId: String? = null,
    @SerialName("date_listed") val dateListed: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("processed_at") val processedAt: String? = null,
    @SerialName("scan_error") val scanError: String? = null,
    // Apparel item specifics. The server owns the vocabularies and the completeness
    // computation (CLAUDE.md §9 - clients display, never compute); these two lists are
    // what the archive-first workflow surfaces, so a garment never reaches a storage bin
    // with its tag unread.
    @SerialName("item_kind") val itemKind: String = "general",
    val size: String? = null,
    @SerialName("size_standard") val sizeStandard: String? = null,
    @SerialName("size_type") val sizeType: String? = null,
    val department: String? = null,
    val color: String? = null,
    val material: String? = null,
    val style: String? = null,
    val fit: String? = null,
    @SerialName("sleeve_length") val sleeveLength: String? = null,
    @SerialName("measurements_in") val measurementsIn: Map<String, Double>? = null,
    @SerialName("storage_location") val storageLocation: String? = null,
    @SerialName("missing_for_listing") val missingForListing: List<String> = emptyList(),
    @SerialName("missing_hand_only") val missingHandOnly: List<String> = emptyList(),
    val photos: List<ItemPhotoDto> = emptyList(),
)

@Serializable
data class ScanAcceptedDto(
    val id: String,
    val status: String,
    @SerialName("photo_count") val photoCount: Int,
)

@Serializable
data class CompDto(
    val title: String,
    val price: String,
    val condition: String? = null,
    val url: String? = null,
)

@Serializable
data class CompsDto(
    val comps: List<CompDto> = emptyList(),
    @SerialName("quick_sale") val quickSale: String? = null,
    val patient: String? = null,
    @SerialName("comp_count") val compCount: Int = 0,
)

@Serializable
data class PriceEventDto(
    val id: String,
    @SerialName("old_price") val oldPrice: String,
    @SerialName("new_price") val newPrice: String,
    val reason: String,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class SaleDto(
    val id: String,
    @SerialName("item_id") val itemId: String,
    @SerialName("ebay_order_id") val ebayOrderId: String,
    @SerialName("sale_price") val salePrice: String,
    val fees: String? = null,
    @SerialName("sale_date") val saleDate: String,
    @SerialName("buyer_username") val buyerUsername: String,
    @SerialName("buyer_address") val buyerAddress: kotlinx.serialization.json.JsonObject? = null,
    @SerialName("ship_status") val shipStatus: String,
    @SerialName("tracking_number") val trackingNumber: String? = null,
    val carrier: String? = null,
    val service: String? = null,
    @SerialName("label_cost") val labelCost: String? = null,
    @SerialName("label_url") val labelUrl: String? = null,
)

@Serializable
data class MessageDto(
    val id: String,
    @SerialName("item_id") val itemId: String? = null,
    @SerialName("message_type") val messageType: String,
    val content: String,
    @SerialName("flagged_at") val flaggedAt: String,
    val resolved: Boolean,
)

@Serializable
data class RateDto(
    @SerialName("rate_id") val rateId: String,
    val provider: String,
    val service: String,
    val amount: String,
    val currency: String = "USD",
    @SerialName("estimated_days") val estimatedDays: Int? = null,
)

@Serializable
data class WeightConfirmRequest(
    @SerialName("weight_oz") val weightOz: String,
    @SerialName("dims_in") val dimsIn: Map<String, Double>,
)

@Serializable
data class BuyLabelRequest(
    @SerialName("rate_id") val rateId: String,
    val provider: String,
    val service: String,
    val amount: String,
)

@Serializable
data class UserSettingsDto(
    val id: String,
    @SerialName("drops_enabled") val dropsEnabled: Boolean,
    @SerialName("drop_interval_days") val dropIntervalDays: Int,
    @SerialName("drop_step_percent") val dropStepPercent: String,
    @SerialName("shipping_preference") val shippingPreference: String,
    @SerialName("ntfy_topic") val ntfyTopic: String? = null,
)

@Serializable
data class UserSettingsUpdate(
    @SerialName("drops_enabled") val dropsEnabled: Boolean? = null,
    @SerialName("drop_interval_days") val dropIntervalDays: Int? = null,
    @SerialName("drop_step_percent") val dropStepPercent: String? = null,
    @SerialName("shipping_preference") val shippingPreference: String? = null,
)

@Serializable
data class EbayConnectDto(
    @SerialName("authorize_url") val authorizeUrl: String,
)

@Serializable
data class EbayStatusDto(
    val configured: Boolean,
    val connected: Boolean,
    val environment: String? = null,
    @SerialName("access_expires_at") val accessExpiresAt: String? = null,
    @SerialName("refresh_expires_at") val refreshExpiresAt: String? = null,
)

@Serializable
data class ItemUpdateRequest(
    val title: String? = null,
    val description: String? = null,
    val brand: String? = null,
    val model: String? = null,
    @SerialName("category_id") val categoryId: String? = null,
    val condition: String? = null,
    @SerialName("chosen_price") val chosenPrice: String? = null,
    @SerialName("weight_oz_est") val weightOzEst: String? = null,
    @SerialName("dims_in_est") val dimsInEst: Map<String, Double>? = null,
    @SerialName("weight_confirmed") val weightConfirmed: Boolean? = null,
    // Apparel edits. Suite PATCH convention: null = untouched, "" = clear. Enum-valued
    // fields (itemKind/sizeType/department/fit/sleeveLength) are validated server-side and
    // 422 on an unknown value rather than degrading, so the UI offers fixed choices.
    @SerialName("item_kind") val itemKind: String? = null,
    val size: String? = null,
    @SerialName("size_standard") val sizeStandard: String? = null,
    @SerialName("size_type") val sizeType: String? = null,
    val department: String? = null,
    val color: String? = null,
    val material: String? = null,
    val style: String? = null,
    val fit: String? = null,
    @SerialName("sleeve_length") val sleeveLength: String? = null,
    @SerialName("measurements_in") val measurementsIn: Map<String, Double>? = null,
    @SerialName("storage_location") val storageLocation: String? = null,
)

/** One option in a server-owned controlled vocabulary.
 *
 * `value` is what the API validates ("big_tall"); `label` is what a human picks from a menu
 * ("Big & Tall"). Both come from the server so a new vocabulary entry cannot silently drift
 * out of sync with what the client offers. */
@Serializable
data class VocabularyEntryDto(val value: String, val label: String)

@Serializable
data class VocabulariesDto(
    val departments: List<VocabularyEntryDto> = emptyList(),
    @SerialName("size_types") val sizeTypes: List<VocabularyEntryDto> = emptyList(),
    @SerialName("sleeve_lengths") val sleeveLengths: List<VocabularyEntryDto> = emptyList(),
    val fits: List<VocabularyEntryDto> = emptyList(),
    val conditions: List<VocabularyEntryDto> = emptyList(),
)

/** An eBay category option. `path` is the breadcrumb — two categories can share a leaf name,
 * and the wrong one puts a listing in front of the wrong buyers. */
@Serializable
data class CategorySuggestionDto(
    @SerialName("category_id") val categoryId: String,
    val name: String,
    val path: String,
)

/** Permitted values for one eBay aspect, read live from eBay's taxonomy.
 *
 * `selectionOnly` matters over time: eBay is removing custom size values (full enforcement
 * Aug 2026), so an aspect that is free text today can be closed tomorrow. */
@Serializable
data class AspectOptionsDto(
    val name: String,
    val required: Boolean,
    @SerialName("selection_only") val selectionOnly: Boolean,
    val values: List<String> = emptyList(),
)

@Serializable
data class CategoryAspectsDto(
    val aspects: List<AspectOptionsDto> = emptyList(),
    /** The permitted Size the tag text unambiguously matches — a pre-selection, not a write. */
    @SerialName("suggested_size") val suggestedSize: String? = null,
)
