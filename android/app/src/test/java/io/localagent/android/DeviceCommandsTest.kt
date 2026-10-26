package io.localagent.android

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DeviceCommandsTest {
    @Test fun acceptsGeneralShellWithoutAllowlist() {
        val script = "for i in 1 2; do echo \"${"$"}i; done; /system/bin/settings get system screen_brightness"
        val request = DeviceCommands.parse(JSONObject().put("id", "task-1").put("command", script).put("channel", "root").put("runtime", "system").toString())
        assertEquals(script, request.command)
        assertEquals("root", request.channel)
    }
    @Test fun preservesShellSyntaxRatherThanFilteringMetacharacters() {
        for (script in listOf("echo hello | sed s/h/H/", "echo 'a;b' && printf '%s' \"${"$"}(id)\"", "pkg install git", "setenforce 0", "echo ☃")) {
            assertEquals(script, DeviceCommands.parse(JSONObject().put("command", script).toString()).command)
        }
    }
    @Test fun quotesNestedCommandsLosslessly() {
        assertEquals("'hello world'", DeviceCommands.quote("hello world"))
        assertEquals("'a'\"'\"'b'", DeviceCommands.quote("a'b"))
        assertEquals("''", DeviceCommands.quote(""))
    }
    @Test fun rejectsInvalidStructuralFields() {
        for (body in listOf(
            JSONObject().put("command", ""), JSONObject().put("command", 4),
            JSONObject().put("command", "id").put("channel", "auto"),
            JSONObject().put("command", "id").put("runtime", "external"),
            JSONObject().put("command", "id").put("cwd", "../tmp"),
            JSONObject().put("command", "id").put("timeout_seconds", 0),
            JSONObject().put("command", "id").put("timeout_seconds", 86401),
            JSONObject().put("command", "id").put("timeout_seconds", 1.5),
            JSONObject().put("command", "id").put("id", "bad/id"),
            JSONObject().put("command", "id").put("environment", JSONObject().put("A;id", "x")),
            JSONObject().put("command", "id").put("environment", JSONObject().put("A", 1)))) {
            assertThrows(IllegalArgumentException::class.java) { DeviceCommands.parse(body.toString()) }
        }
    }
    @Test fun rejectsOversizedRequestsAndNul() {
        assertThrows(IllegalArgumentException::class.java) { DeviceCommands.parse(JSONObject().put("command", "x".repeat(131073)).toString()) }
        assertThrows(IllegalArgumentException::class.java) { DeviceCommands.parse(JSONObject().put("command", "id"+0.toChar()).toString()) }
    }
    @Test fun preservesEnvironmentAndAbsoluteCwd() {
        val request = DeviceCommands.parse(JSONObject().put("command", "echo hi").put("cwd", "/data/local/tmp/a b").put("environment", JSONObject().put("TEST", "a'b;${"$"}x")).put("timeout_seconds", 86400).toString())
        assertEquals("/data/local/tmp/a b", request.cwd)
        assertEquals("a'b;${"$"}x", request.environment["TEST"])
        assertEquals(86400L, request.timeoutSeconds)
    }
}
