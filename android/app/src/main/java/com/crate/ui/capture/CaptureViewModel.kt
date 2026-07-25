package com.crate.ui.capture

import android.app.Application
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.WorkManager
import com.crate.data.local.CaptureQueueEntity
import com.crate.data.repository.CaptureQueueRepository
import com.crate.work.UploadWorker
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import java.util.UUID
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

const val MAX_PHOTOS_PER_ITEM = 8

@HiltViewModel
class CaptureViewModel @Inject constructor(
    private val app: Application,
    private val repository: CaptureQueueRepository,
) : ViewModel() {

    /** Photos shot for the CURRENT item (not yet queued). */
    private val _shots = MutableStateFlow<List<File>>(emptyList())
    val shots: StateFlow<List<File>> = _shots

    val queue: StateFlow<List<CaptureQueueEntity>> = repository.queue
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private var pendingCameraTarget: File? = null

    /** A fresh camera output target in cache/captures/; returns its content Uri. */
    fun newCameraTarget(): Uri {
        val dir = File(app.cacheDir, "captures").apply { mkdirs() }
        val file = File(dir, "${UUID.randomUUID()}.jpg")
        pendingCameraTarget = file
        return FileProvider.getUriForFile(app, "com.crate.fileprovider", file)
    }

    fun onCameraResult(success: Boolean) {
        val file = pendingCameraTarget
        pendingCameraTarget = null
        if (success && file != null && file.exists() && _shots.value.size < MAX_PHOTOS_PER_ITEM) {
            _shots.value = _shots.value + file
        }
    }

    fun onGalleryPicked(uris: List<Uri>) {
        val room = MAX_PHOTOS_PER_ITEM - _shots.value.size
        if (room <= 0) return
        val dir = File(app.cacheDir, "captures").apply { mkdirs() }
        val copied = uris.take(room).mapNotNull { uri ->
            runCatching {
                val file = File(dir, "${UUID.randomUUID()}.jpg")
                app.contentResolver.openInputStream(uri)?.use { input ->
                    file.outputStream().use { input.copyTo(it) }
                } ?: return@runCatching null
                file
            }.getOrNull()
        }
        _shots.value = _shots.value + copied
    }

    fun removeShot(file: File) {
        _shots.value = _shots.value - file
        file.delete()
    }

    /** Current shots become ONE queued item; the queue uploads in the background. */
    fun queueItem() {
        val shots = _shots.value
        if (shots.isEmpty()) return
        _shots.value = emptyList()
        viewModelScope.launch {
            // Move out of cache into durable app storage before enqueueing.
            val id = UUID.randomUUID().toString()
            val dir = File(app.filesDir, "capture_queue/$id").apply { mkdirs() }
            val moved = shots.mapIndexed { index, src ->
                val dst = File(dir, "photo_$index.jpg")
                src.copyTo(dst, overwrite = true)
                src.delete()
                dst
            }
            repository.enqueue(moved)
            UploadWorker.kick(WorkManager.getInstance(app))
        }
    }

    fun retry(id: String) {
        viewModelScope.launch {
            repository.retry(id)
            UploadWorker.kick(WorkManager.getInstance(app))
        }
    }

    fun discard(id: String) {
        viewModelScope.launch { repository.discard(id) }
    }
}
