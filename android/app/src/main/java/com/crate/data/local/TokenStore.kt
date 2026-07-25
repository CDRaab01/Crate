package com.crate.data.local

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

// Deliberately separate from AppPreferences' "crate_prefs" store: auth state and app
// settings have different lifecycles (logout clears this store only).
private val Context.authDataStore by preferencesDataStore(name = "crate_auth")

@Singleton
class TokenStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val accessKey = stringPreferencesKey("access_token")
    private val refreshKey = stringPreferencesKey("refresh_token")

    val accessToken: Flow<String?> = context.authDataStore.data.map { it[accessKey] }
    val refreshToken: Flow<String?> = context.authDataStore.data.map { it[refreshKey] }

    suspend fun currentAccessToken(): String? = accessToken.first()
    suspend fun currentRefreshToken(): String? = refreshToken.first()

    suspend fun save(access: String, refresh: String) {
        context.authDataStore.edit {
            it[accessKey] = access
            it[refreshKey] = refresh
        }
    }

    suspend fun clear() {
        context.authDataStore.edit { it.clear() }
    }
}
