package com.crate.util

import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/** One-shot auth events (forced sign-out on refresh failure) → the nav host. */
@Singleton
class AuthEventBus @Inject constructor() {
    private val _logoutEvents = MutableSharedFlow<Unit>(
        extraBufferCapacity = 1,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val logoutEvents: SharedFlow<Unit> = _logoutEvents

    fun emitLogout() {
        _logoutEvents.tryEmit(Unit)
    }
}
