package io.localagent.android

import android.content.Context
import android.os.SystemClock
import android.system.Os
import android.system.OsConstants
import java.io.File
import java.io.FileOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray
import org.json.JSONObject

/** App-private llama.cpp lifecycle with fixed executables, bounded logs, and procfs identity checks. */
object LocalModelRuntime {
    private const val LOG_LIMIT_BYTES = 4 * 1024 * 1024
    private const val INSTALL_LOG_LIMIT_BYTES = 512 * 1024
    private const val INSTALL_TIMEOUT_MINUTES = 15L
    // Loading a 1.5B GGUF from flash regularly takes longer than a couple of seconds; a short
    // window used to report a healthy-but-slow server as "exited".
    private const val READY_WAIT_MS = 20_000L
    private const val PROBE_TTL_MS = 120_000L
    private val aliasPattern = Regex("[A-Za-z0-9_.-]{1,64}")
    private val installer = Executors.newSingleThreadExecutor { task -> Thread(task, "local-model-install").apply { isDaemon = true } }
    private val lock = Any()
    private lateinit var app: Context
    @Volatile private var installing = false
    private var installStage = "idle"
    private var installError: String? = null
    private var installExitCode: Int? = null
    private var installProcess: Process? = null
    private var serverRecord: ServerRecord? = null
    private var installVersion: String? = null
    private val probeLock = Any()
    @Volatile private var cachedProbe: EngineProbe? = null
    @Volatile private var cachedProbeAt = 0L

    private data class ServerRecord(
        val pid: Int,
        val startTicks: String,
        val commandDigest: String,
        val alias: String,
        val port: Int,
        val modelName: String,
        val healthy: Boolean,
        val process: Process?,
        val contextSize: Int = 0,
        val threads: Int = 0,
        val backend: String = "cpu"
    )

    /** Parsed llama.cpp capabilities; only flags the installed build advertises are used. */
    private data class EngineProbe(
        val available: Boolean,
        val flags: Set<String>,
        val devices: List<Triple<String, String, String>>,
        val output: String,
        val error: String?
    ) {
        val gpuDevices: List<Triple<String, String, String>> get() = devices.filter { it.third == "gpu" }
        val npuDevices: List<Triple<String, String, String>> get() = devices.filter { it.third == "npu" }
    }

    private class BoundedLog(file: File, private val limit: Int) {
        private val output = FileOutputStream(file, false)
        private var retained = 0
        private var closed = false
        init { Os.chmod(file.path, 384) }

        @Synchronized fun append(bytes: ByteArray, offset: Int, length: Int) {
            if (closed || retained >= limit || length <= 0) return
            val count = minOf(length, limit - retained)
            output.write(bytes, offset, count)
            retained += count
        }

        @Synchronized fun close() {
            if (closed) return
            closed = true
            try { output.flush(); output.fd.sync() } catch (_: Exception) { }
            try { output.close() } catch (_: Exception) { }
        }
    }

    fun initialize(context: Context) { app = context.applicationContext }

    @JvmStatic fun localModelStatus(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        return try { synchronized(lock) { statusLocked().toString() } }
        catch (_: Exception) { bridgeError("model_status_failed", "Could not read local model runtime status") }
    }

    @JvmStatic fun localModelInstall(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        if (!TermuxRuntime.installed()) return bridgeError("termux_not_installed", "Deploy the Termux runtime before installing llama.cpp")
        synchronized(lock) {
            if (installing) return statusLocked().toString()
            val executable = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
            if (executable.isFile && executable.canExecute()) {
                installStage = "succeeded"
                installError = null
                return statusLocked().put("started", false).toString()
            }
            installing = true
            installStage = "starting"
            installError = null
            installExitCode = null
        }
        try { installer.execute { runInstall() } }
        catch (_: Exception) {
            synchronized(lock) {
                installing = false
                installStage = "failed"
                installError = "Could not start the package installer"
            }
            return bridgeError("install_start_failed", "Could not start the local model package installer")
        }
        return synchronized(lock) { statusLocked().put("started", true).toString() }
    }

    @JvmStatic fun localModelStart(modelPath: String, alias: String, port: Int, contextSize: Int, threads: Int): String =
        localModelStartEx(modelPath, alias, port, contextSize, threads, "{}")

