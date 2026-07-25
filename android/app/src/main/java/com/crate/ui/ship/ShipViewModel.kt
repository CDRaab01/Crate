package com.crate.ui.ship

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.crate.data.remote.ApiService
import com.crate.data.remote.BuyLabelRequest
import com.crate.data.remote.ItemDto
import com.crate.data.remote.RateDto
import com.crate.data.remote.SaleDto
import com.crate.data.remote.WeightConfirmRequest
import com.crate.util.UiState
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Sale → ship: confirm the AI's weight/dims guess, shop rates, one tap buys the label. */
@HiltViewModel
class ShipViewModel @Inject constructor(
    private val api: ApiService,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val itemId: String = checkNotNull(savedStateHandle["itemId"])

    private val _item = MutableStateFlow<UiState<ItemDto>>(UiState.Loading)
    val item: StateFlow<UiState<ItemDto>> = _item

    private val _rates = MutableStateFlow<UiState<List<RateDto>>>(UiState.Idle)
    val rates: StateFlow<UiState<List<RateDto>>> = _rates

    private val _label = MutableStateFlow<SaleDto?>(null)
    val label: StateFlow<SaleDto?> = _label

    private val _buyError = MutableStateFlow<String?>(null)
    val buyError: StateFlow<String?> = _buyError

    init {
        viewModelScope.launch {
            _item.value = try {
                val loaded = api.getItem(itemId)
                // Already-confirmed weight: go straight to rates.
                if (loaded.weightConfirmed) fetchRates()
                UiState.Success(loaded)
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't load item")
            }
        }
    }

    fun confirmWeight(weightOz: String, l: Double, w: Double, h: Double) {
        viewModelScope.launch {
            try {
                val updated = api.confirmWeight(
                    itemId,
                    WeightConfirmRequest(
                        weightOz = weightOz,
                        dimsIn = mapOf("l" to l, "w" to w, "h" to h),
                    ),
                )
                _item.value = UiState.Success(updated)
                fetchRates()
            } catch (e: Exception) {
                _buyError.value = e.message ?: "Couldn't confirm weight"
            }
        }
    }

    private fun fetchRates() {
        viewModelScope.launch {
            _rates.value = UiState.Loading
            _rates.value = try {
                UiState.Success(api.rates(itemId))
            } catch (e: Exception) {
                UiState.Error(e.message ?: "Couldn't fetch rates")
            }
        }
    }

    /** REAL MONEY: only ever called from the explicit Buy tap. */
    fun buyLabel(rate: RateDto) {
        viewModelScope.launch {
            _buyError.value = null
            try {
                _label.value = api.buyLabel(
                    itemId,
                    BuyLabelRequest(
                        rateId = rate.rateId,
                        provider = rate.provider,
                        service = rate.service,
                        amount = rate.amount,
                    ),
                )
            } catch (e: retrofit2.HttpException) {
                _buyError.value =
                    e.response()?.errorBody()?.string()?.take(300) ?: "Label purchase failed"
            } catch (e: Exception) {
                _buyError.value = e.message ?: "Label purchase failed"
            }
        }
    }
}
