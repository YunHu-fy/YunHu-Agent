package io.localagent.android

/**
 * Parses the device list printed by `llama-server --list-devices` (or `--help`).
 *
 * Separated from the runtime object so the classification rules can be unit
 * tested on the JVM without touching Android APIs.
 */
internal object EngineDevices {
    // Device ids are a name plus an optional index ("Vulkan0", "HTP0", "CPU0").
    // Underscored log prefixes ("load_backend: ...") must not become devices.
    private val LINE = Regex("^\\s*([A-Za-z][A-Za-z]{0,23}[0-9]{0,3})\\s*:\\s*(.+)$")
    // Report headers and build banners share the "key: value" shape but are not
    // backends.
    private val SKIP = setOf("available", "device", "build", "version", "usage", "options", "note", "example", "default", "main")
    private val NPU = listOf("npu", "qnn", "htp", "hexagon", "nnapi", "neuron", "dsp", "apu", "dla")
    private val GPU = listOf("gpu", "vulkan", "opencl", "cuda", "adreno", "mali", "powervr", "imagination", "angle")
    private const val MAX_DEVICES = 32
    private const val MAX_DESCRIPTION = 160

    fun kind(id: String, description: String): String {
        val text = (id + " " + description).lowercase()
        // NPU is checked first: some SoCs report their accelerator through a
        // Vulkan/QNN pairing where the vendor name would otherwise win.
        if (NPU.any { text.contains(it) }) return "npu"
        if (GPU.any { text.contains(it) }) return "gpu"
        return "cpu"
    }

    fun parse(text: String): List<Triple<String, String, String>> {
        val result = mutableListOf<Triple<String, String, String>>()
        for (line in text.lineSequence()) {
            val match = LINE.find(line) ?: continue
            val id = match.groupValues[1]
            val description = match.groupValues[2].trim().take(MAX_DESCRIPTION)
            if (description.isEmpty()) continue
            if (id.lowercase() in SKIP) continue
            result.add(Triple(id, description, kind(id, description)))
        }
        return result.distinctBy { it.first }.take(MAX_DEVICES)
    }
}
