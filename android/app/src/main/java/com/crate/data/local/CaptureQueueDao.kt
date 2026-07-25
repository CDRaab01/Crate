package com.crate.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface CaptureQueueDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: CaptureQueueEntity)

    @Query("SELECT * FROM capture_queue ORDER BY createdAtMs ASC")
    fun observeAll(): Flow<List<CaptureQueueEntity>>

    @Query("SELECT * FROM capture_queue WHERE state != :excludeState ORDER BY createdAtMs ASC")
    suspend fun listUploadable(excludeState: String = CaptureQueueEntity.STATE_UPLOADING): List<CaptureQueueEntity>

    @Query("SELECT * FROM capture_queue WHERE id = :id")
    suspend fun byId(id: String): CaptureQueueEntity?

    @Query("UPDATE capture_queue SET state = :state, attempts = :attempts, lastError = :lastError WHERE id = :id")
    suspend fun setState(id: String, state: String, attempts: Int, lastError: String?)

    @Query("DELETE FROM capture_queue WHERE id = :id")
    suspend fun delete(id: String)

    @Query("SELECT COUNT(*) FROM capture_queue")
    fun observeCount(): Flow<Int>
}
