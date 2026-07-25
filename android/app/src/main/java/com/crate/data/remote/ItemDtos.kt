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
)
