package io.localagent.android

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Bundle
import android.system.Os
import android.system.OsConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.termux.terminal.TerminalSession
import com.termux.terminal.TerminalSessionClient
import com.termux.view.TerminalView
import com.termux.view.TerminalViewClient

/** Real libtermux PTY, emulator, selection and keyboard. No external package or Activity. */
class TerminalActivity : Activity() {
    private lateinit var terminal: TerminalView
    private lateinit var heading: TextView
    private var fontSize = 36
    private fun tr(zh: String, en: String) = UiPreferences.read(this).text(zh, en)
    private val client = object : TerminalViewClient, TerminalSessionClient {
        override fun onTextChanged(session: TerminalSession) { terminal.onScreenUpdated() }
        override fun onTitleChanged(session: TerminalSession) { heading.text = tr("内置 Termux · ", "Bundled Termux · ") + (session.title ?: "bash") }
        override fun onSessionFinished(session: TerminalSession) { heading.text = tr("终端已退出 · ", "Terminal exited · ") + session.exitStatus; terminal.onScreenUpdated() }
        override fun onCopyTextToClipboard(session: TerminalSession, text: String) { getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Terminal", text)) }
        override fun onPasteTextFromClipboard(session: TerminalSession) { getSystemService(ClipboardManager::class.java).primaryClip?.let { if (it.itemCount > 0) session.emulator?.paste(it.getItemAt(0).coerceToText(this@TerminalActivity).toString()) } }
        override fun onBell(session: TerminalSession) { terminal.performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP) }
        override fun onColorsChanged(session: TerminalSession) { terminal.invalidate() }
        override fun onTerminalCursorStateChange(state: Boolean) { terminal.invalidate() }
        override fun getTerminalCursorStyle(): Int = 0
        override fun onScale(scale: Float): Float { if (scale < 0.9f || scale > 1.1f) { fontSize = (fontSize * scale).toInt().coerceIn(18, 72); terminal.setTextSize(fontSize); return 1f }; return scale }
        override fun onSingleTapUp(event: MotionEvent) { keyboard() }
        override fun shouldBackButtonBeMappedToEscape() = false
        override fun shouldEnforceCharBasedInput() = false
        override fun shouldUseCtrlSpaceWorkaround() = true
        override fun isTerminalViewSelected() = true
        override fun copyModeChanged(copyMode: Boolean) { }
        override fun onKeyDown(keyCode: Int, event: KeyEvent, session: TerminalSession): Boolean { if (!session.isRunning && keyCode == KeyEvent.KEYCODE_ENTER) { finish(); return true }; return false }
        override fun onKeyUp(keyCode: Int, event: KeyEvent) = false
        override fun onLongPress(event: MotionEvent) = false
        override fun readControlKey() = false
        override fun readAltKey() = false
        override fun readShiftKey() = false
        override fun readFnKey() = false
        override fun onCodePoint(codePoint: Int, ctrlDown: Boolean, session: TerminalSession) = false
        override fun onEmulatorSet() { }
        // Terminal output is intentionally not copied into Logcat or diagnostics.
        override fun logError(tag: String, message: String) { }
        override fun logWarn(tag: String, message: String) { }
        override fun logInfo(tag: String, message: String) { }
        override fun logDebug(tag: String, message: String) { }
        override fun logVerbose(tag: String, message: String) { }
        override fun logStackTraceWithMessage(tag: String, message: String, e: Exception) { }
        override fun logStackTrace(tag: String, e: Exception) { }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        UiPreferences.applyWindow(this)
        super.onCreate(savedInstanceState)
        val ui = UiPreferences.read(this)
        val colors = UiPreferences.palette(this, ui)
        fontSize = (36 * ui.scale).toInt().coerceIn(18, 72)
        DeviceBridge.initialize(this)
        if (!TermuxRuntime.installed()) { AlertDialog.Builder(this).setMessage(tr("请先在设置中一键部署内置环境。", "Install the bundled environment in Settings first.")).setPositiveButton(tr("返回", "Back")) { _, _ -> finish() }.show(); return }
        heading = TextView(this).apply { text = tr("内置 Termux 0.118.3 · PTY", "Bundled Termux 0.118.3 · PTY"); textSize = 16f * ui.scale; setPadding(16, 12, 16, 8) }
        terminal = TerminalView(this, null).apply { setTerminalViewClient(client); setTextSize(fontSize); isFocusableInTouchMode = true }
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(colors.background) }
        heading.setTextColor(colors.foreground); root.addView(heading)
        val keys = LinearLayout(this)
        fun key(label: String, action: () -> Unit) { keys.addView(Button(this).apply { text = label; textSize = 12f * ui.scale; setTextColor(colors.foreground); setPadding(0, 0, 0, 0); setOnClickListener { action() } }, LinearLayout.LayoutParams(0, -2, 1f)) }
        key("ESC") { TerminalSessions.session?.write("\u001b") }; key("TAB") { TerminalSessions.session?.write("\t") }
        key("CTRL-C") { TerminalSessions.session?.write("\u0003") }; key("↑") { terminal.handleKeyCode(KeyEvent.KEYCODE_DPAD_UP, 0) }
        key("↓") { terminal.handleKeyCode(KeyEvent.KEYCODE_DPAD_DOWN, 0) }; key(tr("键盘", "Keys")) { keyboard() }; key(tr("关闭", "Close")) { closeSession() }
        root.addView(keys); root.addView(terminal, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(root)
        try {
            val epoch = DeviceBridge.terminalEpoch()
            if (TerminalSessions.epoch != epoch) TerminalSessions.stop()
            val session = TerminalSessions.session ?: run {
                val (shell, args) = DeviceBridge.terminalShell()
                TerminalSession(shell, RuntimeEnvironment.HOME, args, RuntimeEnvironment.environment("termux").map { it.key + "=" + it.value }.toTypedArray(), 2000, client)
                    .also { TerminalSessions.session = it; TerminalSessions.epoch = epoch }
            }
            session.updateTerminalSessionClient(client); terminal.attachSession(session)
            if (DeviceBridge.terminalEpoch() != epoch) { TerminalSessions.stop(); error("Permission channel changed; reopen the terminal") }
            terminal.requestFocus()
        } catch (failure: Exception) { TerminalSessions.stop(); AlertDialog.Builder(this).setMessage(failure.message).setPositiveButton(tr("返回", "Back")) { _, _ -> finish() }.show() }
    }
    private fun keyboard() { terminal.requestFocus(); getSystemService(InputMethodManager::class.java).showSoftInput(terminal, InputMethodManager.SHOW_IMPLICIT) }
    private fun closeSession() { AlertDialog.Builder(this).setTitle(tr("关闭终端会话？", "Close this terminal session?")).setMessage(tr("将尝试终止此 PTY 进程组，不影响其他命令任务。", "Attempts to stop this PTY process group. Other command tasks are unaffected.")).setNegativeButton(tr("取消", "Cancel"), null).setPositiveButton(tr("关闭", "Close")) { _, _ -> TerminalSessions.stop(); finish() }.show() }
    override fun onStart() { super.onStart(); DeviceBridge.attach(this) }
    override fun onStop() { DeviceBridge.detach(this); super.onStop() }
    override fun onDestroy() { TerminalSessions.session?.updateTerminalSessionClient(TerminalSessions.idleClient); super.onDestroy() }
}

