package io.localagent.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WelcomeGreetingTest {
    @Test fun typesChineseGreetingFromLeftToRight() {
        assertEquals("你", WelcomeGreeting.frame(0))
        assertEquals("你", WelcomeGreeting.frame(WelcomeGreeting.CHARACTER_MS - 1))
        assertEquals("你好", WelcomeGreeting.frame(WelcomeGreeting.CHARACTER_MS))
    }

    @Test fun typesEnglishGreetingFromLeftToRightAfterChinesePass() {
        val englishStart = 2 * WelcomeGreeting.CHARACTER_MS + WelcomeGreeting.HOLD_MS + WelcomeGreeting.GAP_MS
        assertEquals("h", WelcomeGreeting.frame(englishStart))
        assertEquals("he", WelcomeGreeting.frame(englishStart + WelcomeGreeting.CHARACTER_MS))
        assertEquals("hello", WelcomeGreeting.frame(englishStart + 4 * WelcomeGreeting.CHARACTER_MS))
    }

    @Test fun holdsAndThenClearsEachGreeting() {
        val chineseHold = 2 * WelcomeGreeting.CHARACTER_MS + WelcomeGreeting.HOLD_MS - 1
        val chineseGap = 2 * WelcomeGreeting.CHARACTER_MS + WelcomeGreeting.HOLD_MS
        assertEquals("你好", WelcomeGreeting.frame(chineseHold))
        assertEquals("", WelcomeGreeting.frame(chineseGap))
    }

    @Test fun cycleRepeatsWithoutGrowingState() {
        assertTrue(WelcomeGreeting.CYCLE_MS > 0)
        assertEquals(WelcomeGreeting.frame(1234), WelcomeGreeting.frame(1234 + WelcomeGreeting.CYCLE_MS))
    }
}
