package com.crate.ui.review

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** The review stack: server drafts (status=draft), newest first. Drafts still processing
 * (processed_at == null) re-poll on a short interval until identification lands. */
@HiltViewModel
class ReviewViewModel @Inject constructor(
    private val api: ApiService,
) : ViewModel() {

    private val _drafts = MutableStateFlow<UiState<List<ItemDto>>>(UiState.Loading)
    val drafts: StateFlow<UiState<List<ItemDto>>> = _drafts

    private var polling = false

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _drafts.value = try {
                val items = api.listItems(status = "draft")
                maybePoll(items)
                UiState.Success(items)
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load drafts")
            }
        }
    }

    private fun maybePoll(items: List<ItemDto>) {
        if (polling || items.none { it.processedAt == null }) return
        polling = true
        viewModelScope.launch {
            try {
                // Re-poll while any draft is still processing (identification is seconds,
                // not minutes, against local LM Studio).
                repeat(30) {
                    delay(3_000)
                    val fresh = api.listItems(status = "draft")
                    _drafts.value = UiState.Success(fresh)
                    if (fresh.none { it.processedAt == null }) return@launch
                }
            } catch (_: Exception) {
                // Polling is best-effort; the user can pull-refresh.
            } finally {
                polling = false
            }
        }
    }

    fun saveEdits(id: String, update: ItemUpdateRequest, onDone: (Boolean) -> Unit) {
        viewModelScope.launch {
            try {
                val updated = api.updateItem(id, update)
                _drafts.value = (_drafts.value as? UiState.Success)?.let { state ->
                    UiState.Success(state.data.map { if (it.id == id) updated else it })
                } ?: _drafts.value
                onDone(true)
            } catch (e: Exception) {
                onDone(false)
            }
        }
    }

    fun dismiss(id: String) {
        viewModelScope.launch {
            try {
                api.deleteItem(id)
                _drafts.value = (_drafts.value as? UiState.Success)?.let { state ->
                    UiState.Success(state.data.filterNot { it.id == id })
                } ?: _drafts.value
            } catch (_: Exception) {
                refresh()
            }
        }
    }
}
