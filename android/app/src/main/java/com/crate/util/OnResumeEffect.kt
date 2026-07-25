package com.crate.util

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * Runs [onResume] each time this destination returns to the foreground — tab revisits
 * included, because inside a NavHost the LocalLifecycleOwner is the back-stack entry.
 * The synthetic ON_RESUME delivered when the observer attaches is skipped so screens
 * whose ViewModels already load in init don't double-fetch on first composition.
 */
@Composable
fun OnResumeEffect(onResume: () -> Unit) {
    val owner = LocalLifecycleOwner.current
    val seenFirst = remember { booleanArrayOf(false) }
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                if (seenFirst[0]) onResume() else seenFirst[0] = true
            }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
}
