package com.crate.util

import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Reads suite connection config from the Dragonfly hub's `SuiteConfigProvider` and applies the
 * managed server URL to [AppPreferences]. This is an override, never a dependency: if Dragonfly
 * isn't installed, isn't same-signed (permission denied), or has no opinion (blank URL), we
 * leave the app's own configured URL untouched.
 */
@Singleton
class SuiteConfigReader @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Fire-and-forget: pull the broker's server URL for this app and apply it if it differs. */
    fun sync() {
        scope.launch {
            val brokerUrl = readBrokerServerUrl() ?: return@launch // no hub / denied / no opinion
            if (appPreferences.serverUrl.first() != brokerUrl) {
                appPreferences.setServerUrl(brokerUrl)
            }
        }
    }

    private fun readBrokerServerUrl(): String? = try {
        context.contentResolver.query(CONFIG_URI, null, null, null, null)?.use { cursor ->
            val keyCol = cursor.getColumnIndexOrThrow("key")
            val valCol = cursor.getColumnIndexOrThrow("value")
            var value: String? = null
            while (cursor.moveToNext()) {
                if (cursor.getString(keyCol) == KEY_SERVER_BASE_URL) value = cursor.getString(valCol)
            }
            value?.takeIf { it.isNotBlank() }
        }
    } catch (e: Exception) {
        // Provider absent (hub not installed), permission denied (different signing key), etc.
        null
    }

    private companion object {
        val CONFIG_URI: Uri = Uri.parse("content://com.dragonfly.suiteconfig/config/crate")
        const val KEY_SERVER_BASE_URL = "server_base_url"
    }
}
