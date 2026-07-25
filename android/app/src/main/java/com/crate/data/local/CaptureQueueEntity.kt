package com.crate.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One queued capture = one item (1-8 photo files) waiting to become a server draft.
 * Photos + state must survive process death (CLAUDE.md §2) — the files live under
 * filesDir/capture_queue/{id}/ and this row tracks them until the upload succeeds.
 */
@Entity(tableName = "capture_queue")
data class CaptureQueueEntity(
    @PrimaryKey val id: String,
    /** Newline-joined absolute paths, in shoot order. */
    val photoPaths: String,
    /** pending | uploading | failed (uploaded rows are deleted). */
    val state: String,
    val attempts: Int = 0,
    val lastError: String? = null,
    val createdAtMs: Long,
) {
    val paths: List<String> get() = photoPaths.split('\n').filter { it.isNotBlank() }

    companion object {
        const val STATE_PENDING = "pending"
        const val STATE_UPLOADING = "uploading"
        const val STATE_FAILED = "failed"
    }
}
