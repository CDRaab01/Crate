package com.crate.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [CaptureQueueEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class CrateDatabase : RoomDatabase() {
    abstract fun captureQueueDao(): CaptureQueueDao
}
