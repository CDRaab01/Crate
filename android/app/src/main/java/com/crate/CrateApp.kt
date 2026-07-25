package com.crate

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import androidx.work.WorkManager
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.crate.util.SuiteConfigReader
import com.crate.work.UploadWorker
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject
import okhttp3.OkHttpClient

@HiltAndroidApp
class CrateApp : Application(), Configuration.Provider, ImageLoaderFactory {

    @Inject lateinit var suiteConfigReader: SuiteConfigReader
    @Inject lateinit var workerFactory: HiltWorkerFactory
    @Inject lateinit var okHttpClient: OkHttpClient

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    /** Coil rides the app's OkHttp client so photo loads carry auth + the host rewrite. */
    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this).okHttpClient(okHttpClient).build()

    override fun onCreate() {
        super.onCreate()
        // Adopt the server URL the Dragonfly hub manages, if it's installed and same-signed.
        suiteConfigReader.sync()
        // Resume any capture uploads stranded by process death.
        UploadWorker.kick(WorkManager.getInstance(this))
    }
}
