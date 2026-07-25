package com.crate.data.repository

import com.crate.data.local.CaptureQueueDao
import com.crate.data.local.CaptureQueueEntity
import com.crate.data.remote.ApiService
import com.crate.util.ImageBytes
import java.io.File
import java.io.IOException
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

/**
 * The batch-capture queue: photos persist to app storage + a Room row per item, uploads
 * drain over WorkManager when connected. Retry policy mirrors the suite's sync rules:
 * IOException ⇒ retry later (still pending); HttpException ⇒ the server REJECTED it — mark
 * failed for the user, never poison-loop the drain.
 */
@Singleton
class CaptureQueueRepository @Inject constructor(
    private val dao: CaptureQueueDao,
    private val api: ApiService,
) {
    val queue: Flow<List<CaptureQueueEntity>> = dao.observeAll()
    val pendingCount: Flow<Int> = dao.observeCount()

    /** Persist a shot set as one queued item. Files are already in app storage. */
    suspend fun enqueue(photoFiles: List<File>): String {
        require(photoFiles.isNotEmpty()) { "at least one photo" }
        val id = UUID.randomUUID().toString()
        dao.upsert(
            CaptureQueueEntity(
                id = id,
                photoPaths = photoFiles.joinToString("\n") { it.absolutePath },
                state = CaptureQueueEntity.STATE_PENDING,
                createdAtMs = System.currentTimeMillis(),
            )
        )
        return id
    }

    suspend fun discard(id: String) {
        dao.byId(id)?.paths?.forEach { File(it).delete() }
        dao.byId(id)?.paths?.firstOrNull()?.let { File(it).parentFile?.delete() }
        dao.delete(id)
    }

    /**
     * Drain everything uploadable. Returns true when the queue is fully drained (nothing
     * pending), false when a transient failure means WorkManager should retry.
     */
    suspend fun drain(): Boolean {
        var allClear = true
        for (entry in dao.listUploadable()) {
            dao.setState(entry.id, CaptureQueueEntity.STATE_UPLOADING, entry.attempts, null)
            try {
                val parts = entry.paths.mapIndexed { index, path ->
                    val raw = File(path).readBytes()
                    val jpeg = ImageBytes.downscaleToJpeg(raw)
                    MultipartBody.Part.createFormData(
                        "photos",
                        "photo_$index.jpg",
                        jpeg.toRequestBody("image/jpeg".toMediaType()),
                    )
                }
                api.scanItem(parts)
                // Uploaded: the server owns it now — drop the row and the local files.
                entry.paths.forEach { File(it).delete() }
                File(entry.paths.first()).parentFile?.delete()
                dao.delete(entry.id)
            } catch (e: HttpException) {
                // Server rejected (4xx/5xx): surface it, don't block the rest of the drain.
                dao.setState(
                    entry.id,
                    CaptureQueueEntity.STATE_FAILED,
                    entry.attempts + 1,
                    "HTTP ${e.code()}",
                )
            } catch (e: IOException) {
                // Offline/transient: back to pending; WorkManager retries with backoff.
                dao.setState(
                    entry.id,
                    CaptureQueueEntity.STATE_PENDING,
                    entry.attempts + 1,
                    e.message,
                )
                allClear = false
            }
        }
        return allClear
    }

    /** A failed row can be retried once the user has seen/fixed the cause. */
    suspend fun retry(id: String) {
        dao.byId(id)?.let {
            dao.setState(it.id, CaptureQueueEntity.STATE_PENDING, it.attempts, null)
        }
    }
}
