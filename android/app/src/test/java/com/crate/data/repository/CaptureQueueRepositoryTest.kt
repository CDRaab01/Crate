package com.crate.data.repository

import com.crate.data.local.CaptureQueueDao
import com.crate.data.local.CaptureQueueEntity
import com.crate.data.remote.ApiService
import com.crate.data.remote.ScanAcceptedDto
import java.io.File
import java.io.IOException
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.assertFalse
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.test.runTest
import okhttp3.MultipartBody
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.mockito.kotlin.any
import org.mockito.kotlin.doAnswer
import org.mockito.kotlin.mock
import org.mockito.kotlin.stub
import retrofit2.HttpException
import retrofit2.Response

/** Drain semantics are the suite's sync rules: IOException ⇒ still pending (retry later);
 * HttpException ⇒ rejected (failed, drain continues — no poison rows). */
class CaptureQueueRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var dao: FakeDao
    private lateinit var api: ApiService

    @Before
    fun setUp() {
        dao = FakeDao()
        api = mock()
    }

    private fun repo() = CaptureQueueRepository(dao, api)

    private var fileCounter = 0

    private fun photoFiles(n: Int = 2): List<File> = (0 until n).map {
        tmp.newFile("photo_${fileCounter++}.jpg").apply {
            writeBytes(ByteArray(64) { b -> b.toByte() })
        }
    }

    @Test
    fun `successful drain uploads, deletes row and files`() = runTest {
        api.stub {
            onBlocking { scanItem(any()) } doAnswer { ScanAcceptedDto("id-1", "draft", 2) }
        }
        val repository = repo()
        val files = photoFiles()
        repository.enqueue(files)

        assertTrue(repository.drain())
        assertEquals(0, dao.rows.value.size)
        assertTrue(files.none { it.exists() })
    }

    @Test
    fun `IOException keeps the row pending and reports not-drained`() = runTest {
        api.stub {
            onBlocking { scanItem(any()) } doAnswer { throw IOException("offline") }
        }
        val repository = repo()
        repository.enqueue(photoFiles())

        assertFalse(repository.drain())
        val row = dao.rows.value.single()
        assertEquals(CaptureQueueEntity.STATE_PENDING, row.state)
        assertEquals(1, row.attempts)
    }

    @Test
    fun `HttpException marks failed but the drain continues and reports clear`() = runTest {
        var calls = 0
        api.stub {
            onBlocking { scanItem(any<List<MultipartBody.Part>>()) } doAnswer {
                calls++
                if (calls == 1) throw HttpException(
                    Response.error<Any>(
                        "rejected".toResponseBody(),
                        okhttp3.Response.Builder()
                            .request(Request.Builder().url("http://test/items/scan").build())
                            .protocol(Protocol.HTTP_1_1)
                            .code(422)
                            .message("Unprocessable")
                            .build(),
                    )
                )
                ScanAcceptedDto("id-2", "draft", 2)
            }
        }
        val repository = repo()
        repository.enqueue(photoFiles())
        repository.enqueue(photoFiles())

        // The rejected row must not abort the second upload (the Cookbook poison-row lesson).
        assertTrue(repository.drain())
        val remaining = dao.rows.value
        assertEquals(1, remaining.size)
        assertEquals(CaptureQueueEntity.STATE_FAILED, remaining.single().state)
        assertEquals("HTTP 422", remaining.single().lastError)
    }

    @Test
    fun `retry resets a failed row to pending`() = runTest {
        api.stub {
            onBlocking { scanItem(any()) } doAnswer { throw IOException("x") }
        }
        val repository = repo()
        val id = repository.enqueue(photoFiles())
        dao.setState(id, CaptureQueueEntity.STATE_FAILED, 1, "HTTP 500")

        repository.retry(id)
        assertEquals(CaptureQueueEntity.STATE_PENDING, dao.rows.value.single().state)
    }

    private class FakeDao : CaptureQueueDao {
        val rows = MutableStateFlow<List<CaptureQueueEntity>>(emptyList())

        override suspend fun upsert(entity: CaptureQueueEntity) {
            rows.value = rows.value.filterNot { it.id == entity.id } + entity
        }

        override fun observeAll(): Flow<List<CaptureQueueEntity>> = rows

        override suspend fun listUploadable(excludeState: String): List<CaptureQueueEntity> =
            rows.value.filter { it.state != excludeState }

        override suspend fun byId(id: String): CaptureQueueEntity? =
            rows.value.firstOrNull { it.id == id }

        override suspend fun setState(id: String, state: String, attempts: Int, lastError: String?) {
            rows.value = rows.value.map {
                if (it.id == id) it.copy(state = state, attempts = attempts, lastError = lastError)
                else it
            }
        }

        override suspend fun delete(id: String) {
            rows.value = rows.value.filterNot { it.id == id }
        }

        override fun observeCount(): Flow<Int> = rows.map { it.size }
    }
}
