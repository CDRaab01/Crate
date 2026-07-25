package com.crate.ui.navigation

import androidx.lifecycle.ViewModel
import com.crate.data.local.TokenStore
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.runBlocking

@HiltViewModel
class GateViewModel @Inject constructor(
    private val tokenStore: TokenStore,
) : ViewModel() {
    /** Session check at launch. Blocking read of a single DataStore key — instant in practice. */
    fun isSignedIn(): Boolean = runBlocking { tokenStore.currentAccessToken() != null }
}
