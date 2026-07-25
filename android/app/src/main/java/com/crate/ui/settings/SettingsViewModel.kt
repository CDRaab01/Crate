package com.crate.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.EbayStatusDto
import com.crate.data.remote.UserSettingsDto
import com.crate.data.remote.UserSettingsUpdate
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

    private val _userSettings = MutableStateFlow<UserSettingsDto?>(null)
    val userSettings: StateFlow<UserSettingsDto?> = _userSettings

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
            _userSettings.value = try {
                api.getSettings()
            } catch (_: Exception) {
                null
            }
        }
    }

    /** The drop-policy knobs — what makes the unattended scheduler 'user-configured'. */
    fun saveDropPolicy(enabled: Boolean, intervalDays: Int, stepPercent: String, preference: String) {
        viewModelScope.launch {
            try {
                _userSettings.value = api.updateSettings(
                    UserSettingsUpdate(
                        dropsEnabled = enabled,
                        dropIntervalDays = intervalDays,
                        dropStepPercent = stepPercent,
                        shippingPreference = preference,
                    )
                )
            } catch (_: Exception) {
                refresh()
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
