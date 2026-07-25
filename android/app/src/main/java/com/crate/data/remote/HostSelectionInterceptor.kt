package com.crate.data.remote

import com.crate.util.AppPreferences
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Rewrites scheme/host/port of every request to the configured server URL, so the app can be
 * repointed (Settings or the Dragonfly config broker) without a rebuild. Runs FIRST in the
 * chain so the rewritten URL is what the auth header and logging see.
 */
@Singleton
class HostSelectionInterceptor @Inject constructor(
    private val appPreferences: AppPreferences,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val configured = runBlocking { appPreferences.serverUrl.firstOrNull() }
        val base = configured?.takeIf { it.isNotBlank() }?.toHttpUrlOrNull()
            ?: return chain.proceed(chain.request())

        val old = chain.request().url
        if (old.scheme == base.scheme && old.host == base.host && old.port == base.port) {
            return chain.proceed(chain.request())
        }
        val rewritten = old.newBuilder()
            .scheme(base.scheme)
            .host(base.host)
            .port(base.port)
            .build()
        return chain.proceed(chain.request().newBuilder().url(rewritten).build())
    }
}
