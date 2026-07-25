package com.crate.ui.capture

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.crate.data.local.CaptureQueueEntity
import com.crate.ui.theme.CrateTheme
import design.pulse.ui.components.PanelCard
import design.pulse.ui.components.PulseButton
import design.pulse.ui.components.SectionHeader

/**
 * Batch capture: snap 1-8 photos of an item, queue it, keep shooting. Queued items upload
 * in the background (WorkManager) and appear in the review stack as drafts process.
 */
@Composable
fun CaptureScreen(
    viewModel: CaptureViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val shots by viewModel.shots.collectAsState()
    val queue by viewModel.queue.collectAsState()

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success -> viewModel.onCameraResult(success) }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris -> viewModel.onGalleryPicked(uris) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) cameraLauncher.launch(viewModel.newCameraTarget())
        else galleryLauncher.launch("image/*")
    }

    fun snap() {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) cameraLauncher.launch(viewModel.newCameraTarget())
        else permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(CrateTheme.spacing.lg),
        verticalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md),
    ) {
        SectionHeader(label = "This item", channel = CrateTheme.colors.copper.base)

        if (shots.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(shots) { file ->
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        AsyncImage(
                            model = file,
                            contentDescription = "captured photo",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier
                                .size(96.dp)
                                .clip(RoundedCornerShape(12.dp)),
                        )
                        IconButton(onClick = { viewModel.removeShot(file) }) {
                            Icon(Icons.Default.Close, contentDescription = "remove photo")
                        }
                    }
                }
            }
        } else {
            PanelCard {
                Text(
                    "Photograph the item — multiple angles help identification and buyers. " +
                        "Up to $MAX_PHOTOS_PER_ITEM shots per item.",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(CrateTheme.spacing.md)) {
            PulseButton(
                text = "Snap photo",
                onClick = { snap() },
                enabled = shots.size < MAX_PHOTOS_PER_ITEM,
                modifier = Modifier.weight(1f),
            )
            PulseButton(
                text = "Gallery",
                onClick = { galleryLauncher.launch("image/*") },
                tonal = true,
                enabled = shots.size < MAX_PHOTOS_PER_ITEM,
                modifier = Modifier.weight(1f),
            )
        }
        PulseButton(
            text = if (shots.isEmpty()) "Queue item" else "Queue item (${shots.size} photos)",
            onClick = { viewModel.queueItem() },
            enabled = shots.isNotEmpty(),
            modifier = Modifier.fillMaxWidth(),
        )

        Column {
            SectionHeader(
                label = "Queue",
                channel = CrateTheme.colors.attention.base,
                trailing = { Text("${queue.size} waiting") },
            )
            if (queue.isEmpty()) {
                Text(
                    "Nothing waiting — queued items upload in the background and land in Review.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        queue.forEach { entry ->
            QueueRow(
                entry = entry,
                onRetry = { viewModel.retry(entry.id) },
                onDiscard = { viewModel.discard(entry.id) },
            )
        }
    }
}

@Composable
private fun QueueRow(
    entry: CaptureQueueEntity,
    onRetry: () -> Unit,
    onDiscard: () -> Unit,
) {
    PanelCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AsyncImage(
                model = entry.paths.firstOrNull(),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(8.dp)),
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 12.dp),
            ) {
                Text(
                    "${entry.paths.size} photos",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    when (entry.state) {
                        CaptureQueueEntity.STATE_FAILED ->
                            "Upload rejected (${entry.lastError ?: "error"})"
                        CaptureQueueEntity.STATE_UPLOADING -> "Uploading…"
                        else -> "Waiting to upload"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (entry.state == CaptureQueueEntity.STATE_FAILED) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            if (entry.state == CaptureQueueEntity.STATE_FAILED) {
                PulseButton(text = "Retry", onClick = onRetry, compact = true)
                Spacer(Modifier.size(4.dp))
            }
            PulseButton(text = "Discard", onClick = onDiscard, compact = true, tonal = true)
        }
    }
}
