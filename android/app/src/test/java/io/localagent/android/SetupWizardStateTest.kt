package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class SetupWizardStateTest {
    @Test fun firstEntryNeedsSeparateConsentAndSuccessfulCheckBeforeReady() {
        val flow = SetupWizardState()
        assertEquals(SetupWizardState.Page.WELCOME, flow.page)
        assertTrue(flow.next())
        assertEquals(SetupWizardState.Page.PRIVACY, flow.page)
        assertFalse(flow.next())
        flow.consent(true)
        assertTrue(flow.next())
        assertEquals(SetupWizardState.Page.CHANNEL, flow.page)
        assertTrue(flow.next())
        assertEquals(SetupWizardState.Page.CONFIRM, flow.page)
        assertFalse(flow.next())
        assertFalse(flow.checked("normal", configured = true, environment = false))
        assertFalse(flow.next())
        assertTrue(flow.checked("normal", configured = true, environment = true))
        assertTrue(flow.next())
        assertEquals(SetupWizardState.Page.READY, flow.page)
        assertTrue(flow.canEnter)
    }
    @Test fun changingChannelOrRevokingConsentInvalidatesPreviousCheck() {
        val flow = SetupWizardState(consent = true)
        assertTrue(flow.checked("normal", true, true))
        flow.select("root")
        assertFalse(flow.canEnter)
        assertFalse(flow.checked("normal", true, true))
        assertFalse(flow.checked("root", false, true))
        assertTrue(flow.checked("root", true, true))
        flow.consent(false)
        assertFalse(flow.canEnter)
        flow.consent(true)
        assertFalse(flow.canEnter)
    }
    @Test fun recreationNeverReusesReadyStateAsAnAuthorization() {
        val flow = SetupWizardState.restore("READY", true, "root")
        assertEquals(SetupWizardState.Page.CONFIRM, flow.page)
        assertEquals("root", flow.selectedChannel)
        assertFalse(flow.canEnter)
        assertFalse(flow.next())
        assertTrue(flow.back())
        assertEquals(SetupWizardState.Page.CHANNEL, flow.page)
        assertFalse(flow.canEnter)
    }
    @Test fun busyOperationBlocksNavigationAndInvalidRestoresAreSafe() {
        val flow = SetupWizardState.restore("unexpected", false, "bad")
        assertEquals(SetupWizardState.Page.WELCOME, flow.page)
        assertEquals("normal", flow.selectedChannel)
        flow.busy = true
        assertFalse(flow.next())
        assertFalse(flow.back())
        assertFalse(flow.canEnter)
    }
}
