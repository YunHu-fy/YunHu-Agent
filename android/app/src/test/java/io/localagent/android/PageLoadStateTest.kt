package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class PageLoadStateTest {
    @Test fun httpCommitAloneMustKeepLoadingOverlay() {
        val state = PageLoadState(); val attempt = state.begin(0)
        state.committed(attempt)
        assertEquals(PageLoadState.Phase.LOADING, state.phase)
        state.initialized(attempt)
        assertEquals(PageLoadState.Phase.READY, state.phase)
    }
    @Test fun javascriptReadyBeforeCommitDoesNotExposeBlankPage() {
        val state = PageLoadState(); val attempt = state.begin(0)
        state.initialized(attempt)
        assertEquals(PageLoadState.Phase.LOADING, state.phase)
        state.committed(attempt)
        assertEquals(PageLoadState.Phase.READY, state.phase)
    }
    @Test fun loadTimeoutHasActionableErrorAndLateCallbacksCannotHideIt() {
        val state = PageLoadState(); val attempt = state.begin(100)
        state.expire(30_099)
        assertEquals(PageLoadState.Phase.LOADING, state.phase)
        state.expire(30_100)
        assertEquals(PageLoadState.Phase.FAILED, state.phase)
        assertTrue(state.message.contains("重试"))
        state.committed(attempt); state.initialized(attempt)
        assertEquals(PageLoadState.Phase.FAILED, state.phase)
    }
    @Test fun previousNavigationCallbacksCannotCompleteRetriedPage() {
        val state = PageLoadState(); val old = state.begin(0)
        state.fail(old, "HTTP 500")
        val current = state.begin(1)
        state.committed(old); state.initialized(old); state.fail(old, "old error")
        assertEquals(PageLoadState.Phase.LOADING, state.phase)
        assertEquals("", state.message)
        state.initialized(current); state.committed(current)
        assertEquals(PageLoadState.Phase.READY, state.phase)
    }
    @Test fun resetInvalidatesCallbacksAndClearsReadyState() {
        val state = PageLoadState(); val attempt = state.begin(0)
        state.reset(); state.initialized(attempt); state.committed(attempt)
        assertEquals(PageLoadState.Phase.IDLE, state.phase)
    }
    @Test fun rendererExitAfterReadyShowsFailure() {
        val state = PageLoadState(); val attempt = state.begin(0)
        state.committed(attempt); state.initialized(attempt)
        state.fail(attempt, "WebView renderer exited")
        assertEquals(PageLoadState.Phase.FAILED, state.phase)
        assertTrue(state.message.contains("WebView"))
    }
}
