package io.localagent.android

/** View-independent navigation. A restored page never restores a channel grant/check result. */
internal class SetupWizardState(
    var page: Page = Page.WELCOME,
    var consent: Boolean = false,
    selectedChannel: String = "normal"
) {
    enum class Page { WELCOME, PRIVACY, CHANNEL, CONFIRM, READY }
    var selectedChannel: String = FirstRunGate.selectedChannel(selectedChannel)
        private set
    var checkedChannel: String? = null
        private set
    var busy: Boolean = false
    val canEnter: Boolean get() = FirstRunGate.canComplete(consent, selectedChannel, checkedChannel == selectedChannel, checkedChannel != null)
    fun select(channel: String) {
        val validated = FirstRunGate.selectedChannel(channel)
        if (selectedChannel != validated) { selectedChannel = validated; checkedChannel = null }
    }
    fun consent(accepted: Boolean) { consent = accepted; if (!accepted) checkedChannel = null }
    fun checked(channel: String, configured: Boolean, environment: Boolean): Boolean {
        checkedChannel = if (channel == selectedChannel && FirstRunGate.canComplete(consent, channel, configured, environment)) channel else null
        return checkedChannel != null
    }
    fun next(): Boolean {
        if (busy) return false
        page = when (page) {
            Page.WELCOME -> Page.PRIVACY
            Page.PRIVACY -> if (consent) Page.CHANNEL else return false
            Page.CHANNEL -> Page.CONFIRM
            Page.CONFIRM -> if (canEnter) Page.READY else return false
            Page.READY -> return false
        }
        return true
    }
    fun back(): Boolean {
        if (busy || page == Page.WELCOME) return false
        page = Page.entries[page.ordinal - 1]
        return true
    }
    companion object {
        fun restore(page: String?, consent: Boolean, channel: String?): SetupWizardState {
            val parsed = Page.entries.firstOrNull { it.name == page } ?: Page.WELCOME
            return SetupWizardState(if (parsed == Page.READY) Page.CONFIRM else parsed, consent, FirstRunGate.selectedChannel(channel))
        }
    }
}
