package com.crate.ui.items

import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.util.UiState
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.doAnswer
import org.mockito.kotlin.eq
import org.mockito.kotlin.isNull
import org.mockito.kotlin.mock

class ItemsViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun item(id: String, status: String) =
        ItemDto(id = id, title = id, status = status, createdAt = "2026-07-25")

    @Test
    fun `loads unfiltered on init and refetches with the chip filter`() =
        runTest(dispatcher.scheduler) {
            val api: ApiService = mock {
                onBlocking { listItems(isNull()) } doAnswer {
                    listOf(item("a", "draft"), item("b", "sold"))
                }
                onBlocking { listItems(eq("sold")) } doAnswer { listOf(item("b", "sold")) }
            }
            val vm = ItemsViewModel(api)
            dispatcher.scheduler.advanceUntilIdle()
            assertEquals(2, (vm.items.value as UiState.Success).data.size)

            vm.setFilter("sold")
            dispatcher.scheduler.advanceUntilIdle()
            val filtered = vm.items.value
            assertIs<UiState.Success<List<ItemDto>>>(filtered)
            assertEquals(listOf("b"), filtered.data.map { it.id })
        }

    @Test
    fun `statuses chip order mirrors the lifecycle`() {
        assertEquals(
            listOf("draft", "active", "sold", "shipped", "returned", "delisted"),
            ItemsViewModel.STATUSES,
        )
    }
}
