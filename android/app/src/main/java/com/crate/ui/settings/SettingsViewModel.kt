package com.crate.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.EbayStatusDto
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val api: ApiService,
) : ViewModel() {

    private val _ebayStatus = MutableStateFlow<UiState<EbayStatusDto>>(UiState.Loading)
    val ebayStatus: StateFlow<UiState<EbayStatusDto>> = _ebayStatus

    /** One-shot: the consent URL to open in a browser. */
    private val _connectUrl = MutableStateFlow<String?>(null)
    val connectUrl: StateFlow<String?> = _connectUrl

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _ebayStatus.value = try {
                UiState.Success(api.ebayStatus())
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't reach the server")
            }
        }
    }

    fun startConnect() {
        viewModelScope.launch {
            try {
                _connectUrl.value = api.ebayConnect().authorizeUrl
            } catch (e: Exception) {
                _ebayStatus.value =
                    UiState.Error("eBay connect unavailable — is the keyset configured?")
            }
        }
    }

    fun connectUrlConsumed() {
        _connectUrl.value = null
    }
}
