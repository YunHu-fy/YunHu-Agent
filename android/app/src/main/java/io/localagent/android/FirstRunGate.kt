package io.localagent.android

/** Pure startup policy for native onboarding; it never performs authorization or detection. */
internal object FirstRunGate {
    const val PREFS_NAME = "native_onboarding"
    const val FIRST_RUN_COMPLETE = "first_run_complete"
    const val SELECTED_CHANNEL = "selected_channel"
    const val CONSENT_V1 = "consent_v1"

    const val NORMAL_CHANNEL = "normal"
    const val SHIZUKU_CHANNEL = "shizuku"
    const val ROOT_CHANNEL = "root"

    data class StartupDecision(
        val bypassSetup: Boolean,
        val migrateLegacy: Boolean
    )

    /**
     * A missing marker is migratable only when both old native signals agree.
     * A false marker is explicit incomplete onboarding and must show setup.
     */
    fun startupDecision(
        firstRunComplete: Boolean?,
        consentGiven: Boolean,
        serviceDesired: Boolean
    ): StartupDecision = when {
        firstRunComplete == true -> StartupDecision(bypassSetup = true, migrateLegacy = false)
        firstRunComplete == null && consentGiven && serviceDesired ->
            StartupDecision(bypassSetup = true, migrateLegacy = true)
        else -> StartupDecision(bypassSetup = false, migrateLegacy = false)
    }

    fun selectedChannel(value: String?): String = when (value) {
        SHIZUKU_CHANNEL -> SHIZUKU_CHANNEL
        ROOT_CHANNEL -> ROOT_CHANNEL
        else -> NORMAL_CHANNEL
    }

    /** Marker persistence is allowed only after all first-run requirements succeed. */
    fun canComplete(
        consentGiven: Boolean,
        channel: String,
        channelConfigured: Boolean,
        environmentDetected: Boolean
    ): Boolean = consentGiven &&
        channel in setOf(NORMAL_CHANNEL, SHIZUKU_CHANNEL, ROOT_CHANNEL) &&
        channelConfigured && environmentDetected
}