    /**
     * Optional acceleration surface. Every extra flag is emitted only when the installed
     * llama.cpp build advertises it and a matching device was enumerated, so an
     * unsupported toggle fails loudly instead of silently running on another backend.
     */
    @JvmStatic fun localModelStartEx(modelPath: String, alias: String, port: Int, contextSize: Int, threads: Int, optionsJson: String): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        if (!aliasPattern.matches(alias)) return bridgeError("invalid_alias", "Alias must match [A-Za-z0-9_.-]{1,64}")
        if (port !in 18000..18999) return bridgeError("invalid_port", "Port must be between 18000 and 18999")
        if (contextSize !in 512..8192) return bridgeError("invalid_context_size", "Context size must be between 512 and 8192")
        if (threads !in 1..16) return bridgeError("invalid_threads", "Thread count must be between 1 and 16")
        val model = try { validateModel(modelPath) }
        catch (_: Exception) { return bridgeError("invalid_model_path", "Select a readable .gguf file inside the app model directory") }
        if (!TermuxRuntime.installed()) return bridgeError("termux_not_installed", "Deploy the Termux runtime before starting a local model")
        val options = try { if (optionsJson.isBlank()) JSONObject() else JSONObject(optionsJson) }
        catch (_: Exception) { return bridgeError("invalid_options", "Acceleration options must be a JSON object") }
        val backend = options.optJSONObject("backend") ?: JSONObject()
        val useCpu = backend.optBoolean("cpu", false)
        val useGpu = backend.optBoolean("gpu", false)
        val useNpu = backend.optBoolean("npu", false)
        val lowMemory = backend.optBoolean("low_memory", false)
        val labels = mutableListOf("cpu")
        if (useCpu) labels.add("cpu-accel")
        if (useGpu) labels.add("gpu")
        if (useNpu) labels.add("npu")
        if (lowMemory) labels.add("low-memory")
        val backendLabel = labels.joinToString("+")

