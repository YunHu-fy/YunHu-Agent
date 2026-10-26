package io.localagent.android

import android.net.Uri
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Process-local state. The bearer-bearing launch URL is never broadcast or logged. */
internal object AgentRuntime {
    const val PORT = 8686
    const val ORIGIN = "http://127.0.0.1:8686"
    enum class Phase { STOPPED, STARTING, RUNNING, STOPPING, FAILED }
    @Volatile var phase = Phase.STOPPED
        private set
    @Volatile var detail = "服务已停止"
        private set
    @Volatile private var launchUrl: String? = null

    val worker = Executors.newSingleThreadExecutor { task -> Thread(task, "agent-python-runtime") }
    val main = Handler(Looper.getMainLooper())

    fun update(newPhase: Phase, message: String) {
        if (newPhase != Phase.RUNNING) launchUrl = null
        detail = message
        phase = newPhase
    }

    fun ready(url: String) {
        val uri = Uri.parse(url)
        val fragmentToken = uri.fragment?.takeIf { it.startsWith("token=") }?.removePrefix("token=")
        require(isLocal(uri) && uri.path == "/" && uri.query == null && !fragmentToken.isNullOrBlank()) {
            "Python runtime returned an invalid launch URL"
        }
        launchUrl = url
        update(Phase.RUNNING, "本地服务运行中")
    }

    fun launchUrlIfReady(): String? = if (phase == Phase.RUNNING) launchUrl else null

    fun isLocal(uri: Uri): Boolean = uri.scheme == "http" && uri.host == "127.0.0.1" &&
        uri.port == PORT && uri.userInfo == null
}
