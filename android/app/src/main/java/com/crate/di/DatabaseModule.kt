package com.crate.di

import android.content.Context
import androidx.room.Room
import com.crate.data.local.CaptureQueueDao
import com.crate.data.local.CrateDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): CrateDatabase =
        Room.databaseBuilder(context, CrateDatabase::class.java, "crate.db")
            // The capture queue is small and local-only; on a schema mismatch a rebuild
            // loses at most not-yet-uploaded captures (photos still on disk).
            .fallbackToDestructiveMigration()
            .build()

    @Provides
    fun provideCaptureQueueDao(db: CrateDatabase): CaptureQueueDao = db.captureQueueDao()
}
