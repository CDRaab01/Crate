package com.crate.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

interface ApiService {
    @POST("auth/suite")
    suspend fun suiteLogin(@Body req: SuiteLoginRequest): TokenResponse

    @POST("auth/refresh")
    suspend fun refresh(@Body req: RefreshRequest): TokenResponse

    @GET("users/me")
    suspend fun me(): UserDto
}
