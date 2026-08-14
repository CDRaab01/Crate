package com.crate.ui.items

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.data.remote.PriceEventDto
import com.crate.data.remote.SaleDto
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

@HiltViewModel
class ItemDetailViewModel @Inject constructor(
    private val api: ApiService,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val itemId: String = checkNotNull(savedStateHandle["itemId"])

    private val _item = MutableStateFlow<UiState<ItemDto>>(UiState.Loading)
    val item: StateFlow<UiState<ItemDto>> = _item

    private val _priceEvents = MutableStateFlow<List<PriceEventDto>>(emptyList())
    val priceEvents: StateFlow<List<PriceEventDto>> = _priceEvents

    private val _sale = MutableStateFlow<SaleDto?>(null)
    val sale: StateFlow<SaleDto?> = _sale

    init {
        refresh()
    }

    /** Registry-side edits — chiefly the tag/tape fields and storage location, which are
     * routinely filled in long after capture (the garment comes back out of a bin, or a
     * measurement gets corrected). Same PATCH the review stack uses. */
    fun saveEdits(update: ItemUpdateRequest, onDone: (Boolean) -> Unit = {}) {
        viewModelScope.launch {
            try {
                _item.value = UiState.Success(api.updateItem(itemId, update))
                onDone(true)
            } catch (e: Exception) {
                onDone(false)
            }
        }
    }

    /** Explicit listing writes (never automated): withdraw or republish the offer. */
    fun delist(onError: (String) -> Unit) {
        viewModelScope.launch {
            try {
                _item.value = UiState.Success(api.delistItem(itemId))
            } catch (e: Exception) {
                onError(e.message ?: "Delist failed")
            }
        }
    }

    fun relist(onError: (String) -> Unit) {
        viewModelScope.launch {
            try {
                _item.value = UiState.Success(api.relistItem(itemId))
            } catch (e: Exception) {
                onError(e.message ?: "Relist failed")
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val loaded = try {
                UiState.Success(api.getItem(itemId))
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load item")
            }
            _item.value = loaded
            _priceEvents.value = try {
                api.priceEvents(itemId)
            } catch (_: Exception) {
                emptyList() // history is additive UI — its failure never blanks the item
            }
            val status = (loaded as? UiState.Success)?.data?.status
            _sale.value = if (status in listOf("sold", "shipped")) {
                try {
                    api.itemSale(itemId)
                } catch (_: Exception) {
                    null
                }
            } else {
                null
            }
        }
    }
}
