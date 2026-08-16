package com.crate.ui.review

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.CategoryAspectsDto
import com.crate.data.remote.CategorySuggestionDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.data.remote.VocabulariesDto
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

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing

    private var polling = false

    /** Server-owned dropdown vocabularies. Empty until loaded — the dialog degrades to
     * showing whatever the draft already holds rather than blocking on the network. */
    private val _vocabularies = MutableStateFlow(VocabulariesDto())
    val vocabularies: StateFlow<VocabulariesDto> = _vocabularies

    /** eBay category suggestions, per item id. Fetched when the dropdown is opened rather
     * than for every draft: each lookup is a live eBay call, and most drafts in a batch
     * capture are never expanded. */
    private val _categorySuggestions =
        MutableStateFlow<Map<String, List<CategorySuggestionDto>>>(emptyMap())
    val categorySuggestions: StateFlow<Map<String, List<CategorySuggestionDto>>> =
        _categorySuggestions

    private val inFlightCategories = mutableSetOf<String>()

    /** eBay's permitted aspect values per item — the Size dropdown. Keyed by item id and
     * fetched on menu-open, like the category suggestions. */
    private val _categoryAspects = MutableStateFlow<Map<String, CategoryAspectsDto>>(emptyMap())
    val categoryAspects: StateFlow<Map<String, CategoryAspectsDto>> = _categoryAspects

    private val inFlightAspects = mutableSetOf<String>()

    init {
        refresh()
        loadVocabularies()
    }

    private fun loadVocabularies() {
        viewModelScope.launch {
            try {
                _vocabularies.value = api.vocabularies()
            } catch (_: Exception) {
                // Static reference data; a failure just means the dropdowns stay empty and
                // the user can still see (and keep) the draft's existing values.
            }
        }
    }

    /** Load this item's category options once. Safe to call on every menu open. */
    fun loadCategorySuggestions(id: String) {
        if (id in inFlightCategories || _categorySuggestions.value.containsKey(id)) return
        inFlightCategories += id
        viewModelScope.launch {
            try {
                val found = api.categorySuggestions(id)
                _categorySuggestions.value = _categorySuggestions.value + (id to found)
            } catch (_: Exception) {
                // Leave the key absent so opening the menu again retries — a 502 from eBay
                // is usually transient, and caching the failure would strand the user.
            } finally {
                inFlightCategories -= id
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            _drafts.value = try {
                val items = api.listItems(status = "draft")
                maybePoll(items)
                UiState.Success(items)
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load drafts")
            }
            _refreshing.value = false
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

    /** Load eBay's permitted values for this item's category. Requires a category to be set
     * (the server 409s otherwise), so the Size dropdown fills in only after one is chosen. */
    fun loadCategoryAspects(id: String) {
        if (id in inFlightAspects || _categoryAspects.value.containsKey(id)) return
        inFlightAspects += id
        viewModelScope.launch {
            try {
                _categoryAspects.value = _categoryAspects.value + (id to api.categoryAspects(id))
            } catch (_: Exception) {
                // Absent key => opening the menu again retries. A 409 here just means no
                // category picked yet, which the dropdown's placeholder already explains.
            } finally {
                inFlightAspects -= id
            }
        }
    }

    /** Category changed => the permitted aspect values changed with it. */
    fun invalidateCategoryAspects(id: String) {
        _categoryAspects.value = _categoryAspects.value - id
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
