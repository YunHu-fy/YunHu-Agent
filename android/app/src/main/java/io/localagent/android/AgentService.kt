package io.localagent.android

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import org.json.JSONObject

/** Owns the embedded interpreter's HTTP runtime for a user-started session. */
class AgentService : Service() {
    @Volatile private var stopping = false
    private var startupSubmitted = false
    private var failed = false
    private var unhealthy = 0
    private val uiListener = UiPreferences.Listener {
        refreshNotificationChannel()
        if (startupSubmitted && !stopping) getSystemService(NotificationManager::class.java).notify(
            NOTIFICATION_ID, notification(if (AgentRuntime.phase == AgentRuntime.Phase.RUNNING) R.string.notification_running else R.string.notification_starting)
        )
    }
    private val monitor = object : Runnable {
        override fun run() {
            if (stopping || !ServiceLifecycle.desired()) return
            if (AgentRuntime.phase == AgentRuntime.Phase.RUNNING) AgentRuntime.worker.execute {
                val good = checkHealth()
                if (good) { unhealthy = 0; ServiceLifecycle.healthy() } else if (++unhealthy >= 2) {
                    AgentRuntime.main.post {
                        if (!stopping && ServiceLifecycle.desired()) {
                            failed = true
                            AgentRuntime.update(AgentRuntime.Phase.FAILED, "服务健康检查失败，正在尝试有限恢复。")
                            stopSelf()
                            AgentRuntime.main.postDelayed({ if (ServiceLifecycle.desired()) ServiceLifecycle.tryRecover() }, 2000)
                        }
                    }
                }
            }
            AgentRuntime.main.postDelayed(this, 30000)
        }
    }

    override fun onCreate() {
        super.onCreate()
        DeviceBridge.initialize(applicationContext)
        UiPreferences.addListener(uiListener)
        refreshNotificationChannel()
    }

