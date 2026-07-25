package com.crate.ui.inbox

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.MessageDto
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Buyer-message inbox: Crate flags, it doesn't chat — replies happen in the eBay app. */
@HiltViewModel
class InboxViewModel @Inject constructor(
    private val api: ApiService,
) : ViewModel() {

    private val _messages = MutableStateFlow<UiState<List<MessageDto>>>(UiState.Loading)
    val messages: StateFlow<UiState<List<MessageDto>>> = _messages

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _messages.value = try {
                UiState.Success(api.messages())
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load messages")
            }
        }
    }

    fun resolve(id: String) {
        viewModelScope.launch {
            try {
                val updated = api.resolveMessage(id)
                _messages.value = (_messages.value as? UiState.Success)?.let { state ->
                    UiState.Success(state.data.map { if (it.id == id) updated else it })
                } ?: _messages.value
            } catch (_: Exception) {
                refresh()
            }
        }
    }
}
