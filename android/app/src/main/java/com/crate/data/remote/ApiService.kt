package com.crate.data.remote

import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {
    @POST("auth/suite")
    suspend fun suiteLogin(@Body req: SuiteLoginRequest): TokenResponse

    @POST("auth/refresh")
    suspend fun refresh(@Body req: RefreshRequest): TokenResponse

    @GET("users/me")
    suspend fun me(): UserDto

    @Multipart
    @POST("items/scan")
    suspend fun scanItem(@Part photos: List<MultipartBody.Part>): ScanAcceptedDto

    @GET("items")
    suspend fun listItems(@Query("status_filter") status: String? = null): List<ItemDto>

    @GET("items/{id}")
    suspend fun getItem(@Path("id") id: String): ItemDto

    @PATCH("items/{id}")
    suspend fun updateItem(@Path("id") id: String, @Body req: ItemUpdateRequest): ItemDto

    @DELETE("items/{id}")
    suspend fun deleteItem(@Path("id") id: String)
}
