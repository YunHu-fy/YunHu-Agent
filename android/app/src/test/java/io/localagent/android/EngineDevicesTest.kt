package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class EngineDevicesTest {
    @Test fun parsesAndClassifiesGpuAndNpuDevices() {
        val text = """
            Available devices:
              Vulkan0: Adreno (TM) 740 (8384 MiB, 8384 MiB free)
              CPU0: unknown, fp16: 0
        """.trimIndent()
        val devices = EngineDevices.parse(text)
        assertEquals(2, devices.size)
        assertEquals("Vulkan0", devices[0].first)
        assertEquals("gpu", devices[0].third)
        assertEquals("CPU0", devices[1].first)
        assertEquals("cpu", devices[1].third)
    }

    @Test fun qualcommHexagonIsTreatedAsNpu() {
        assertEquals("npu", EngineDevices.kind("HTP0", "Qualcomm Hexagon NPU"))
        assertEquals("npu", EngineDevices.kind("QNN0", "QNN accelerator"))
        assertEquals("gpu", EngineDevices.kind("OpenCL0", "Mali-G715"))
    }

    @Test fun headerAndDeduplicatedEntriesAreSkipped() {
        val devices = EngineDevices.parse("Available devices:\nDevice 0: something\nVulkan0: A\nVulkan0: B")
        assertEquals(1, devices.size)
        assertEquals("A", devices[0].second)
    }

    @Test fun unrelatedLogLinesAreIgnored() {
        val devices = EngineDevices.parse("load_backend: loaded CPU backend\nbuild: 4891\nVulkan0: Adreno 740")
        assertEquals(1, devices.size)
        assertEquals("gpu", devices[0].third)
    }
}