        synchronized(lock) {
            if (installing) return bridgeError("installer_busy", "Wait for llama.cpp installation to finish before starting a model")
            val active = currentServerLocked()
            if (active != null) return JSONObject().put("ok", false).put("error", "model_already_running")
                .put("message", "Stop the currently managed local model before starting another")
                .put("server", serverJson(active)).toString()
            val executable = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
            if (!executable.isFile || !executable.canExecute()) {
                return bridgeError("llama_server_missing", "llama-server is not installed; call localModelInstall() first")
            }
            // The installed build decides which optional flags are legal; probing first is what
            // keeps an unknown flag from killing the server during argument parsing.
            val probe = engineProbe()
            val accelerated = useGpu || useNpu || useCpu
            if (accelerated && !probe.available) {
                return bridgeError("backend_unavailable", "无法读取内置 llama.cpp 的能力信息：" + (probe.error ?: "未知原因") + "；请关闭硬件加速后重试。")
            }
            if (useGpu) {
                if (probe.gpuDevices.isEmpty()) {
                    return bridgeError("gpu_unavailable", "当前 llama.cpp 构建未枚举到 GPU 后端设备；请关闭 GPU 加速或改用 CPU。")
                }
                if ("n-gpu-layers" !in probe.flags) {
                    return bridgeError("gpu_unsupported", "当前 llama.cpp 构建不支持 GPU 层卸载参数；请关闭 GPU 加速。")
                }
            }
            if (useNpu) {
                if (probe.npuDevices.isEmpty()) {
                    return bridgeError("npu_unavailable", "当前 llama.cpp 构建未枚举到 NPU 后端设备；请关闭 NPU 加速或改用 CPU/GPU。")
                }
                if ("n-gpu-layers" !in probe.flags || "device" !in probe.flags) {
                    return bridgeError("npu_unsupported", "当前 llama.cpp 构建不支持设备选择参数，无法把计算派发到 NPU。")
                }
            }
            val engineBackend = LocalEngineArgs.Backend(
                cpu = useCpu, gpu = useGpu, npu = useNpu, lowMemory = lowMemory,
                gpuDevice = probe.gpuDevices.firstOrNull()?.first,
                npuDevice = probe.npuDevices.firstOrNull()?.first
            )
            // A leftover server from an earlier run can still own the port; binding fails
            // instantly in that case, which used to look like an engine crash.
            val actualPort = freePort(port)
            val attempts = listOf(false, true).map { minimal ->
                LocalEngineArgs.build(executable.absolutePath, model.absolutePath, alias, actualPort,
                    contextSize, threads, probe.flags, engineBackend, minimal)
            }
            var lastFailure: StartOutcome? = null
            for ((index, argv) in attempts.withIndex()) {
                val outcome = startAttempt(argv, alias, actualPort, model, contextSize, threads, backendLabel)
                if (outcome.ok) return outcome.json.toString()
                lastFailure = outcome
                if (index > 0 || !outcome.argumentRejected) break
                // The engine rejected an optional flag: retry once with the minimal argv.
                Thread.sleep(150L)
            }
            return (lastFailure?.json ?: failureJson("server_start_failed", "", null, false, actualPort, actualPort != port)).toString()
        }
    }

    private data class StartOutcome(val ok: Boolean, val json: JSONObject, val argumentRejected: Boolean)

    /** One launch attempt: identity-checked process, bounded log, explicit readiness wait. */
    private fun startAttempt(argv: List<String>, alias: String, port: Int, model: File,
                             contextSize: Int, threads: Int, backendLabel: String): StartOutcome {
        val digest = commandDigest(argv)
        val existingPids = matchingDirectChildPids(digest, android.os.Process.myPid())
        var launchedPid = -1
        var log: BoundedLog? = null
        var process: Process? = null
        val logFile = try { privateFile("server.log") } catch (_: Exception) { null }
        try {
            log = BoundedLog(privateFile("server.log"), LOG_LIMIT_BYTES)
            val builder = ProcessBuilder(argv)
            builder.environment().clear()
            builder.environment().putAll(RuntimeEnvironment.environment("termux"))
            builder.directory(File(RuntimeEnvironment.HOME))
            process = builder.start()
            process.outputStream.close()
            drainToLog(listOf(process.inputStream, process.errorStream), log, "local-model-server-log")
            val identity = awaitNewChildProcess(digest, android.os.Process.myPid(), existingPids, process)
            check(identity != null) { "server process identity unavailable" }
            launchedPid = identity.first
            val record = ServerRecord(launchedPid, identity.second, digest, alias, port, model.name, false, process, contextSize, threads, backendLabel)
            check(isExactProcess(record)) { "process identity verification failed" }
            persistRecord(record)
            serverRecord = record

            val healthy = awaitReady(record)
            if (!isExactProcess(record)) {
                serverRecord = null
                clearPersistedRecord()
                try { log.close() } catch (_: Exception) { }
                val text = logFile?.let { readLogTail(it) }.orEmpty()
                val exit = exitCodeOf(process)
                val rejected = LocalEngineArgs.rejectedArguments(text)
                return StartOutcome(false, failureJson("server_exited", text, exit, rejected, port), rejected)
            }
            val finalRecord = record.copy(healthy = healthy)
            serverRecord = finalRecord
            persistRecord(finalRecord)
            return StartOutcome(true, JSONObject().put("ok", true).put("running", true).put("healthy", healthy)
                .put("active_model_id", alias).put("state", if (healthy) "ready" else "starting").put("alias", alias).put("port", port)
                .put("context_size", contextSize).put("threads", threads).put("backend", backendLabel)
                .put("message", if (healthy) "Local model server is healthy" else "Server started; the model is still loading"), false)
        } catch (_: Exception) {
            val started = process
            if (started != null && started.isAlive) {
                val pid = launchedPid
                val ticks = if (pid > 1) procStartTicks(pid) else null
                val cleanup = if (ticks != null && procCommandDigest(pid) == digest) {
                    ServerRecord(pid, ticks, digest, alias, port, model.name, false, started)
                } else null
                if (cleanup != null) signalIfExact(cleanup, OsConstants.SIGTERM)
                else try { started.destroyForcibly() } catch (_: Exception) { }
            }
            try { log?.close() } catch (_: Exception) { }
            serverRecord?.takeIf { it.alias == alias && it.port == port }?.let { serverRecord = null; clearPersistedRecord() }
            val text = logFile?.let { readLogTail(it) }.orEmpty()
            val rejected = LocalEngineArgs.rejectedArguments(text)
            return StartOutcome(false, failureJson("server_start_failed", text, exitCodeOf(process), rejected, port), rejected)
        }
    }

    /** Failure payload: code plus the actionable cause and the retained log tail. */
    private fun failureJson(code: String, logText: String, exitCode: Int?, rejected: Boolean, port: Int, rebound: Boolean = false): JSONObject {
        val prefix = if (code == "server_exited") "llama-server 启动后立即退出。" else "无法启动或校验 llama-server。"
        val suffix = if (rebound) "（${port} 端口已被占用，已改用可用端口。）" else ""
        return JSONObject().put("ok", false)
            .put("error", JSONObject().put("code", code).put("message", prefix + suffix + LocalEngineArgs.diagnose(logText, exitCode)))
            .put("exit_code", exitCode ?: JSONObject.NULL).put("port", port)
            .put("argument_rejected", rejected).put("log_tail", LocalEngineArgs.tail(logText))
    }

    /** Bounded tail of the private server log, so the UI can show why the engine failed. */
    @JvmStatic fun localModelLog(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        return try {
            val file = privateFile("server.log")
            val text = readLogTail(file, 64 * 1024)
            JSONObject().put("ok", true).put("path", file.absolutePath).put("bytes", file.length()).put("text", text).toString()
        } catch (_: Exception) {
            bridgeError("log_unavailable", "无法读取本地引擎日志")
        }
    }

    private fun readLogTail(file: File, limit: Int = 12 * 1024): String {
        return try {
            if (!file.isFile) "" else {
                val length = file.length()
                val start = if (length > limit) length - limit else 0L
                java.io.RandomAccessFile(file, "r").use { handle ->
                    handle.seek(start)
                    val bytes = ByteArray((length - start).toInt())
                    handle.readFully(bytes)
                    bytes.toString(Charsets.UTF_8)
                }
            }
        } catch (_: Exception) { "" }
    }

    private fun exitCodeOf(process: Process?): Int? = try {
        if (process == null || process.isAlive) null else process.exitValue()
    } catch (_: Exception) { null }

    /** Reserves the first bindable loopback port, preferring the requested one. */
    private fun freePort(preferred: Int): Int {
        for (candidate in preferred..(preferred + 20).coerceAtMost(18999)) {
            try {
                java.net.ServerSocket().use { socket ->
                    socket.reuseAddress = true
                    socket.bind(InetSocketAddress("127.0.0.1", candidate))
                }
                return candidate
            } catch (_: Exception) { }
        }
        return preferred
    }

    @JvmStatic fun localModelStop(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        synchronized(lock) {
            val record = currentServerLocked()
                ?: return JSONObject().put("ok", true).put("running", false).put("stopped", false).toString()
            var signalSent = false
            try {
                if (isExactProcess(record)) {
                    signalIfExact(record, OsConstants.SIGTERM)
                    signalSent = true
                    val deadline = android.os.SystemClock.elapsedRealtime() + 750L
                    while (android.os.SystemClock.elapsedRealtime() < deadline && isExactProcess(record)) Thread.sleep(40L)
                    if (isExactProcess(record)) signalIfExact(record, OsConstants.SIGKILL)
                    try { record.process?.waitFor(150L, TimeUnit.MILLISECONDS) } catch (_: Exception) { }
                }
            } catch (_: Exception) {
                return bridgeError("server_stop_failed", "Could not stop the verified local model process")
            }
            if (!isExactProcess(record)) {
                serverRecord = null
                clearPersistedRecord()
                return JSONObject().put("ok", true).put("running", false).put("stopped", signalSent).toString()
            }
            return JSONObject().put("ok", false).put("error", "server_stop_timeout")
                .put("message", "The verified model process is still running").put("pid", record.pid).toString()
        }
    }

    private fun runInstall() {
        var log: BoundedLog? = null
        try {
            synchronized(lock) { installStage = "checking" }
            check(TermuxRuntime.installed()) { "Termux runtime unavailable" }
            val pkg = File(RuntimeEnvironment.PREFIX, "bin/pkg")
            check(pkg.isFile && pkg.canExecute()) { "pkg executable unavailable" }
            log = BoundedLog(privateFile("install.log"), INSTALL_LOG_LIMIT_BYTES)
            val builder = ProcessBuilder(pkg.absolutePath, "install", "-y", "llama-cpp")
            builder.environment().clear()
            builder.environment().putAll(RuntimeEnvironment.environment("termux"))
            builder.directory(File(RuntimeEnvironment.HOME))
            builder.redirectErrorStream(true)
            synchronized(lock) { installStage = "installing" }
            val process = builder.start()
            process.outputStream.close()
            synchronized(lock) { installProcess = process }
            drainToLog(listOf(process.inputStream), log, "local-model-install-log")
            val completed = process.waitFor(INSTALL_TIMEOUT_MINUTES, TimeUnit.MINUTES)
            if (!completed) {
                process.destroy()
                if (!process.waitFor(500L, TimeUnit.MILLISECONDS)) process.destroyForcibly()
                process.waitFor(2L, TimeUnit.SECONDS)
                error("Package installation timed out")
            }
            val exit = process.exitValue()
            synchronized(lock) { installExitCode = exit }
            check(exit == 0) { "pkg exited with status $exit" }
            val server = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
            check(server.isFile && server.canExecute()) { "llama-server executable missing after package install" }
            cachedProbe = null; cachedProbeAt = 0L
            // The build identifier is recorded, not asserted: some packages omit --version.
            synchronized(lock) { installStage = "verifying" }
            val version = runEngine(listOf("--version"), 6000L).lineSequence().firstOrNull { it.isNotBlank() }?.trim()?.take(160)
            synchronized(lock) { installStage = "succeeded"; installError = null; installVersion = version }
        } catch (failure: Exception) {
            synchronized(lock) {
                installStage = "failed"
                installError = when {
                    failure.message?.contains("timed out", ignoreCase = true) == true -> "Package installation timed out"
                    failure.message?.contains("status", ignoreCase = true) == true -> "pkg install failed"
                    failure.message?.contains("unavailable", ignoreCase = true) == true -> "Termux runtime or pkg executable unavailable"
                    else -> "Package installation failed; inspect the private install log"
                }
            }
        } finally {
            try { log?.close() } catch (_: Exception) { }
            synchronized(lock) { installProcess = null; installing = false }
        }
    }

    private fun statusLocked(): JSONObject {
        val runtimeInstalled = TermuxRuntime.installed()
        val executable = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
        var active = currentServerLocked()
        if (active != null) {
            val observedHealthy = quickHealth(active)
            if (observedHealthy != active.healthy) {
                active = active.copy(healthy = observedHealthy)
                serverRecord = active
                try { persistRecord(active) } catch (_: Exception) { }
            }
        }
        val engineAvailable = runtimeInstalled && executable.isFile && executable.canExecute()
        val probe = cachedProbe
        return JSONObject().put("ok", true).put("installed", engineAvailable)
            .put("installing", installing).put("error", installError ?: JSONObject.NULL)
            .put("running", active != null).put("active_model_id", active?.alias ?: JSONObject.NULL)
            .put("port", active?.port ?: JSONObject.NULL).put("healthy", active?.healthy ?: false)
            .put("termux_installed", runtimeInstalled).put("engine_available", engineAvailable)
            .put("install_state", if (installing) "running" else installStage)
            .put("install_error", installError ?: JSONObject.NULL).put("install_exit_code", installExitCode ?: JSONObject.NULL)
            .put("engine_version", installVersion ?: JSONObject.NULL)
            .put("context_size", active?.contextSize?.takeIf { it > 0 } ?: JSONObject.NULL)
            .put("threads", active?.threads?.takeIf { it > 0 } ?: JSONObject.NULL)
            .put("backend", active?.backend ?: "cpu")
            .put("backends", probe?.let { probeJson(it) } ?: JSONObject.NULL)
            .put("install_log_limited", true).put("server", serverJson(active))
    }

    private fun probeJson(probe: EngineProbe): JSONObject = JSONObject()
        .put("available", probe.available)
        .put("flags", JSONArray(probe.flags.sorted()))
        .put("devices", JSONArray().also { array ->
            probe.devices.forEach { device -> array.put(JSONObject().put("id", device.first).put("name", device.second).put("kind", device.third)) }
        })
        .put("cpu", JSONObject().put("available", probe.available))
        .put("gpu", JSONObject().put("available", probe.gpuDevices.isNotEmpty()).put("device", probe.gpuDevices.firstOrNull()?.first ?: JSONObject.NULL))
        .put("npu", JSONObject().put("available", probe.npuDevices.isNotEmpty()).put("device", probe.npuDevices.firstOrNull()?.first ?: JSONObject.NULL))
        .put("error", probe.error ?: JSONObject.NULL)

    /** Enumerates the installed engine's devices and advertised flags, cached briefly. */
    @JvmStatic fun localModelBackends(): String {
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        return try { JSONObject().put("ok", true).put("engine", "llama.cpp").put("probe", probeJson(engineProbe())).toString() }
        catch (failure: Exception) { bridgeError("backend_probe_failed", failure.message ?: "Could not probe llama.cpp backends") }
    }

    private fun engineProbe(force: Boolean = false): EngineProbe {
        val fresh = cachedProbe
        if (!force && fresh != null && SystemClock.elapsedRealtime() - cachedProbeAt < PROBE_TTL_MS) return fresh
        synchronized(probeLock) {
            val current = cachedProbe
            if (!force && current != null && SystemClock.elapsedRealtime() - cachedProbeAt < PROBE_TTL_MS) return current
            val executable = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
            val probe = if (!executable.isFile || !executable.canExecute()) {
                EngineProbe(false, emptySet(), emptyList(), "", "llama-server 尚未安装")
            } else {
                val help = runEngine(listOf("--help"), 8000L)
                val devicesText = runEngine(listOf("--list-devices"), 8000L)
                val flags = mutableSetOf<String>()
                if (help.contains("--n-gpu-layers") || help.contains("-ngl,")) flags.add("n-gpu-layers")
                if (help.contains("--device") || help.contains("-dev,")) flags.add("device")
                if (help.contains("--prio")) flags.add("prio")
                if (help.contains("--no-mmap")) flags.add("no-mmap")
                if (help.contains("--mlock")) flags.add("mlock")
                if (help.contains("--threads")) flags.add("threads")
                // Optional flags are only passed when the binary advertises them: an unknown
                // argument makes llama-server exit before it can bind the port.
                if (help.contains("--no-webui")) flags.add("no-webui")
                if (help.contains("--parallel")) flags.add("parallel")
                if (help.contains("--alias")) flags.add("alias")
                val devices = parseDevices(devicesText.ifBlank { help })
                val ok = help.isNotBlank() || devicesText.isNotBlank()
                EngineProbe(ok, flags, devices, devicesText, if (ok) null else "llama-server 未能输出能力信息")
            }
            cachedProbe = probe
            cachedProbeAt = SystemClock.elapsedRealtime()
            return probe
        }
    }

    private fun parseDevices(text: String): List<Triple<String, String, String>> = EngineDevices.parse(text)

    private fun runEngine(arguments: List<String>, timeoutMs: Long): String {
        val executable = File(RuntimeEnvironment.PREFIX, "bin/llama-server")
        if (!executable.isFile || !executable.canExecute()) return ""
        val process = try {
            val builder = ProcessBuilder(listOf(executable.absolutePath) + arguments)
            builder.environment().clear()
            builder.environment().putAll(RuntimeEnvironment.environment("termux"))
            builder.directory(File(RuntimeEnvironment.HOME))
            builder.redirectErrorStream(true)
            builder.start()
        } catch (_: Exception) { return "" }
        val builder = StringBuilder()
        val reader = Thread({
            try {
                process.inputStream.bufferedReader().use { stream ->
                    val buffer = CharArray(4096)
                    while (builder.length < 128 * 1024) {
                        val count = stream.read(buffer)
                        if (count < 0) break
                        builder.append(buffer, 0, count)
                    }
                }
            } catch (_: Exception) { }
        }, "local-model-probe-io")
        reader.isDaemon = true
        try { process.outputStream.close() } catch (_: Exception) { }
        reader.start()
        try {
            if (!process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)) process.destroyForcibly()
        } catch (_: Exception) {
            try { process.destroyForcibly() } catch (_: Exception) { }
        }
        try { reader.join(400L) } catch (_: Exception) { }
        return builder.toString()
    }


    private fun serverJson(record: ServerRecord?): JSONObject = JSONObject()
        .put("running", record != null).put("healthy", record?.healthy ?: false)
        .put("alias", record?.alias ?: JSONObject.NULL).put("port", record?.port ?: JSONObject.NULL)
        .put("model_name", record?.modelName ?: JSONObject.NULL)
        .put("context_size", record?.contextSize?.takeIf { it > 0 } ?: JSONObject.NULL)
        .put("threads", record?.threads?.takeIf { it > 0 } ?: JSONObject.NULL)
        .put("backend", record?.backend ?: "cpu")

    private fun validateModel(raw: String): File {
        require(raw.isNotEmpty() && '\u0000' !in raw)
        val filesRoot = app.filesDir.canonicalFile
        val root = File(filesRoot, "agent/data/models").canonicalFile
        require(root.isDirectory && root.path.startsWith(filesRoot.path + File.separator))
        val model = File(raw).canonicalFile
        require(model.path.startsWith(root.path + File.separator))
        require(model.name.endsWith(".gguf") && model.isFile && model.canRead())
        return model
    }

    private fun privateDirectory(): File {
        val filesRoot = app.filesDir.canonicalFile
        val directory = File(filesRoot, "local-model-runtime")
        if (directory.exists()) require(directory.isDirectory && directory.canonicalFile == directory.absoluteFile)
        else check(directory.mkdir() || directory.isDirectory) { "cannot create private runtime directory" }
        require(directory.canonicalFile == directory.absoluteFile)
        Os.chmod(directory.path, 448)
        return directory
    }

    private fun privateFile(name: String): File {
        require(name == "server.log" || name == "install.log" || name == "server.json" || name == "server.json.tmp")
        val directory = privateDirectory()
        val file = File(directory, name)
        if (file.exists()) require(file.isFile && file.canonicalFile == file.absoluteFile)
        return file
    }

    private fun drainToLog(inputs: List<java.io.InputStream>, sink: BoundedLog, threadPrefix: String) {
        val remaining = AtomicInteger(inputs.size)
        for ((index, input) in inputs.withIndex()) {
            Thread({
                try {
                    input.use { stream ->
                        val buffer = ByteArray(8192)
                        while (true) {
                            val count = stream.read(buffer)
                            if (count < 0) break
                            sink.append(buffer, 0, count)
                        }
                    }
                } catch (_: Exception) {
                } finally {
                    if (remaining.decrementAndGet() == 0) sink.close()
                }
            }, "${threadPrefix}-${index}").apply { isDaemon = true; start() }
        }
    }

    private fun matchingDirectChildPids(digest: String, parentPid: Int): Set<Int> {
        val result = mutableSetOf<Int>()
        val root = File("/proc")
        val entries = root.listFiles() ?: return result
        for (entry in entries) {
            val pid = entry.name.toIntOrNull() ?: continue
            if (pid <= 1 || procOwnerUid(pid) != android.os.Process.myUid() || procParentPid(pid) != parentPid) continue
            if (procCommandDigest(pid) == digest) result.add(pid)
        }
        return result
    }

    private fun awaitNewChildProcess(digest: String, parentPid: Int, initial: Set<Int>, process: Process): Pair<Int, String>? {
        val deadline = android.os.SystemClock.elapsedRealtime() + 750L
        while (android.os.SystemClock.elapsedRealtime() < deadline && process.isAlive) {
            val entries = File("/proc").listFiles() ?: return null
            for (entry in entries) {
                val pid = entry.name.toIntOrNull() ?: continue
                if (pid <= 1 || pid in initial || procOwnerUid(pid) != android.os.Process.myUid() || procParentPid(pid) != parentPid) continue
                if (procCommandDigest(pid) != digest) continue
                val ticks = procStartTicks(pid) ?: continue
                if (procParentPid(pid) == parentPid && procCommandDigest(pid) == digest && procStartTicks(pid) == ticks) return pid to ticks
            }
            Thread.sleep(20L)
        }
        return null
    }

    private fun procParentPid(pid: Int): Int? = try {
        if (pid <= 1) null else {
            val stat = File("/proc/" + pid + "/stat").readText(Charsets.US_ASCII)
            val end = stat.lastIndexOf(')')
            if (end < 0) null else stat.substring(end + 1).trim().split(Regex("\\s+")).getOrNull(1)?.toIntOrNull()
        }
    } catch (_: Exception) { null }

    private fun awaitReady(record: ServerRecord): Boolean {
        val deadline = android.os.SystemClock.elapsedRealtime() + READY_WAIT_MS
        while (android.os.SystemClock.elapsedRealtime() < deadline) {
            if (!isExactProcess(record)) return false
            if (quickHealth(record)) return true
            Thread.sleep(120L)
        }
        return false
    }

    private fun quickHealth(record: ServerRecord): Boolean {
        if (!isExactProcess(record)) return false
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress("127.0.0.1", record.port), 180)
                socket.soTimeout = 180
                socket.getOutputStream().write("GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".toByteArray(Charsets.US_ASCII))
                val line = StringBuilder()
                while (line.length < 96) {
                    val next = socket.getInputStream().read()
                    if (next < 0 || next == 10) break
                    if (next != 13) line.append(next.toChar())
                }
                val fields = line.toString().split(' ')
                fields.size >= 2 && fields[0].startsWith("HTTP/") && fields[1] == "200"
            }
        } catch (_: Exception) { false }
    }

    private fun commandDigest(argv: List<String>): String {
        val digest = MessageDigest.getInstance("SHA-256")
        for (arg in argv) {
            digest.update(arg.toByteArray(Charsets.UTF_8))
            digest.update(0.toByte())
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun procStartTicks(pid: Int): String? {
        return try {
            if (pid <= 1) null else {
                val stat = File("/proc/" + pid + "/stat").readText(Charsets.US_ASCII)
                val end = stat.lastIndexOf(')')
                if (end < 0) null else {
                    val fields = stat.substring(end + 1).trim().split(Regex("\\s+"))
                    if (fields.size <= 19 || fields[0].isEmpty()) null else fields[19].takeIf { it.toLongOrNull() != null }
                }
            }
        } catch (_: Exception) { null }
    }

    private fun procCommandDigest(pid: Int): String? {
        return try {
            if (pid <= 1) null else {
                val bytes = File("/proc/" + pid + "/cmdline").readBytes()
                if (bytes.isEmpty() || bytes.last() != 0.toByte()) null else {
                    val args = bytes.toString(Charsets.UTF_8).split('\u0000').dropLastWhile { it.isEmpty() }
                    if (args.isEmpty()) null else commandDigest(args)
                }
            }
        } catch (_: Exception) { null }
    }

    private fun procOwnerUid(pid: Int): Int? = try {
        if (pid <= 1) null else Os.stat("/proc/" + pid).st_uid
    } catch (_: Exception) { null }

    private fun isExactProcess(record: ServerRecord): Boolean =
        procOwnerUid(record.pid) == android.os.Process.myUid() &&
            procStartTicks(record.pid) == record.startTicks && procCommandDigest(record.pid) == record.commandDigest

    private fun signalIfExact(record: ServerRecord, signal: Int) {
        if (isExactProcess(record)) Os.kill(record.pid, signal)
    }

    private fun persistRecord(record: ServerRecord) {
        val target = privateFile("server.json")
        val temporary = privateFile("server.json.tmp")
        val json = JSONObject().put("pid", record.pid).put("start_ticks", record.startTicks)
            .put("command_digest", record.commandDigest).put("alias", record.alias).put("port", record.port)
            .put("model_name", record.modelName).put("healthy", record.healthy)
            .put("context_size", record.contextSize).put("threads", record.threads).put("backend", record.backend)
        FileOutputStream(temporary, false).use { output ->
            output.write(json.toString().toByteArray(Charsets.UTF_8))
            output.fd.sync()
        }
        Os.chmod(temporary.path, 384)
        check(temporary.renameTo(target)) { "cannot publish private process identity" }
        Os.chmod(target.path, 384)
    }

    private fun loadPersistedRecord(): ServerRecord? {
        val file = try { privateFile("server.json") } catch (_: Exception) { return null }
        if (!file.isFile) return null
        return try {
            val json = JSONObject(file.readText(Charsets.UTF_8))
            val pid = json.getInt("pid")
            val ticks = json.getString("start_ticks")
            val digest = json.getString("command_digest")
            val alias = json.getString("alias")
            val port = json.getInt("port")
            val modelName = json.getString("model_name")
            require(pid > 1 && ticks.toLongOrNull() != null && digest.matches(Regex("[0-9a-f]{64}")))
            require(aliasPattern.matches(alias) && port in 18000..18999 && modelName.endsWith(".gguf") && File(modelName).name == modelName)
            ServerRecord(pid, ticks, digest, alias, port, modelName, json.optBoolean("healthy", false), null,
                json.optInt("context_size", 0), json.optInt("threads", 0), json.optString("backend", "cpu").take(64))
        } catch (_: Exception) { clearPersistedRecord(); null }
    }

    private fun currentServerLocked(): ServerRecord? {
        val record = serverRecord ?: loadPersistedRecord() ?: return null
        if (isExactProcess(record)) {
            if (serverRecord == null) serverRecord = record
            return record
        }
        if (serverRecord?.pid == record.pid) serverRecord = null
        clearPersistedRecord()
        return null
    }

    private fun clearPersistedRecord() {
        try { privateFile("server.json").takeIf { it.exists() && it.isFile }?.delete() } catch (_: Exception) { }
        try { privateFile("server.json.tmp").takeIf { it.exists() && it.isFile }?.delete() } catch (_: Exception) { }
    }
}
