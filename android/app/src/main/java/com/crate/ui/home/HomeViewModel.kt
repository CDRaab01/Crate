package com.crate.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

data class HomeStats(
    val active: Int = 0,
    val sold: Int = 0,
    val drafts: Int = 0,
    val recent: List<ItemDto> = emptyList(),
    val unresolvedMessages: Int = 0,
    val loaded: Boolean = false,
)

/** Dashboard reads. Errors degrade to zeroed stats — Home is a glance, not a blocker. */
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val api: ApiService,
) : ViewModel() {

    private val _stats = MutableStateFlow(HomeStats())
    val stats: StateFlow<HomeStats> = _stats

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val items = try {
                api.listItems()
            } catch (_: Exception) {
                emptyList()
            }
            val unresolved = try {
                api.messages(unresolvedOnly = true).size
            } catch (_: Exception) {
                0
            }
            _stats.value = HomeStats(
                active = items.count { it.status == "active" },
                sold = items.count { it.status == "sold" || it.status == "shipped" },
                drafts = items.count { it.status == "draft" },
                recent = items.sortedByDescending { it.createdAt }.take(5),
                unresolvedMessages = unresolved,
                loaded = true,
            )
        }
    }
}
