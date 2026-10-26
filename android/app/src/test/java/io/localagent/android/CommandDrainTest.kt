package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class CommandDrainTest {
    @Test fun duplicateAndOutOfOrderChunksAreIgnored() {
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        val drained = CommandDrain.accept(
            2,
            listOf(Triple(1, "stdout", "old\n"), Triple(3, "stdout", "new\n"), Triple(3, "stderr", "dup\n"), Triple(4, "stderr", "warn\n")),
            stdout, stderr, 0, false,
        )
        assertEquals(4, drained.after)
        assertEquals("new\n", stdout.toString())
        assertEquals("warn\n", stderr.toString())
        assertFalse(drained.truncated)
    }

    @Test fun retainedBytesCountTowardTheCap() {
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        val chunk = "a".repeat(1000)
        val drained = CommandDrain.accept(0, listOf(Triple(1, "stdout", chunk)), stdout, stderr, CommandDrain.LIMIT_BYTES - 10, false)
        assertEquals("", stdout.toString())
        assertTrue(drained.truncated)
        assertEquals(CommandDrain.LIMIT_BYTES - 10, drained.retained)
    }

    @Test fun emptyChunksOnlyAdvanceTheCursor() {
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        val drained = CommandDrain.accept(0, listOf(Triple(7, "stdout", "")), stdout, stderr, 0, false)
        assertEquals(7, drained.after)
        assertEquals(0, drained.retained)
        assertEquals("", stdout.toString())
        assertFalse(drained.truncated)
    }
}
