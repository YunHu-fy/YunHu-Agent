package io.localagent.android

/**
 * Pure llama.cpp command-line composition and startup-failure diagnosis.
 *
 * The bundled engine is whatever `pkg install llama-cpp` currently ships, so the argv must be
 * derived from the flags the installed binary actually advertises. Passing a flag an older or
 * newer build does not know makes llama-server exit during argument parsing, which used to
 * surface only as "llama-server exited before becoming available".
 */
internal object LocalEngineArgs {
    /** Advertised acceleration surface resolved from `--help` and `--list-devices`. */
    data class Backend(
        val cpu: Boolean = false,
        val gpu: Boolean = false,
        val npu: Boolean = false,
        val lowMemory: Boolean = false,
        val gpuDevice: String? = null,
        val npuDevice: String? = null
    ) {
        val accelerated: Boolean get() = cpu || gpu || npu
    }

    private val argumentRejectionMarkers = listOf(
        "invalid argument", "unknown argument", "unrecognized", "invalid option", "unknown option",
        "error while handling argument", "usage: llama-server"
    )

    /**
     * Builds the server argv. `minimal` keeps only the parameters llama-server has always
     * accepted, so a retry can still start on a build that rejects every optional flag.
     */
    fun build(
        executable: String,
        model: String,
        alias: String,
        port: Int,
        contextSize: Int,
        threads: Int,
        advertised: Set<String>,
        backend: Backend,
        minimal: Boolean = false
    ): List<String> {
        val argv = mutableListOf(
            executable, "--model", model, "--host", "127.0.0.1", "--port", port.toString(),
            "--ctx-size", contextSize.toString(), "--threads", threads.toString(), "--alias", alias
        )
        if (minimal) return argv
        if ("parallel" in advertised) argv.addAll(listOf("--parallel", "1"))
        if ("no-webui" in advertised) argv.add("--no-webui")
        if (backend.gpu || backend.npu) {
            if ("n-gpu-layers" in advertised) argv.addAll(listOf("--n-gpu-layers", "99"))
            val device = if (backend.npu) backend.npuDevice else backend.gpuDevice
            if (device != null && "device" in advertised) argv.addAll(listOf("--device", device))
        }
        if (backend.cpu && "prio" in advertised) argv.addAll(listOf("--prio", "2"))
        if (backend.lowMemory && "no-mmap" in advertised) argv.add("--no-mmap")
        return argv
    }

    /** True when the log shows the binary rejected our arguments rather than failing later. */
    fun rejectedArguments(log: String): Boolean {
        val lowered = log.lowercase()
        return argumentRejectionMarkers.any { it in lowered }
    }

    /** True when the engine reported it is serving, which is the earliest reliable readiness signal. */
    fun listening(log: String): Boolean {
        val lowered = log.lowercase()
        return "server is listening" in lowered || "listening on http" in lowered || "all slots are idle" in lowered
    }

    /**
     * Human-readable cause for a server that died before becoming available. The returned text is
     * shown verbatim in the settings page, so it names the next action instead of the symptom.
     */
    fun diagnose(log: String, exitCode: Int?): String {
        val lowered = log.lowercase()
        val cause = when {
            exitCode == 137 || exitCode == -9 ||
                "out of memory" in lowered || "cannot allocate" in lowered ||
                "bad_alloc" in lowered || "failed to allocate" in lowered ->
                "内存不足：请改用更小的模型、降低上下文长度，或开启 Anima 低内存模式后重试。"
            rejectedArguments(log) ->
                "引擎不接受某个启动参数；已尝试最简参数启动，仍失败请更新 llama.cpp 引擎。"
            "cannot link" in lowered || "shared object" in lowered || ("library" in lowered && "not found" in lowered) ->
                "缺少运行库：llama.cpp 引擎不完整，请先在设置页重新安装引擎。"
            "address already in use" in lowered || ("bind" in lowered && "fail" in lowered) ->
                "本地端口被占用；请先停止旧的推理进程或更换端口。"
            ("load model" in lowered && "fail" in lowered) || "unknown model architecture" in lowered ||
                "invalid magic" in lowered || "unsupported model" in lowered || "failed to load model" in lowered ->
                "模型文件无法被当前引擎加载：请重新下载模型，或更新 llama.cpp 引擎。"
            exitCode != null -> "引擎在就绪前退出（退出码 " + exitCode + "）。"
            else -> "引擎在就绪前退出。"
        }
        val tail = tail(log)
        return if (tail.isEmpty()) cause else cause + " 日志：" + tail
    }

    /** Last meaningful log lines, bounded so the error stays readable in the UI. */
    fun tail(log: String, maxLines: Int = 6, maxChars: Int = 700): String {
        val lines = log.lineSequence().map { it.trim() }.filter { it.isNotEmpty() }.toList()
        if (lines.isEmpty()) return ""
        val picked = lines.takeLast(maxLines).joinToString(" | ")
        return if (picked.length <= maxChars) picked else picked.takeLast(maxChars)
    }
}
