package io.localagent.android

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.ContentObserver
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.json.JSONArray

/** Read-only device observation; unavailable data carries a reason instead of a guessed value. */
internal object DeviceState {
    private lateinit var app: Context
    @Volatile private var cached = "{}"
    @Volatile private var cachedAt = 0L
    @Volatile private var env: JSONObject? = null
    private val worker = Executors.newSingleThreadScheduledExecutor { Thread(it, "device-state").apply { isDaemon = true } }
    fun initialize(context: Context) {
        if (::app.isInitialized) return
        app = context.applicationContext
        app.registerReceiver(object : BroadcastReceiver() { override fun onReceive(c: Context?, i: Intent?) { worker.execute { refresh() } } }, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        app.contentResolver.registerContentObserver(Settings.System.CONTENT_URI, true, object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { worker.execute { refresh() } }
        })
        try { app.getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { worker.execute { refresh() } }
            override fun onLost(network: Network) { worker.execute { refresh() } }
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) { worker.execute { refresh() } }
        }) } catch (_: Exception) { }
        worker.scheduleWithFixedDelay({ refresh() }, 0, 5, TimeUnit.SECONDS)
    }
    fun snapshot(): String {
        val value = JSONObject(cached)
        val age = if (cachedAt == 0L) -1L else SystemClock.elapsedRealtime() - cachedAt
        return value.put("ok", true).put("stale", age < 0 || age > 15000).put("age_ms", age)
            .put("meta", JSONObject().put("source", "android_native_cache").put("refresh_interval_ms", 5000).put("foreground_requires_usage_access", true)).toString()
    }
    @Synchronized private fun refresh() {
        if (!::app.isInitialized) return
        val body = JSONObject().put("checked_at", java.time.Instant.now().toString())
        val errors = JSONObject()
        fun field(name: String, block: () -> Any?) { try { body.put(name, block() ?: JSONObject.NULL) } catch (e: Exception) { body.put(name, JSONObject.NULL); errors.put(name, e.message ?: e.javaClass.simpleName) } }
        field("brightness") { JSONObject().put("value", Settings.System.getInt(app.contentResolver, Settings.System.SCREEN_BRIGHTNESS))
            .put("mode", Settings.System.getInt(app.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE)).put("range", "ROM-dependent, commonly 0..255") }
        field("volume") {
            val audio = app.getSystemService(AudioManager::class.java)
            val streams = mapOf("media" to AudioManager.STREAM_MUSIC, "ring" to AudioManager.STREAM_RING, "alarm" to AudioManager.STREAM_ALARM, "notification" to AudioManager.STREAM_NOTIFICATION)
            JSONObject().also { value -> streams.forEach { (name, id) -> value.put(name, JSONObject().put("value", audio.getStreamVolume(id)).put("max", audio.getStreamMaxVolume(id))) } }
        }
        field("battery") {
            val intent = app.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val manager = app.getSystemService(BatteryManager::class.java)
            JSONObject().put("capacity_percent", manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
                .put("charging", manager.isCharging).put("temperature_tenths_c", intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1)
                .put("status", intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1)
        }
        field("network") {
            val manager = app.getSystemService(ConnectivityManager::class.java)
            val caps = manager.getNetworkCapabilities(manager.activeNetwork)
            JSONObject().put("connected", caps != null).put("validated", caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true)
                .put("wifi", caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true).put("cellular", caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true)
                .put("vpn", caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true).put("metered", manager.isActiveNetworkMetered)
        }
        field("foreground_app") {
            val ops = app.getSystemService(AppOpsManager::class.java)
            if (ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), app.packageName) != AppOpsManager.MODE_ALLOWED) {
                errors.put("foreground_app", "Usage access not granted; foreground app is unavailable")
                null
            } else {
                val now = System.currentTimeMillis()
                val events = app.getSystemService(UsageStatsManager::class.java).queryEvents(now - 60 * 60 * 1000, now)
                val event = android.app.usage.UsageEvents.Event()
                var packageName: String? = null; var timestamp = 0L
                while (events.hasNextEvent()) { events.getNextEvent(event); if (event.eventType == android.app.usage.UsageEvents.Event.ACTIVITY_RESUMED) { packageName = event.packageName; timestamp = event.timeStamp } }
                if (packageName == null) { errors.put("foreground_app", "No recent resumed activity in permitted UsageStats history"); null }
                else JSONObject().put("package", packageName).put("observed_at_ms", timestamp).put("source", "UsageStats last resumed; not guaranteed current")
            }
        }
        val state = JSONObject()
        for (name in listOf("brightness", "volume", "battery", "network", "foreground_app")) state.put(name, body.opt(name) ?: JSONObject.NULL)
        body.put("state", state).put("errors", errors)
        cached = body.toString(); cachedAt = SystemClock.elapsedRealtime()
    }
    @Synchronized fun environment(): JSONObject {
        env?.let { return JSONObject(it.toString()) }
        val paths = JSONObject()
        for (name in listOf("sh", "toybox", "settings", "input", "pm", "am", "svc", "cmd", "dumpsys", "getenforce", "getprop", "setsid")) paths.put(name, if (File("/system/bin/"+name).canExecute()) "/system/bin/"+name else JSONObject.NULL)
        val properties = JSONObject()
        for (name in listOf("ro.miui.ui.version.name", "ro.build.version.emui", "ro.build.version.opporom", "ro.vivo.os.version", "ro.build.version.oneui", "ro.build.version.release", "ro.product.cpu.abi")) properties.put(name, probe(listOf("/system/bin/getprop", name)))
        val result = JSONObject().put("checked_at", java.time.Instant.now().toString()).put("sdk", Build.VERSION.SDK_INT).put("supported", NativeSetupPolicy.supported(Build.VERSION.SDK_INT, Build.SUPPORTED_ABIS.toList()))
            .put("manufacturer", Build.MANUFACTURER).put("brand", Build.BRAND).put("model", Build.MODEL).put("display", Build.DISPLAY).put("rom_properties", properties)
            .put("abis", JSONArray(Build.SUPPORTED_ABIS.toList())).put("primary_user", android.os.Process.myUid()/100000 == 0).put("uid", android.os.Process.myUid())
            .put("selinux", probe(listOf("/system/bin/getenforce"))).put("su_candidates", JSONArray(DeviceBridge.detectRoot())).put("tools", paths)
            .put("files_dir", app.filesDir.absolutePath).put("private_prefix_check", RuntimeEnvironment.privatePrefixDiagnostics()).put("prefix", RuntimeEnvironment.PREFIX).put("available_bytes", app.filesDir.usableSpace).put("page_size", RuntimeEnvironment.pageSizeBytes())
            .put("notes", "su presence does not prove authorization; SELinux and ROM policy remain effective; no settings were changed")
        env = result
        return JSONObject(result.toString())
    }
    private fun probe(argv: List<String>): Any {
        return try {
            val process = ProcessBuilder(argv).redirectErrorStream(true).start()
            process.outputStream.close()
            try { if (!process.waitFor(800, TimeUnit.MILLISECONDS)) { process.destroyForcibly(); "unavailable: probe timeout" }
                else if (process.exitValue() != 0) "unavailable: exit " + process.exitValue() else process.inputStream.bufferedReader().readText().take(2048).trim() }
            finally { if (process.isAlive) process.destroyForcibly() }
        } catch (failure: Exception) { "unavailable: " + failure.javaClass.simpleName }
    }
}
