package com.crate.data.remote

import com.crate.BuildConfig
import com.crate.data.local.TokenStore
import com.crate.util.AppPreferences
import com.crate.util.AuthEventBus
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.Authenticator
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.Route

/**
 * Refreshes the access token on a 401 and retries the request. Hardened per the suite's
 * Spotter audit: refreshes are serialized behind a lock and re-check the stored token first
 * (N concurrent 401s → one refresh); a transient IOException mid-refresh fails the request
 * WITHOUT signing out; only a 401/403 from /auth/refresh clears the session.
 */
@Singleton
class TokenRefreshAuthenticator @Inject constructor(
    private val tokenStore: TokenStore,
    private val appPreferences: AppPreferences,
    private val authEventBus: AuthEventBus,
) : Authenticator {

    private val refreshLock = Any()
    private val json = Json { ignoreUnknownKeys = true }
    // A bare client: routing refresh through the main client would recurse into this authenticator.
    private val refreshClient = OkHttpClient()

    override fun authenticate(route: Route?, response: Response): Request? {
        // A 401 from an auth endpoint is bad credentials, not an expired session.
        if (response.request.url.encodedPath.contains("/auth/")) return null
        // One retry only: a second 401 with a fresh token means the session is truly dead.
        if (responseCount(response) >= 2) {
            signOut()
            return null
        }

        val failedToken = response.request.header("Authorization")?.removePrefix("Bearer ")

        synchronized(refreshLock) {
            val stored = runBlocking { tokenStore.currentAccessToken() } ?: run {
                signOut()
                return null
            }
            // Another thread already refreshed while we waited on the lock.
            if (stored != failedToken) {
                return response.request.newBuilder()
                    .header("Authorization", "Bearer $stored")
                    .build()
            }

            val refreshToken = runBlocking { tokenStore.currentRefreshToken() } ?: run {
                signOut()
                return null
            }

            val base = runBlocking { appPreferences.serverUrl.firstOrNull() }
                ?.takeIf { it.isNotBlank() } ?: BuildConfig.SERVER_URL
            val url = base.trimEnd('/') + "/auth/refresh"
            val body = json.encodeToString(
                RefreshRequest.serializer(), RefreshRequest(refreshToken)
            ).toRequestBody("application/json".toMediaType())

            val refreshResponse = try {
                refreshClient.newCall(Request.Builder().url(url).post(body).build()).execute()
            } catch (e: IOException) {
                // Network blip mid-refresh: fail this request, keep the session.
                return null
            }

            refreshResponse.use { resp ->
                when {
                    resp.isSuccessful -> {
                        val parsed = resp.body?.string()?.let {
                            runCatching {
                                json.decodeFromString(TokenResponse.serializer(), it)
                            }.getOrNull()
                        } ?: return null
                        runBlocking { tokenStore.save(parsed.accessToken, parsed.refreshToken) }
                        return response.request.newBuilder()
                            .header("Authorization", "Bearer ${parsed.accessToken}")
                            .build()
                    }
                    resp.code == 401 || resp.code == 403 -> {
                        signOut()
                        return null
                    }
                    // 5xx etc: transient server trouble — don't wipe the session.
                    else -> return null
                }
            }
        }
    }

    private fun signOut() {
        runBlocking { tokenStore.clear() }
        authEventBus.emitLogout()
    }

    private fun responseCount(response: Response): Int {
        var count = 1
        var prior = response.priorResponse
        while (prior != null) {
            count++
            prior = prior.priorResponse
        }
        return count
    }
}
