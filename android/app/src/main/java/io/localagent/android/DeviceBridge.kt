package io.localagent.android

import android.app.Activity
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import java.io.File
import java.lang.ref.WeakReference
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.json.JSONArray
import rikka.shizuku.Shizuku

/** Chaquopy-only native API. No addJavascriptInterface and no external Termux activity. */
object DeviceBridge {
    private lateinit var app: Context
    @Volatile private var activity = WeakReference<Activity>(null)
    @Volatile private var selected = "normal"
    @Volatile private var channelReady = false
    @Volatile private var normalRecoveryAllowed = false
    private val authorization = java.util.concurrent.atomic.AtomicLong()
    internal fun terminalEpoch(): Long = synchronized(stateLock) {
        check(channelReady) { "Confirm a permission channel before opening the terminal" }
        authorization.get()
    }
    @Volatile private var rootChecked = false
    @Volatile private var rootGranted = false
    @Volatile private var rootExecutable: String? = null
    @Volatile private var permissionPending = false
    @Volatile private var remote: IDeviceUserService? = null
    @Volatile private var bindLatch: CountDownLatch? = null
    private val routes = ConcurrentHashMap<String, String>()
    private val rpc = Executors.newFixedThreadPool(2) { Thread(it, "shizuku-rpc").apply { isDaemon = true } }
    private val channelLock = Any()
    private val stateLock = Any() // Never hold this lock across process, binder, or UI work.
    private val permissionListener = Shizuku.OnRequestPermissionResultListener { code, _ -> if (code == 8686) permissionPending = false }
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) { remote = IDeviceUserService.Stub.asInterface(binder); bindLatch?.countDown() }
        override fun onServiceDisconnected(name: ComponentName?) {
            synchronized(stateLock) {
                remote = null
                if (selected == "shizuku") { channelReady = false; normalRecoveryAllowed = false; authorization.incrementAndGet() }
            }
        }
    }
    private val userServiceArgs get() = Shizuku.UserServiceArgs(ComponentName(app, ShizukuUserService::class.java))
        .daemon(false).processNameSuffix("command_service").tag("local-agent-shell-v1").version(10000)

    @JvmStatic @Synchronized fun initialize(context: Context) {
        if (!::app.isInitialized) {
            app = context.applicationContext
            RuntimeEnvironment.initialize(app); TermuxRuntime.initialize(app); LocalModelRuntime.initialize(app); DeviceState.initialize(app); ServiceLifecycle.initialize(app)
            KeyStoreCredentialStore.initialize(app)
            synchronized(stateLock) { channelReady = true }
            return
        }
        synchronized(stateLock) {
            // Restore app-UID authority only after service shutdown, never an elevated channel.
            if (normalRecoveryAllowed && selected == "normal" && !channelReady) {
                authorization.incrementAndGet()
                channelReady = true
                normalRecoveryAllowed = false
            }
        }
    }
    @JvmStatic fun credentialRead(profile: String): String = try {
        JSONObject().put("ok", true).put("value", KeyStoreCredentialStore.read(profile)).toString()
    } catch (_: Exception) { bridgeError("credential_read_failed", "无法解密已保存的 API 密钥，请在该模型配置中重新保存密钥。") }
    @JvmStatic fun credentialWrite(profile: String, secret: String): String = try {
        KeyStoreCredentialStore.write(profile, secret)
        JSONObject().put("ok", true).toString()
    } catch (_: Exception) { bridgeError("credential_write_failed", "无法安全保存 API 密钥，请检查设备存储和系统密钥库后重试。") }
    @JvmStatic fun credentialDelete(profile: String): String = try {
        KeyStoreCredentialStore.delete(profile)
        JSONObject().put("ok", true).toString()
    } catch (_: Exception) { bridgeError("credential_delete_failed", "无法删除已保存的密钥，请重试。") }
    /** Presentation mirror only: never changes model instructions, consent or execution authority. */
    @JvmStatic fun appUiPreferences(payload: String): String = try {
        if (!::app.isInitialized) bridgeError("not_initialized", "Native bridge not initialized")
        else { UiPreferences.update(app, payload); JSONObject().put("ok", true).toString() }
    } catch (_: Exception) { bridgeError("invalid_ui_preferences", "Invalid native UI preferences") }
    @JvmStatic fun openPermissionSetup(): String {
        val owner = activity.get() ?: return bridgeError("activity_required", "请返回应用后打开权限设置。")
        owner.runOnUiThread { owner.startActivity(Intent(owner, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_SHOW_SETUP, true)) }
        return JSONObject().put("ok", true).toString()
    }
    internal fun attach(owner: Activity) { initialize(owner); activity = WeakReference(owner); Shizuku.addRequestPermissionResultListener(permissionListener) }
    internal fun detach(owner: Activity) { if (activity.get() === owner) { activity.clear(); Shizuku.removeRequestPermissionResultListener(permissionListener) } }
    private fun shizukuAvailable() = try { Shizuku.pingBinder() && !Shizuku.isPreV11() } catch (_: Exception) { false }
    private fun shizukuGranted() = try { shizukuAvailable() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED } catch (_: Exception) { false }
    internal fun detectRoot(): List<String> {
        val paths = linkedSetOf("/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su", "/debug_ramdisk/su", "/data/adb/magisk/su", "/data/adb/ksu/bin/su", "/data/adb/ap/bin/su")
        System.getenv("PATH")?.split(':')?.filter { it.startsWith('/') && it.length < 1024 && !it.contains("..") }?.take(32)?.forEach { paths.add(it.trimEnd('/') + "/su") }
        return paths.filter { try { File(it).isFile && File(it).canExecute() } catch (_: Exception) { false } }
    }
    @JvmStatic fun status(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native bridge not initialized")
        return JSONObject().put("ok", true).put("selected_channel", selected)
            .put("normal", JSONObject().put("available", true).put("granted", true))
            .put("root", JSONObject().put("available", detectRoot().isNotEmpty()).put("checked", rootChecked).put("granted", rootGranted)
                .put("su_path", rootExecutable ?: JSONObject.NULL).put("candidates", JSONArray(detectRoot())))
            .put("shizuku", JSONObject().put("available", shizukuAvailable()).put("granted", shizukuGranted()).put("request_pending", permissionPending)
                .put("user_service_ready", remote?.asBinder()?.isBinderAlive == true))
            .put("arbitrary_shell", true).put("sandbox", false).toString()
    }
    @JvmStatic fun requestShizuku(): String {
        if (!shizukuAvailable()) return bridgeError("shizuku_unavailable", "Install and activate Shizuku first")
        if (shizukuGranted()) return JSONObject().put("ok", true).put("pending", false).put("granted", true).toString()
        val owner = activity.get() ?: return bridgeError("activity_required", "Return to the app to grant Shizuku")
        permissionPending = true
        owner.runOnUiThread { try { Shizuku.requestPermission(8686) } catch (_: Exception) { permissionPending = false } }
        return JSONObject().put("ok", true).put("pending", true).toString()
    }
    @JvmStatic fun configureChannel(channel: String): String = synchronized(channelLock) configure@ {
        if (channel !in setOf("normal", "root", "shizuku")) return@configure bridgeError("invalid_channel", "Unknown permission channel")
        if (Looper.myLooper() == Looper.getMainLooper() && channel != "normal") return@configure bridgeError("background_required", "Configure privileged channels on a worker thread")
        val epoch = synchronized(stateLock) {
            channelReady = false; normalRecoveryAllowed = false
            selected = channel; rootGranted = false; rootExecutable = null
            if (channel == "root") rootChecked = true
            authorization.incrementAndGet()
        }
        try {
            cancelAll(); TerminalSessions.stop()
            var validatedSu: String? = null
            when (channel) {
                "root" -> {
                    val su = detectRoot().firstOrNull() ?: return@configure bridgeError("root_unavailable", "No executable su detected")
                    // Only this explicit operation may trigger a Root manager authorization dialog.
                    val probe = ProcessBuilder(su, "-c", "/system/bin/sh -c 'exec /system/bin/id -u'").redirectErrorStream(true).start()
                    try {
                        probe.outputStream.close()
                        if (!probe.waitFor(15, TimeUnit.SECONDS)) return@configure bridgeError("root_timeout", "Root authorization timed out")
                        val output = probe.inputStream.bufferedReader().readText().take(4096).trim()
                        if (probe.exitValue() != 0 || output != "0") return@configure bridgeError("root_denied", "su did not grant UID 0")
                        validatedSu = su
                    } finally { if (probe.isAlive) probe.destroyForcibly() }
                }
                "shizuku" -> { if (!shizukuGranted()) return@configure bridgeError("shizuku_not_granted", "Shizuku unavailable or permission denied"); awaitUserService() }
            }
            synchronized(stateLock) {
                if (authorization.get() != epoch) {
                    bridgeError("channel_revoked", "Permission channel changed during authorization; select it again")
                } else {
                    rootExecutable = validatedSu; rootGranted = validatedSu != null
                    selected = channel; channelReady = true
                    JSONObject().put("ok", true).put("selected_channel", selected).toString()
                }
            }
        } catch (failure: Exception) { bridgeError("channel_failed", failure.message ?: "Permission channel unavailable") }
    }
    private fun awaitUserService(): IDeviceUserService {
        remote?.takeIf { it.asBinder().isBinderAlive }?.let { return it }
        val latch = CountDownLatch(1); bindLatch = latch
        AgentRuntime.main.post { try { Shizuku.bindUserService(userServiceArgs, connection) } catch (_: Exception) { latch.countDown() } }
        check(latch.await(15, TimeUnit.SECONDS)) { "Shizuku UserService bind timed out" }
        return remote?.takeIf { it.asBinder().isBinderAlive } ?: error("Shizuku UserService unavailable")
    }
    private fun <T> remoteCall(owner: IDeviceUserService? = remote, block: (IDeviceUserService) -> T): T {
        val service = owner?.takeIf { it.asBinder().isBinderAlive } ?: error("Shizuku UserService disconnected; re-enable explicitly")
        val future = rpc.submit<T> { block(service) }
        return try { future.get(5, TimeUnit.SECONDS) } finally { future.cancel(true) }
    }
    @JvmStatic fun commandStart(requestJson: String): String = try {
        val request = DeviceCommands.parse(requestJson)
        synchronized(channelLock) start@ {
            val authority = synchronized(stateLock) {
                check(channelReady) { "Confirm a permission channel before starting a command" }
                check(request.channel == selected) { "Requested channel differs from explicitly selected channel" }
                if (request.channel == "root") check(rootGranted && rootExecutable != null) { "Root not explicitly granted" }
                Triple(authorization.get(), if (request.channel == "root") rootExecutable else null, remote)
            }
            if (routes.containsKey(request.id)) return@start bridgeError("duplicate_id", "Use a new command id")
            if (request.channel == "shizuku") {
                check(shizukuGranted()) { "Shizuku permission revoked or service unavailable" }
                check(request.runtime == "system") { "Shizuku UID 2000 cannot access app-private Termux prefix; select normal or Root for Termux" }
            }
            if (request.runtime == "termux") check(TermuxRuntime.installed()) { "Deploy the bundled Termux environment first" }
            val current = synchronized(stateLock) { channelReady && selected == request.channel && authorization.get() == authority.first }
            if (!current) return@start bridgeError("channel_revoked", "Permission channel changed before command start; select it again")
            val reply = if (request.channel == "shizuku") remoteCall(authority.third) { it.commandStart(requestJson) } else {
                val selectedSu = authority.second
                val (argv, env) = RuntimeEnvironment.shell(request, selectedSu)
                DeviceProcess.start(request, argv, env, if (request.channel == "root") null else request.cwd ?: if (request.runtime == "termux") RuntimeEnvironment.HOME else app.filesDir.absolutePath,
                    if (selectedSu != null) { pid, signal, identity -> rootSignal(selectedSu, pid, signal, identity) } else null)
            }
            if (JSONObject(reply).optBoolean("ok")) {
                val retained = synchronized(stateLock) {
                    if (!channelReady || selected != request.channel || authorization.get() != authority.first) false
                    else {
                        if (routes.size >= 64) routes.entries.firstOrNull()?.let { routes.remove(it.key) }
                        routes[request.id] = request.channel
                        true
                    }
                }
                if (!retained) {
                    try { if (request.channel == "shizuku") remoteCall(authority.third) { it.commandCancel(request.id) } else DeviceProcess.cancel(request.id) } catch (_: Exception) { }
                    return@start bridgeError("channel_revoked", "Permission channel changed during command start; command canceled")
                }
            }
            reply
        }
    } catch (_: Exception) { bridgeError("command_start_failed", "Invalid command request or unavailable permission channel; check the selected channel and try again") }
    internal fun rootSignal(su: String, pid: Int, signal: Int, identity: String?) {
        if (pid <= 1 || identity?.toLongOrNull() == null) return
        val dollar = 36.toChar()
        val script = "read -r s < /proc/" + pid + "/stat || exit; t=" + dollar + "{s##*) }; set -- " + dollar + "t; [ " + dollar + "{3} = " + pid + " ] && [ " + dollar + "{20} = " + identity + " ] && kill -" + signal + " -- -" + pid
        try {
            val process = ProcessBuilder(su, "-c", "/system/bin/sh -c " + DeviceCommands.quote(script)).redirectOutput(File("/dev/null")).redirectError(File("/dev/null")).start()
            process.outputStream.close()
            if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly()
        } catch (_: Exception) { }
    }
    @JvmStatic fun commandPoll(id: String, after: Int): String = try {
        if (routes[id] == "shizuku") {
            val reply = JSONObject(remoteCall { it.commandPoll(id, after) })
            if (reply.optBoolean("ok") && reply.optBoolean("done")) {
                val result = JSONObject()
                for (stream in listOf("stdout", "stderr")) {
                    val text = StringBuilder(); var offset = 0
                    do {
                        val slice = JSONObject(remoteCall { it.resultSlice(id, stream, offset) })
                        check(slice.optBoolean("ok")) { "Remote result expired" }
                        text.append(slice.getString("text")); offset = slice.getInt("next")
                        for (key in listOf("exit_code", "status", "truncated", "duration_ms")) result.put(key, slice.get(key))
                        if (slice.getBoolean("done")) break
                    } while (offset <= 1024 * 1024)
                    result.put(stream, text.toString())
                }
                reply.put("result", result)
            }
            reply.toString()
        } else DeviceProcess.poll(id, after)
    } catch (failure: Exception) { bridgeError("command_poll_failed", failure.message ?: "Command service disconnected") }
    @JvmStatic fun commandCancel(id: String): String = try {
        if (routes[id] == "shizuku") remoteCall { it.commandCancel(id) } else DeviceProcess.cancel(id)
    } catch (failure: Exception) { bridgeError("command_cancel_failed", failure.message ?: "Command service disconnected") }
    /**
     * Synchronous compatibility surface for in-process callers that must not poll.
     * It reuses the reviewed streaming executor, so channel checks, blacklist policy,
     * process-group handling and output caps stay identical to commandStart/poll.
     */
    @JvmStatic fun executeCommand(requestJson: String): String = try {
        val request = DeviceCommands.parse(requestJson)
        val startReply = commandStart(requestJson)
        if (!JSONObject(startReply).optBoolean("ok")) return startReply
        val deadline = SystemClock.elapsedRealtime() + request.timeoutSeconds * 1000L + 3000L
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        var retained = 0
        var truncated = false
        var after = 0
        var finished: JSONObject? = null
        while (true) {
            if (SystemClock.elapsedRealtime() > deadline) {
                try { commandCancel(request.id) } catch (_: Exception) { }
                return JSONObject().put("ok", false).put("id", request.id).put("status", "timed_out")
                    .put("stdout", stdout.toString()).put("stderr", stderr.toString()).put("exit_code", JSONObject.NULL)
                    .put("error", JSONObject().put("code", "command_timeout").put("message", "命令在审阅的超时时间内未结束。"))
                    .toString()
            }
            val poll = JSONObject(commandPoll(request.id, after))
            if (!poll.optBoolean("ok")) return poll.toString()
            val chunks = poll.optJSONArray("chunks")
            if (chunks != null) {
                val batch = ArrayList<Triple<Int, String, String>>(chunks.length())
                for (index in 0 until chunks.length()) {
                    val chunk = chunks.optJSONObject(index) ?: continue
                    batch.add(Triple(chunk.optInt("seq", after), chunk.optString("stream", "stdout"), chunk.optString("text", "")))
                }
                val drained = CommandDrain.accept(after, batch, stdout, stderr, retained, truncated)
                after = drained.after
                retained = drained.retained
                truncated = drained.truncated
            }
            if (poll.optBoolean("done") && !poll.optBoolean("more", false)) { finished = poll; break }
            Thread.sleep(60L)
        }
        val result = finished?.optJSONObject("result")
        val body = JSONObject().put("ok", true).put("id", request.id)
        if (result == null) {
            body.put("status", "failed").put("exit_code", JSONObject.NULL).put("truncated", truncated)
                .put("stdout", stdout.toString()).put("stderr", stderr.toString())
                .put("error", JSONObject().put("code", "missing_result").put("message", "命令结束但未返回结果。"))
        } else {
            val hasStdout = stdout.isNotEmpty()
            val hasStderr = stderr.isNotEmpty()
            body.put("status", result.optString("status", "succeeded"))
                .put("exit_code", if (result.has("exit_code") && !result.isNull("exit_code")) result.get("exit_code") else JSONObject.NULL)
                .put("duration_ms", result.optLong("duration_ms", 0L))
                .put("truncated", result.optBoolean("truncated", false) || truncated)
                .put("stdout", if (hasStdout) stdout.toString() else result.optString("stdout", ""))
                .put("stderr", if (hasStderr) stderr.toString() else result.optString("stderr", ""))
        }
        body.toString()
    } catch (failure: Exception) {
        bridgeError("command_failed", failure.message ?: "Command execution failed")
    }
    @JvmStatic fun cancelAll(): String {
        DeviceProcess.cancelAll()
        remote?.let { service -> rpc.execute { try { service.cancelAll() } catch (_: Exception) { } } }
        return JSONObject().put("ok", true).toString()
    }
    @JvmStatic fun runtimeStatus(): String = TermuxRuntime.status()
    @JvmStatic fun runtimePathExists(path: String): Boolean {
        return try {
            val prefix = File(RuntimeEnvironment.PREFIX).canonicalFile
            val target = File(path).canonicalFile
            target.path.startsWith(prefix.path + File.separator) && target.isFile && target.canRead()
        } catch (_: Exception) { false }
    }
    @JvmStatic fun runtimeDeploy(): String = TermuxRuntime.deploy()
    @JvmStatic fun localModelStatus(): String = LocalModelRuntime.localModelStatus()
    @JvmStatic fun localModelInstall(): String = LocalModelRuntime.localModelInstall()
    @JvmStatic fun localModelStart(modelPath: String, alias: String, port: Int, contextSize: Int, threads: Int): String =
        LocalModelRuntime.localModelStart(modelPath, alias, port, contextSize, threads)
    @JvmStatic fun localModelStartEx(modelPath: String, alias: String, port: Int, contextSize: Int, threads: Int, optionsJson: String): String =
        LocalModelRuntime.localModelStartEx(modelPath, alias, port, contextSize, threads, optionsJson)
    @JvmStatic fun localModelBackends(): String = LocalModelRuntime.localModelBackends()
    @JvmStatic fun localModelLog(): String = LocalModelRuntime.localModelLog()
    @JvmStatic fun localModelStop(): String = LocalModelRuntime.localModelStop()
    internal fun terminalShell(): Pair<String, Array<String>> {
        terminalEpoch()
        check(selected != "shizuku") { "Shizuku cannot enter private Termux prefix; select normal or Root first" }
        val bash = RuntimeEnvironment.PREFIX + "/bin/bash"
        if (selected == "normal") return bash to arrayOf("bash", "-l")
        check(rootGranted && rootExecutable != null) { "Root authorization is not active" }
        val exports = RuntimeEnvironment.environment("termux").entries.joinToString(" ") { it.key + "=" + DeviceCommands.quote(it.value) }
        val selectedSu = rootExecutable!!
        val handoff = TerminalSessions.prepareRoot(app, selectedSu)
        val dollar = 36.toChar()
        val announce = "read -r __agent_stat < /proc/" + dollar + dollar + "/stat; __agent_tail=" + dollar + "{__agent_stat##*) }; set -- " + dollar + "__agent_tail; printf '%s %s\\n' " + dollar + dollar + " " + dollar + "{20} > " + DeviceCommands.quote(handoff.absolutePath) + "; "
        val command = "export " + exports + "; cd " + DeviceCommands.quote(RuntimeEnvironment.HOME) + " || exit 125; " + announce + "exec " + DeviceCommands.quote(bash) + " -l"
        val setsid = DeviceCommands.quote(RuntimeEnvironment.PREFIX + "/bin/setsid")
        return selectedSu to arrayOf("su", "-c", "exec " + setsid + " -w -c /system/bin/sh -c " + DeviceCommands.quote(command))
    }
    @JvmStatic fun openTerminal(): String {
        if (selected == "shizuku") return bridgeError("runtime_inaccessible", "Shizuku cannot access private Termux; explicitly select normal or Root first")
        if (!TermuxRuntime.installed()) return bridgeError("runtime_not_installed", "Deploy the bundled Termux environment first")
        return openInternal(Intent(app, TerminalActivity::class.java))
    }
    private fun openInternal(intent: Intent): String {
        val owner = activity.get() ?: return bridgeError("activity_required", "Return to the app before opening native UI")
        owner.runOnUiThread { if (!owner.isFinishing) owner.startActivity(intent) }
        return JSONObject().put("ok", true).put("opened", true).toString()
    }
    @JvmStatic fun openLicenses(): String = openInternal(Intent(app, LicensesActivity::class.java))
    @JvmStatic fun deviceState(): String = DeviceState.snapshot()
    @JvmStatic fun diagnostics(): String = JSONObject().put("ok", true).put("checked_at", java.time.Instant.now().toString())
        .put("environment", DeviceState.environment()).put("permissions", JSONObject(status())).put("runtime", JSONObject(runtimeStatus()))
        .put("service", ServiceLifecycle.status()).put("active_commands", DeviceProcess.activeCount()).toString()
    @JvmStatic fun serviceControl(action: String): String = ServiceLifecycle.control(action, activity.get())
    @JvmStatic fun shutdown() {
        synchronized(stateLock) {
            // Revoke immediately; in-flight authorization cannot publish a stale epoch.
            channelReady = false; normalRecoveryAllowed = true; authorization.incrementAndGet()
            selected = "normal"; rootGranted = false; rootExecutable = null
        }
        cancelAll(); TerminalSessions.stop()
        if (::app.isInitialized) AgentRuntime.main.post { try { Shizuku.unbindUserService(userServiceArgs, connection, true) } catch (_: Exception) { }; remote = null }
    }
}
