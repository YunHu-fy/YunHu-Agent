package io.localagent.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstRunGateTest {
    @Test fun missingMarkerNeedsFirstRunUnlessBothLegacySignalsExist() {
        assertFalse(FirstRunGate.startupDecision(null, consentGiven = false, serviceDesired = true).bypassSetup)
        assertFalse(FirstRunGate.startupDecision(null, consentGiven = true, serviceDesired = false).bypassSetup)
        assertTrue(FirstRunGate.startupDecision(null, consentGiven = true, serviceDesired = true).bypassSetup)
        assertTrue(FirstRunGate.startupDecision(null, consentGiven = true, serviceDesired = true).migrateLegacy)
    }

    @Test fun completedMarkerBypassesWithoutMigration() {
        val decision = FirstRunGate.startupDecision(true, consentGiven = false, serviceDesired = false)
        assertTrue(decision.bypassSetup)
        assertFalse(decision.migrateLegacy)
    }

    @Test fun incompleteMarkerCannotBeOverriddenByLegacySignals() {
        val decision = FirstRunGate.startupDecision(false, consentGiven = true, serviceDesired = true)
        assertFalse(decision.bypassSetup)
        assertFalse(decision.migrateLegacy)
    }

    @Test fun completionRequiresConsentChannelConfigurationAndDetection() {
        assertTrue(FirstRunGate.canComplete(true, FirstRunGate.NORMAL_CHANNEL, true, true))
        assertFalse(FirstRunGate.canComplete(false, FirstRunGate.NORMAL_CHANNEL, true, true))
        assertFalse(FirstRunGate.canComplete(true, "unknown", true, true))
        assertFalse(FirstRunGate.canComplete(true, FirstRunGate.ROOT_CHANNEL, false, true))
        assertFalse(FirstRunGate.canComplete(true, FirstRunGate.SHIZUKU_CHANNEL, true, false))
    }

    @Test fun savedChannelIsValidatedWithoutGrantReplay() {
        assertEquals(FirstRunGate.NORMAL_CHANNEL, FirstRunGate.selectedChannel(null))
        assertEquals(FirstRunGate.NORMAL_CHANNEL, FirstRunGate.selectedChannel("unknown"))
        assertEquals(FirstRunGate.ROOT_CHANNEL, FirstRunGate.selectedChannel(FirstRunGate.ROOT_CHANNEL))
        assertEquals(FirstRunGate.SHIZUKU_CHANNEL, FirstRunGate.selectedChannel(FirstRunGate.SHIZUKU_CHANNEL))
    }
}
