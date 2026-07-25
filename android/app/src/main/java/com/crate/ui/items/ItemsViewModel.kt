package com.crate.ui.items

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** The item registry: everything ever captured, filterable by lifecycle status. */
@HiltViewModel
class ItemsViewModel @Inject constructor(
    private val api: ApiService,
) : ViewModel() {

    private val _items = MutableStateFlow<UiState<List<ItemDto>>>(UiState.Loading)
    val items: StateFlow<UiState<List<ItemDto>>> = _items

    private val _filter = MutableStateFlow<String?>(null)
    val filter: StateFlow<String?> = _filter

    init {
        refresh()
    }

    fun setFilter(status: String?) {
        _filter.value = status
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _items.value = UiState.Loading
            _items.value = try {
                UiState.Success(api.listItems(status = _filter.value))
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load items")
            }
        }
    }

    companion object {
        /** Chip order mirrors the lifecycle. */
        val STATUSES = listOf("draft", "active", "sold", "shipped", "returned", "delisted")
    }
}
