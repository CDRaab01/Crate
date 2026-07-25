package com.crate

import android.app.Application
import com.crate.util.SuiteConfigReader
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class CrateApp : Application() {

    @Inject lateinit var suiteConfigReader: SuiteConfigReader

    override fun onCreate() {
        super.onCreate()
        // Adopt the server URL the Dragonfly hub manages, if it's installed and same-signed.
        suiteConfigReader.sync()
    }
}
