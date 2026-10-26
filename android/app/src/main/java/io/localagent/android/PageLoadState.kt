package io.localagent.android

/** UI-thread navigation state. Late JS/visual callbacks cannot complete a new attempt. */
internal class PageLoadState {
    enum class Phase { IDLE, LOADING, READY, FAILED }
    var phase = Phase.IDLE; private set
    var generation = 0L; private set
    var message = ""; private set
    private var deadline = 0L
    private var committed = false
    private var initialized = false
    fun reset() { generation++; phase = Phase.IDLE; message = ""; committed = false; initialized = false }
    fun begin(now: Long): Long { reset(); phase = Phase.LOADING; deadline = now + 30_000; return generation }
    fun committed(attempt: Long) { if (active(attempt)) { committed = true; complete() } }
    fun initialized(attempt: Long) { if (active(attempt)) { initialized = true; complete() } }
    fun fail(attempt: Long, detail: String) { if (attempt == generation && phase != Phase.IDLE) { phase = Phase.FAILED; message = detail } }
    fun expire(now: Long) { if (phase == Phase.LOADING && now >= deadline) fail(generation, "会话页面加载超时，请重试页面。若反复失败，请检查 Android System WebView。") }
    private fun active(attempt: Long) = attempt == generation && phase == Phase.LOADING
    private fun complete() { if (committed && initialized) phase = Phase.READY }
}
