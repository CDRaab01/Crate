package com.crate.ui.items

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.PriceEventDto
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

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _item.value = try {
                UiState.Success(api.getItem(itemId))
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load item")
            }
            _priceEvents.value = try {
                api.priceEvents(itemId)
            } catch (_: Exception) {
                emptyList() // history is additive UI — its failure never blanks the item
            }
        }
    }
}
