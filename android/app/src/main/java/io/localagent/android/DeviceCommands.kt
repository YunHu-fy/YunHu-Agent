package io.localagent.android

import java.util.UUID
import org.json.JSONObject

/** Shell text is intentionally unrestricted. Validation bounds the request, not its authority. */
internal data class CommandRequest(
    val id: String, val command: String, val channel: String, val runtime: String,
    val cwd: String?, val timeoutSeconds: Long, val environment: Map<String, String>
)

internal object DeviceCommands {
    fun quote(value: String): String = "'" + value.replace("'", "'\"'\"'") + "'"

    fun parse(json: String): CommandRequest {
        require(json.toByteArray(Charsets.UTF_8).size <= 192 * 1024) { "Request exceeds 192 KiB" }
        val body = JSONObject(json)
        fun string(key: String, default: String? = null): String {
            if (!body.has(key) && default != null) return default
            require(body.get(key) is String) { "$key must be a string" }
            return body.getString(key)
        }
        val id = string("id", UUID.randomUUID().toString())
        require(Regex("[A-Za-z0-9_.:-]{1,128}").matches(id)) { "Invalid command id" }
        val command = string("command")
        require(command.isNotBlank() && '\u0000' !in command && command.toByteArray().size <= 128 * 1024) { "Invalid or oversized shell text" }
        val channel = string("channel", "normal")
        require(channel in setOf("normal", "root", "shizuku")) { "Invalid channel" }
        val runtime = string("runtime", "system")
        require(runtime in setOf("system", "termux")) { "Invalid runtime" }
        val cwd = if (!body.has("cwd") || body.isNull("cwd")) null else string("cwd").also {
            require(it.startsWith("/") && it.length <= 4096 && '\u0000' !in it) { "cwd must be an absolute path" }
        }
        val timeout = if (body.has("timeout_seconds")) {
            val number = body.get("timeout_seconds")
            require(number is Int || number is Long) { "timeout_seconds must be an integer" }
            (number as Number).toLong()
        } else 60L
        require(timeout in 1..86400) { "timeout_seconds must be in 1..86400" }
        val environment = mutableMapOf<String, String>()
        if (body.has("environment") && !body.isNull("environment")) {
            require(body.get("environment") is JSONObject) { "environment must be an object" }
            val env = body.getJSONObject("environment")
            require(env.length() <= 128) { "Too many environment variables" }
            var bytes = 0
            for (key in env.keys()) {
                require(Regex("[A-Za-z_][A-Za-z0-9_]{0,127}").matches(key) && env.get(key) is String) { "Invalid environment entry" }
                val value = env.getString(key)
                require('\u0000' !in value) { "NUL in environment" }
                bytes += key.toByteArray().size + value.toByteArray().size
                require(bytes <= 64 * 1024) { "Environment exceeds 64 KiB" }
                environment[key] = value
            }
        }
        return CommandRequest(id, command, channel, runtime, cwd, timeout, environment)
    }
}

internal fun bridgeError(code: String, message: String): String = JSONObject()
    .put("ok", false).put("error", JSONObject().put("code", code).put("message", message)).toString()
