package io.localagent.android

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit
import org.json.JSONObject

/** Persistent user stop flag is authoritative for both sticky recovery and periodic work. */
internal object ServiceLifecycle {
    private lateinit var app: Context
    private val prefs get() = app.getSharedPreferences("native_service", Context.MODE_PRIVATE)
    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null
    @Volatile var lastHealthyAt = 0L
    @Volatile var recoveryError: String? = null
    private val restartEpoch = java.util.concurrent.atomic.AtomicLong()
    fun initialize(context: Context) { if (!::app.isInitialized) app = context.applicationContext }
    fun desired() = ::app.isInitialized && prefs.getBoolean("user_enabled", false)
    fun requestStart() {
        prefs.edit().putBoolean("user_enabled", true).apply()
        WorkManager.getInstance(app).enqueueUniquePeriodicWork("agent-watchdog", ExistingPeriodicWorkPolicy.KEEP, PeriodicWorkRequestBuilder<AgentWatchdog>(15, TimeUnit.MINUTES).build())
        app.startForegroundService(Intent(app, AgentService::class.java))
    }
    fun manualStop() {
        restartEpoch.incrementAndGet()
        prefs.edit().putBoolean("user_enabled", false).apply()
        WorkManager.getInstance(app).cancelUniqueWork("agent-watchdog")
        releaseLocks(); app.stopService(Intent(app, AgentService::class.java))
    }
    fun tryRecover(): Boolean {
        if (!desired()) return false
        val now = System.currentTimeMillis()
        val window = prefs.getLong("recovery_window", 0)
        val count = if (now - window > 15 * 60 * 1000) 0 else prefs.getInt("recovery_count", 0)
        if (count >= 3) { recoveryError = "Recovery paused after three attempts in 15 minutes; restart manually"; return false }
        prefs.edit().putLong("recovery_window", if (count == 0) now else window).putInt("recovery_count", count + 1).apply()
        return try { app.startForegroundService(Intent(app, AgentService::class.java)); true } catch (e: Exception) { recoveryError = "Background service start denied: " + e.javaClass.simpleName; false }
    }
    fun healthy() { lastHealthyAt = System.currentTimeMillis(); recoveryError = null; if (prefs.getBoolean("locks_opt_in", false)) acquireLocks() }
    @Synchronized fun acquireLocks() {
        if (!desired()) return
        prefs.edit().putBoolean("locks_opt_in", true).apply()
        val power = app.getSystemService(PowerManager::class.java)
        if (wake == null) wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "com.termux:agent").apply { setReferenceCounted(false) }
        wake?.acquire(10 * 60 * 1000L)
        @Suppress("DEPRECATION")
        if (wifi == null) wifi = (app.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager).createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "com.termux:agent").apply { setReferenceCounted(false) }
        if (wifi?.isHeld != true) wifi?.acquire()
    }
    @Synchronized fun releaseLocks() {
        try { if (wake?.isHeld == true) wake?.release() } catch (_: Exception) { }
        try { if (wifi?.isHeld == true) wifi?.release() } catch (_: Exception) { }
        wake = null; wifi = null
    }
    fun status(): JSONObject {
        val power = app.getSystemService(PowerManager::class.java)
        return JSONObject().put("phase", AgentRuntime.phase.name.lowercase()).put("detail", AgentRuntime.detail).put("user_enabled", desired())
            .put("last_healthy_at_ms", lastHealthyAt).put("recovery_error", recoveryError ?: JSONObject.NULL)
            .put("battery_optimization_ignored", power.isIgnoringBatteryOptimizations(app.packageName))
            .put("locks_opt_in", prefs.getBoolean("locks_opt_in", false)).put("wake_lock_held", wake?.isHeld == true).put("wifi_lock_held", wifi?.isHeld == true)
            .put("watchdog_interval_minutes", 15).put("recovery_limit", "3 per 15 minutes; never after manual stop")
    }
    fun control(action: String, activity: Activity?): String = try {
        when (action) {
            "stop" -> AgentRuntime.main.post { manualStop() }
            "start" -> AgentRuntime.main.post { requestStart() }
            "restart" -> {
                val epoch = restartEpoch.incrementAndGet()
                AgentRuntime.main.post {
                    if (epoch != restartEpoch.get()) return@post
                    prefs.edit().putBoolean("user_enabled", false).apply()
                    app.stopService(Intent(app, AgentService::class.java))
                    waitThenRestart(epoch, 0)
                }
            }
            "battery_settings", "app_settings", "usage_settings" -> {
                val owner = activity ?: return bridgeError("activity_required", "Open settings from the visible app")
                val intent = when (action) {
                    "battery_settings" -> Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                    "usage_settings" -> Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
                    else -> Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + app.packageName))
                }
                owner.runOnUiThread { try { owner.startActivity(intent) } catch (_: Exception) { } }
            }
            "locks_on" -> { check(desired()) { "Start service before enabling locks" }; acquireLocks() }
            "locks_off" -> { prefs.edit().putBoolean("locks_opt_in", false).apply(); releaseLocks() }
            else -> return bridgeError("invalid_action", "Unsupported service control action")
        }
        JSONObject().put("ok", true).put("action", action).put("accepted", true).put("service", status()).toString()
    } catch (e: Exception) { bridgeError("service_control_failed", e.message ?: e.javaClass.simpleName) }
    private fun waitThenRestart(epoch: Long, attempt: Int) {
        if (epoch != restartEpoch.get()) return
        if (AgentRuntime.phase in setOf(AgentRuntime.Phase.STOPPED, AgentRuntime.Phase.FAILED)) { requestStart(); return }
        if (attempt >= 100) { recoveryError = "Restart waited 10 seconds for shutdown; start manually"; return }
        AgentRuntime.main.postDelayed({ waitThenRestart(epoch, attempt + 1) }, 100)
    }
}

class AgentWatchdog(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        DeviceBridge.initialize(applicationContext)
        if (ServiceLifecycle.desired() && AgentRuntime.phase in setOf(AgentRuntime.Phase.STOPPED, AgentRuntime.Phase.FAILED)) ServiceLifecycle.tryRecover()
        return Result.success()
    }
}
