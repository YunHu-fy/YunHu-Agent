package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class StreamCursorTest {
    @Test fun exitedProcessWithMoreThan16EventsIsNotDoneUntilDrained() {
        val events = (1..65).toList()
        var after = 0
        var pages = 0
        val received = mutableListOf<Int>()
        do {
            val page = events.filter { it > after }.take(16)
            received.addAll(page)
            after = page.lastOrNull() ?: after
            pages++
            if (pages < 5) { assertTrue(StreamCursor.more(after, events.last())); assertFalse(StreamCursor.done(true, after, events.last())) }
        } while (!StreamCursor.done(true, after, events.last()))
        assertEquals(events, received)
        assertEquals(5, pages)
    }
    @Test fun noOutputRequiresProcessExit() {
        assertFalse(StreamCursor.done(false, 0, 0))
        assertTrue(StreamCursor.done(true, 0, 0))
    }
    @Test fun newEventsAfterEarlierPageRequireAnotherPoll() {
        assertFalse(StreamCursor.done(true, 16, 17))
        assertTrue(StreamCursor.done(true, 17, 17))
    }
}
