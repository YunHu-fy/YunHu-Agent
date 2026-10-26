package io.localagent.android

/** Two left-to-right typing passes, each held briefly, separated by a quiet blank. */
internal object WelcomeGreeting {
    const val CHARACTER_MS = 260L
    const val HOLD_MS = 1500L
    const val GAP_MS = 450L
    private val words = arrayOf("你好", "hello")
    val CYCLE_MS = words.sumOf { it.length * CHARACTER_MS + HOLD_MS + GAP_MS }
    fun frame(elapsedMs: Long): String {
        var time = elapsedMs.coerceAtLeast(0L) % CYCLE_MS
        for (word in words) {
            val typed = word.length * CHARACTER_MS
            if (time < typed) return word.take((time / CHARACTER_MS).toInt() + 1)
            if (time < typed + HOLD_MS) return word
            if (time < typed + HOLD_MS + GAP_MS) return ""
            time -= typed + HOLD_MS + GAP_MS
        }
        return ""
    }
}
