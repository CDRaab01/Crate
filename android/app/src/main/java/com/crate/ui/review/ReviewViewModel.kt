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

    /** Pick a price strategy (quick/patient/custom) — just chosen_price via the normal PATCH. */
    fun choosePrice(id: String, price: String, onDone: (Boolean) -> Unit = {}) {
        saveEdits(id, ItemUpdateRequest(chosenPrice = price), onDone)
    }

    /** The approve tap: draft → live eBay listing. Success removes it from the stack;
     * failure surfaces the server's honest reason (not connected / policies missing / down). */
    fun post(id: String, onResult: (String?) -> Unit) {
        viewModelScope.launch {
            try {
                api.postItem(id)
                _drafts.value = (_drafts.value as? UiState.Success)?.let { state ->
                    UiState.Success(state.data.filterNot { it.id == id })
                } ?: _drafts.value
                onResult(null)
            } catch (e: retrofit2.HttpException) {
                onResult(e.response()?.errorBody()?.string()?.take(300) ?: "Posting failed")
            } catch (e: Exception) {
                onResult(e.message ?: "Posting failed")
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
