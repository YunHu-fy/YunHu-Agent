package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class NativeSetupPolicyTest {
    @Test fun rootRequestsRootEvenWhenShizukuIsUnavailable() {
        val calls = mutableListOf<String>()
        for (reply in listOf("root_granted", "root_denied", "root_missing")) {
            val result = NativeSetupPolicy.authorize("root", { channel -> calls.add(channel); reply }, { fail("Root must not request Shizuku"); "unreachable" })
            assertEquals(reply, result)
        }
        assertEquals(listOf("root", "root", "root"), calls)
    }
    @Test fun shizukuUsesOnlyShizukuRequest() {
        assertEquals("shizuku", NativeSetupPolicy.authorize("shizuku", { fail("Must not configure Root"); "unreachable" }, { "shizuku" }))
    }
    @Test fun normalNeverRequestsElevatedAuthorization() {
        assertEquals("normal", NativeSetupPolicy.authorize("normal", { assertEquals("normal", it); it }, { fail("Normal must not use Shizuku"); "unreachable" }))
    }
    @Test fun invalidChannelCannotFallThroughToShizuku() {
        try { NativeSetupPolicy.authorize("other", { fail(); "" }, { fail(); "" }); fail() } catch (_: IllegalArgumentException) { }
    }
    @Test fun android17IsAcceptedBySharedCompatibilityPolicy() {
        assertTrue(NativeSetupPolicy.supported(37, listOf("arm64-v8a")))
        assertTrue(NativeSetupPolicy.supported(36, listOf("arm64-v8a")))
        assertTrue(NativeSetupPolicy.supported(29, listOf("arm64-v8a")))
        assertFalse(NativeSetupPolicy.supported(28, listOf("arm64-v8a")))
        assertFalse(NativeSetupPolicy.supported(38, listOf("arm64-v8a")))
        assertFalse(NativeSetupPolicy.supported(36, listOf("x86_64")))
    }
    @Test fun deploymentStagesExplainWorkAndFailure() {
        assertEquals("正在检查系统和可用空间", NativeSetupPolicy.deploymentStage("checking"))
        assertEquals("部署失败", NativeSetupPolicy.deploymentStage("failed"))
        assertEquals("future_stage", NativeSetupPolicy.deploymentStage("future_stage"))
    }
}
