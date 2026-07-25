package com.crate.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class SuiteLoginRequest(
    @SerialName("suite_token") val suiteToken: String,
)

@Serializable
data class RefreshRequest(
    @SerialName("refresh_token") val refreshToken: String,
)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
)

@Serializable
data class UserDto(
    val id: String,
    val name: String,
    val email: String,
    @SerialName("created_at") val createdAt: String,
)