    private fun refreshNotificationChannel() {
        val ui = UiPreferences.read(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL, ui.text("云琥本地服务", "Yunhu local service"), NotificationManager.IMPORTANCE_LOW).apply {
                    description = ui.text("显示用户启动的本地服务及停止操作", "Shows the local service you started and its stop action")
                    setShowBadge(false)
                }
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            ServiceLifecycle.manualStop()
            return START_NOT_STICKY
        }
        if (!ServiceLifecycle.desired()) { stopSelf(); return START_NOT_STICKY }
        if (startupSubmitted || stopping) return if (ServiceLifecycle.desired()) START_STICKY else START_NOT_STICKY
        // Foreground promotion is synchronous, before interpreter startup or networking.
        try {
            val notification = notification(R.string.notification_starting)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (_: RuntimeException) {
            failed = true
            AgentRuntime.update(AgentRuntime.Phase.FAILED, "无法启动前台服务，请检查系统权限后重试。")
            stopSelf()
            return START_NOT_STICKY
        }
        startupSubmitted = true
        AgentRuntime.update(AgentRuntime.Phase.STARTING, "正在启动本地 Python 服务…")
        AgentRuntime.worker.execute {
            try {
                if (stopping) return@execute
                AgentRuntime.update(AgentRuntime.Phase.STARTING, "正在初始化本地 Python 引擎…")
                if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                AgentRuntime.update(AgentRuntime.Phase.STARTING, "正在载入服务与内嵌页面资源…")
                val runtime = Python.getInstance().getModule("android_agent.android_runtime")
                if (stopping) return@execute
                runtime.callAttr("start", filesDir.absolutePath, AgentRuntime.PORT)
                AgentRuntime.update(AgentRuntime.Phase.STARTING, "正在检查本地服务是否就绪…")
                waitForReadiness()
                if (stopping) return@execute
                val launchUrl = runtime.callAttr("launch_url").toString()
                AgentRuntime.main.post {
                    if (!stopping) {
                        try {
                            AgentRuntime.ready(launchUrl)
                            ServiceLifecycle.healthy()
                            AgentRuntime.main.postDelayed(monitor, 30000)
                            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                                getSystemService(NotificationManager::class.java)
                                    .notify(NOTIFICATION_ID, notification(R.string.notification_running))
                            }
                        } catch (_: RuntimeException) { failStartup() }
                    }
                }
            } catch (failure: Throwable) {
                // Throwable messages can contain credentials: show only the fixed startup stage.
                val stage = AgentRuntime.detail
                AgentRuntime.main.post { if (!stopping) failStartup(stage) }
                if (failure is VirtualMachineError || failure is ThreadDeath) throw failure
            }
        }
        // Persistent user-enabled flag gates recovery. Elevated authorization is never restored.
        return if (ServiceLifecycle.desired()) START_STICKY else START_NOT_STICKY
    }

    private fun failStartup(stage: String = "检查启动地址") {
        failed = true
        AgentRuntime.update(AgentRuntime.Phase.FAILED, "本地服务启动失败（" + stage + "）。请检查运行模块、资源或端口占用，然后重试。")
        stopSelf()
    }

    private fun checkHealth(): Boolean {
        val connection = URL(AgentRuntime.ORIGIN + "/api/health/live").openConnection(Proxy.NO_PROXY) as HttpURLConnection
        return try { connection.connectTimeout = 1000; connection.readTimeout = 1000; connection.instanceFollowRedirects = false; connection.useCaches = false
            connection.responseCode == 200 && JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optString("status") == "alive"
        } catch (_: Exception) { false } finally { connection.disconnect() }
    }

    private fun waitForReadiness() {
        val deadline = android.os.SystemClock.elapsedRealtime() + 45_000
        while (!stopping && android.os.SystemClock.elapsedRealtime() < deadline) {
            val connection = URL(AgentRuntime.ORIGIN + "/api/health/live")
                .openConnection(Proxy.NO_PROXY) as HttpURLConnection
            try {
                connection.connectTimeout = 500
                connection.readTimeout = 500
                connection.instanceFollowRedirects = false
                connection.useCaches = false
                if (connection.responseCode == 200) {
                    val body = connection.inputStream.bufferedReader().use { it.readText() }
                    if (JSONObject(body).optString("status") == "alive") return
                }
            } catch (_: IOException) {
                // Listener may not be ready yet. A foreign/unhealthy service is never loaded.
            } finally {
                connection.disconnect()
            }
            Thread.sleep(250)
        }
        if (!stopping) throw IOException("Local runtime readiness timed out")
    }

    override fun onDestroy() {
        stopping = true
        AgentRuntime.main.removeCallbacks(monitor)
        ServiceLifecycle.releaseLocks()
        DeviceBridge.shutdown()
        if (!failed) AgentRuntime.update(AgentRuntime.Phase.STOPPING, "正在停止本地服务…")
        stopForeground(STOP_FOREGROUND_REMOVE)
        // The same serial executor prevents stop racing interpreter initialization/start.
        AgentRuntime.worker.execute {
            try {
                if (startupSubmitted && Python.isStarted()) {
                    Python.getInstance().getModule("android_agent.android_runtime").callAttr("stop")
                }
            } catch (_: Exception) {
                // Do not leak runtime exception text or credentials into Logcat.
            } finally {
                AgentRuntime.main.post {
                    if (AgentRuntime.phase == AgentRuntime.Phase.STOPPING) {
                        AgentRuntime.update(AgentRuntime.Phase.STOPPED, "服务已停止，点按重新启动。")
                    }
                }
            }
        }
        UiPreferences.removeListener(uiListener)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun notification(text: Int): Notification {
        val immutableUpdate = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), immutableUpdate)
        val stop = PendingIntent.getService(
            this, 2, Intent(this, AgentService::class.java).setAction(ACTION_STOP), immutableUpdate
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, CHANNEL)
            else Notification.Builder(this)
        val ui = UiPreferences.read(this)
        val detail = if (text == R.string.notification_running) ui.text("本地服务运行中，点按返回界面", "Local service running. Tap to return.")
            else ui.text("正在启动本地服务…", "Starting local service…")
        return builder.setSmallIcon(R.drawable.brand_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(detail)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(Notification.Action.Builder(R.drawable.brand_notification, ui.text("停止服务", "Stop service"), stop).build())
            .build()
    }

    companion object {
        private const val CHANNEL = "local_agent_runtime"
        private const val NOTIFICATION_ID = 8686
        private const val ACTION_STOP = "io.localagent.android.STOP"
    }
}
