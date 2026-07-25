package com.crate.ui.review

import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.ItemUpdateRequest
import com.crate.util.UiState
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.doAnswer
import org.mockito.kotlin.eq
import org.mockito.kotlin.mock
import org.mockito.kotlin.stub

class ReviewViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun draft(id: String, title: String? = "Thing", processed: String? = "2026-07-25") =
        ItemDto(id = id, title = title, status = "draft", createdAt = "2026-07-25", processedAt = processed)

    @Test
    fun `loads drafts on init`() = runTest(dispatcher.scheduler) {
        val api: ApiService = mock {
            onBlocking { listItems(eq("draft")) } doAnswer { listOf(draft("a"), draft("b")) }
        }
        val vm = ReviewViewModel(api)
        dispatcher.scheduler.advanceUntilIdle()
        val state = vm.drafts.value
        assertIs<UiState.Success<List<ItemDto>>>(state)
        assertEquals(listOf("a", "b"), state.data.map { it.id })
    }

    @Test
    fun `load failure surfaces an error`() = runTest(dispatcher.scheduler) {
        val api: ApiService = mock {
            onBlocking { listItems(any()) } doAnswer { throw java.io.IOException("offline") }
        }
        val vm = ReviewViewModel(api)
        dispatcher.scheduler.advanceUntilIdle()
        assertIs<UiState.Error>(vm.drafts.value)
    }

    @Test
    fun `saveEdits swaps the updated draft in place`() = runTest(dispatcher.scheduler) {
        val api: ApiService = mock {
            onBlocking { listItems(eq("draft")) } doAnswer { listOf(draft("a"), draft("b")) }
            onBlocking { updateItem(eq("a"), any()) } doAnswer { draft("a", title = "Edited") }
        }
        val vm = ReviewViewModel(api)
        dispatcher.scheduler.advanceUntilIdle()

        var saved = false
        vm.saveEdits("a", ItemUpdateRequest(title = "Edited")) { saved = it }
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(saved)
        val state = vm.drafts.value
        assertIs<UiState.Success<List<ItemDto>>>(state)
        assertEquals("Edited", state.data.first { it.id == "a" }.title)
        assertEquals("Thing", state.data.first { it.id == "b" }.title)
    }

    @Test
    fun `dismiss removes the draft locally`() = runTest(dispatcher.scheduler) {
        val api: ApiService = mock {
            onBlocking { listItems(eq("draft")) } doAnswer { listOf(draft("a"), draft("b")) }
        }
        val vm = ReviewViewModel(api)
        dispatcher.scheduler.advanceUntilIdle()

        vm.dismiss("a")
        dispatcher.scheduler.advanceUntilIdle()

        val state = vm.drafts.value
        assertIs<UiState.Success<List<ItemDto>>>(state)
        assertEquals(listOf("b"), state.data.map { it.id })
    }
}
