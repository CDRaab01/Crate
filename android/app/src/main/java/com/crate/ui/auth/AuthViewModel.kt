package com.crate.ui.auth

import android.content.Intent
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.local.TokenStore
import com.crate.data.remote.SuiteAuthManager
import com.crate.util.AuthEventBus
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val suiteAuthManager: SuiteAuthManager,
    private val tokenStore: TokenStore,
    authEventBus: AuthEventBus,
) : ViewModel() {

    private val _signInState = MutableStateFlow<UiState<Unit>>(UiState.Idle)
    val signInState: StateFlow<UiState<Unit>> = _signInState

    /** Forced sign-outs (refresh failure) surface here; the nav host bounces to Login. */
    val logoutEvents: SharedFlow<Unit> = authEventBus.logoutEvents

    fun suiteAuthorizeIntent(): Intent = suiteAuthManager.authorizeIntent()

    fun completeSuiteSignIn(data: Intent?) {
        _signInState.value = UiState.Loading
        viewModelScope.launch {
            try {
                suiteAuthManager.complete(data)
                _signInState.value = UiState.Success(Unit)
            } catch (e: Exception) {
                _signInState.value = UiState.Error(e.message ?: "Dragonfly sign-in failed")
            }
        }
    }

    fun signOut() {
        viewModelScope.launch { tokenStore.clear() }
    }
}
