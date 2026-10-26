package io.localagent.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalEngineArgsTest {
    private val base = LocalEngineArgs.Backend()

    private fun build(
        advertised: Set<String> = emptySet(),
        backend: LocalEngineArgs.Backend = base,
        minimal: Boolean = false
    ) = LocalEngineArgs.build(
        "/prefix/bin/llama-server", "/models/m.gguf", "qwen25-05-q4km", 18286, 4096, 4,
        advertised, backend, minimal
    )

    @Test fun optionalFlagsAreOnlyPassedWhenTheBinaryAdvertisesThem() {
        val plain = build()
        assertFalse(plain.contains("--no-webui"))
        assertFalse(plain.contains("--parallel"))
        assertTrue(plain.contains("--model"))
        assertTrue(plain.contains("--ctx-size"))
        assertTrue(plain.contains("--threads"))
        assertTrue(plain.contains("--alias"))

        val full = build(setOf("no-webui", "parallel"))
        assertTrue(full.contains("--no-webui"))
        assertTrue(full.containsAll(listOf("--parallel", "1")))
    }

    @Test fun minimalFallbackDropsEveryOptionalFlag() {
        val argv = build(
            advertised = setOf("no-webui", "parallel", "n-gpu-layers", "device", "prio", "no-mmap"),
            backend = LocalEngineArgs.Backend(cpu = true, gpu = true, lowMemory = true, gpuDevice = "Vulkan0"),
            minimal = true
        )
        assertEquals(
            listOf(
                "/prefix/bin/llama-server", "--model", "/models/m.gguf", "--host", "127.0.0.1",
                "--port", "18286", "--ctx-size", "4096", "--threads", "4", "--alias", "qwen25-05-q4km"
            ),
            argv
        )
    }

    @Test fun accelerationFlagsFollowTheAdvertisedDeviceAndFlags() {
        val gpu = build(
            advertised = setOf("n-gpu-layers", "device"),
            backend = LocalEngineArgs.Backend(gpu = true, gpuDevice = "Vulkan0")
        )
        assertTrue(gpu.containsAll(listOf("--n-gpu-layers", "99")))
        assertTrue(gpu.containsAll(listOf("--device", "Vulkan0")))

        val withoutDeviceFlag = build(
            advertised = setOf("n-gpu-layers"),
            backend = LocalEngineArgs.Backend(gpu = true, gpuDevice = "Vulkan0")
        )
        assertFalse(withoutDeviceFlag.contains("--device"))

        val npu = build(
            advertised = setOf("n-gpu-layers", "device"),
            backend = LocalEngineArgs.Backend(npu = true, npuDevice = "HTP0", gpuDevice = "Vulkan0")
        )
        assertTrue(npu.containsAll(listOf("--device", "HTP0")))
    }

    @Test fun lowMemoryOnlyAddsNoMmapWhenAdvertised() {
        assertTrue(build(setOf("no-mmap"), LocalEngineArgs.Backend(lowMemory = true)).contains("--no-mmap"))
        assertFalse(build(setOf("mlock"), LocalEngineArgs.Backend(lowMemory = true)).contains("--no-mmap"))
    }

    @Test fun argumentRejectionIsRecognisedFromTheLog() {
        assertTrue(LocalEngineArgs.rejectedArguments("error: invalid argument: --no-webui"))
        assertTrue(LocalEngineArgs.rejectedArguments("unknown argument: --parallel"))
        assertFalse(LocalEngineArgs.rejectedArguments("llama_model_load: error loading model"))
    }

    @Test fun diagnoseNamesTheNextActionInsteadOfTheSymptom() {
        assertTrue(LocalEngineArgs.diagnose("", 137).startsWith("内存不足"))
        assertTrue(LocalEngineArgs.diagnose("ggml_backend_cuda_buffer_type_alloc_buffer: failed to allocate", null).startsWith("内存不足"))
        assertTrue(LocalEngineArgs.diagnose("error: invalid argument: --no-webui", 1).startsWith("引擎不接受某个启动参数"))
        assertTrue(LocalEngineArgs.diagnose("CANNOT LINK EXECUTABLE: library \"libc++_shared.so\" not found", 1).startsWith("缺少运行库"))
        assertTrue(LocalEngineArgs.diagnose("bind: Address already in use", 1).startsWith("本地端口被占用"))
        assertTrue(LocalEngineArgs.diagnose("llama_model_load: failed to load model", 1).startsWith("模型文件无法被当前引擎加载"))
    }

    @Test fun diagnoseAppendsABoundedLogTail() {
        val log = (1..40).joinToString("\n") { "line $it" }
        val message = LocalEngineArgs.diagnose(log, null)
        assertTrue(message.contains("日志："))
        assertTrue(message.contains("line 40"))
        assertFalse(message.contains("line 1 "))
        assertTrue(message.length < 900)
    }

    @Test fun emptyLogKeepsTheCauseReadable() {
        assertEquals("引擎在就绪前退出。", LocalEngineArgs.diagnose("   \n\n ", null))
        assertEquals("引擎在就绪前退出（退出码 1）。", LocalEngineArgs.diagnose("", 1))
    }
}
