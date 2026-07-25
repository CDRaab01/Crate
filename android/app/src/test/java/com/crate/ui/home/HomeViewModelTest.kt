package com.crate.ui.home

import com.crate.data.remote.ApiService
import com.crate.data.remote.ItemDto
import com.crate.data.remote.MessageDto
import kotlin.test.assertEquals
import kotlin.test.assertTrue
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

class HomeViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun item(id: String, status: String, createdAt: String = "2026-07-25") =
        ItemDto(id = id, title = id, status = status, createdAt = createdAt)

    private fun message(id: String) = MessageDto(
        id = id,
        messageType = "question",
        content = "?",
        flaggedAt = "2026-07-25",
        resolved = false,
    )

    @Test
    fun `counts by status, sold includes shipped, recent is newest-first capped at five`() =
        runTest(dispatcher.scheduler) {
            val api: ApiService = mock {
                onBlocking { listItems(isNull()) } doAnswer {
                    listOf(
                        item("a", "active", "2026-07-20"),
                        item("b", "active", "2026-07-21"),
                        item("c", "sold", "2026-07-22"),
                        item("d", "shipped", "2026-07-19"),
                        item("e", "draft", "2026-07-23"),
                        item("f", "draft", "2026-07-24"),
                        item("g", "delisted", "2026-07-18"),
                    )
                }
                onBlocking { messages(eq(true)) } doAnswer { listOf(message("m1"), message("m2")) }
            }
            val vm = HomeViewModel(api)
            dispatcher.scheduler.advanceUntilIdle()

            val stats = vm.stats.value
            assertTrue(stats.loaded)
            assertEquals(2, stats.active)
            assertEquals(2, stats.sold)
            assertEquals(2, stats.drafts)
            assertEquals(2, stats.unresolvedMessages)
            assertEquals(listOf("f", "e", "c", "b", "a"), stats.recent.map { it.id })
        }

    @Test
    fun `errors degrade to zeroed stats, not a broken dashboard`() =
        runTest(dispatcher.scheduler) {
            val api: ApiService = mock {
                onBlocking { listItems(isNull()) } doAnswer { error("boom") }
                onBlocking { messages(eq(true)) } doAnswer { error("boom") }
            }
            val vm = HomeViewModel(api)
            dispatcher.scheduler.advanceUntilIdle()

            val stats = vm.stats.value
            assertTrue(stats.loaded)
            assertEquals(0, stats.active)
            assertEquals(0, stats.sold)
            assertEquals(0, stats.drafts)
            assertEquals(0, stats.unresolvedMessages)
            assertTrue(stats.recent.isEmpty())
        }
}