internal object TerminalSessions {
    @Volatile var session: TerminalSession? = null
    @Volatile var epoch = -1L
    private var rootLease: Pair<String, java.io.File>? = null
    internal fun prepareRoot(context: android.content.Context, su: String): java.io.File {
        check(android.os.Looper.myLooper() == android.os.Looper.getMainLooper())
        val handoff = java.io.File.createTempFile(".agent-pty-", ".identity", context.filesDir)
        Os.chmod(handoff.absolutePath, 0x180) // 0600: Root writes into an app-owned file.
        rootLease = su to handoff
        return handoff
    }
    // Detach UI references while the foreground service keeps the PTY alive.
    val idleClient = object : TerminalSessionClient {
        override fun onTextChanged(s: TerminalSession) { }; override fun onTitleChanged(s: TerminalSession) { }; override fun onSessionFinished(s: TerminalSession) { }
        override fun onCopyTextToClipboard(s: TerminalSession, text: String) { }; override fun onPasteTextFromClipboard(s: TerminalSession) { }; override fun onBell(s: TerminalSession) { }
        override fun onColorsChanged(s: TerminalSession) { }; override fun onTerminalCursorStateChange(state: Boolean) { }; override fun getTerminalCursorStyle(): Int = 0
        override fun logError(t: String, m: String) { }; override fun logWarn(t: String, m: String) { }; override fun logInfo(t: String, m: String) { }
        override fun logDebug(t: String, m: String) { }; override fun logVerbose(t: String, m: String) { }; override fun logStackTraceWithMessage(t: String, m: String, e: Exception) { }; override fun logStackTrace(t: String, e: Exception) { }
    }
    fun stop() {
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) stopMain()
        else {
            val done = java.util.concurrent.CountDownLatch(1)
            AgentRuntime.main.post { try { stopMain() } finally { done.countDown() } }
            check(done.await(3, java.util.concurrent.TimeUnit.SECONDS)) { "Terminal shutdown timed out; authorization remains revoked" }
        }
    }
    @Synchronized private fun stopMain() {
        val old = session
        val lease = rootLease
        rootLease = null; session = null; epoch = -1
        if (lease != null) {
            Thread({
                try {
                    // A channel change may race the child entering su; retain its exact lease.
                    val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(3)
                    var identity: Pair<Int, String>? = null
                    while (System.nanoTime() < deadline && identity == null) {
                        val fields = lease.second.readText().trim().split(Regex("\\s+"))
                        val pid = fields.getOrNull(0)?.toIntOrNull()
                        val started = fields.getOrNull(1)
                        if (pid != null && pid > 1 && started?.toLongOrNull() != null) identity = pid to started
                        else Thread.sleep(25)
                    }
                    identity?.let { (pid, started) ->
                        DeviceBridge.rootSignal(lease.first, pid, OsConstants.SIGTERM, started)
                        Thread.sleep(350)
                        DeviceBridge.rootSignal(lease.first, pid, OsConstants.SIGKILL, started)
                    }
                } catch (_: Exception) { } finally { lease.second.delete() }
            }, "root-pty-cleanup").apply { isDaemon = true; start() }
        }
        old?.let { s -> val pid = s.pid; if (pid > 1) try { if (ProcessGroups.isLeader(pid)) Os.kill(-pid, OsConstants.SIGTERM) } catch (_: Exception) { }; s.finishIfRunning() }
    }
}
