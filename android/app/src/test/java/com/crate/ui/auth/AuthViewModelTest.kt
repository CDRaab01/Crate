package com.crate.ui.auth

import android.content.Intent
import com.crate.data.local.TokenStore
import com.crate.data.remote.SuiteAuthManager
import com.crate.util.AuthEventBus
import com.crate.util.UiState
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.anyOrNull
import org.mockito.kotlin.doAnswer
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.stub

class AuthViewModelTest {

    private val dispatcher = StandardTestDispatcher()
    private val tokenStore: TokenStore = mock()
    private val eventBus = AuthEventBus()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `authorize intent delegates to the manager`() {
        val intent = Intent()
        val manager: SuiteAuthManager = mock {
            on { authorizeIntent() } doReturn intent
        }
        val vm = AuthViewModel(manager, tokenStore, eventBus)
        assertEquals(intent, vm.suiteAuthorizeIntent())
    }

    @Test
    fun `successful completion reaches Success`() = runTest(dispatcher.scheduler) {
        val manager: SuiteAuthManager = mock()
        val vm = AuthViewModel(manager, tokenStore, eventBus)
        vm.completeSuiteSignIn(Intent())
        dispatcher.scheduler.advanceUntilIdle()
        assertIs<UiState.Success<Unit>>(vm.signInState.value)
    }

    @Test
    fun `failure surfaces the error message and stays on Login`() = runTest(dispatcher.scheduler) {
        val manager: SuiteAuthManager = mock()
        manager.stub {
            onBlocking { complete(anyOrNull()) } doAnswer { throw IllegalStateException("Sign-in was canceled") }
        }
        val vm = AuthViewModel(manager, tokenStore, eventBus)
        vm.completeSuiteSignIn(null)
        dispatcher.scheduler.advanceUntilIdle()
        val state = vm.signInState.value
        assertIs<UiState.Error>(state)
        assertEquals("Sign-in was canceled", state.message)
    }
}
