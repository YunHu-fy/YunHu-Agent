package io.localagent.android

import android.os.SystemClock
import android.system.Os
import android.system.OsConstants
import java.io.InputStream
import java.io.InputStreamReader
import java.util.ArrayDeque
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject

/** Independent process groups, concurrent drains, bounded retained text and a bounded event ring. */
internal object DeviceProcess {
    private const val CAP = 1024 * 1024
    private const val EVENT_CAP = 256 * 1024
    private const val MAX_RECORDS = 16
    private const val MAX_ACTIVE = 4
    private val records = ConcurrentHashMap<String, Record>()
    private val worker = Executors.newFixedThreadPool(MAX_ACTIVE) { task -> Thread(task, "native-command").apply { isDaemon = true } }
    private val io = Executors.newCachedThreadPool { task -> Thread(task, "native-command-io").apply { isDaemon = true } }
    private val scheduler = Executors.newSingleThreadScheduledExecutor { task -> Thread(task, "native-command-kill").apply { isDaemon = true } }
    private data class Event(val seq: Int, val stream: String, val text: String, val bytes: Int)
    private class Record(val request: CommandRequest) {
        val started = SystemClock.elapsedRealtime()
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        val events = ArrayDeque<Event>()
        var retained = 0
        var eventBytes = 0
        var sequence = 0
        var truncated = false
        @Volatile var done = false
        @Volatile var status = "running"
        @Volatile var stopReason: String? = null
        @Volatile var process: Process? = null
        @Volatile var pid = 0
        @Volatile var groupIdentity: String? = null
        var pidLine = StringBuilder()
        var pidRead = false
        var signal: ((Int, Int, String?) -> Unit)? = null
        var exitCode = -1
        var duration = 0L
    }

    @Synchronized fun start(request: CommandRequest, argv: List<String>, environment: Map<String, String>, cwd: String?, signal: ((Int, Int, String?) -> Unit)? = null): String {
        if (records.containsKey(request.id)) return bridgeError("duplicate_id", "Command id already exists; use a new id.")
        if (records.values.count { !it.done } >= MAX_ACTIVE) return bridgeError("busy", "At most four native commands may run concurrently.")
        while (records.size >= MAX_RECORDS) {
            val oldest = records.values.filter { it.done }.minByOrNull { it.started } ?: break
            records.remove(oldest.request.id, oldest)
        }
        val record = Record(request)
        record.signal = signal
        records[request.id] = record
        worker.execute { execute(record, argv, environment, cwd) }
        return JSONObject().put("ok", true).put("id", request.id).toString()
    }

    private fun emit(record: Record, stream: String, text: String) = synchronized(record) {
        val bytes = text.toByteArray(Charsets.UTF_8).size
        var retainedText = text
        if (record.retained + bytes > CAP) {
            val room = CAP - record.retained
            var end = 0
            var used = 0
            while (end < text.length) {
                val cp = text.codePointAt(end)
                val width = String(Character.toChars(cp)).toByteArray(Charsets.UTF_8).size
                if (used + width > room) break
                used += width
                end += Character.charCount(cp)
            }
            retainedText = text.substring(0, end)
            record.truncated = true
        }
        if (retainedText.isNotEmpty()) {
            (if (stream == "stdout") record.stdout else record.stderr).append(retainedText)
            record.retained += retainedText.toByteArray(Charsets.UTF_8).size
        }
        // Stream events continue even after the retained-result cap is reached.
        record.sequence++
        record.events.addLast(Event(record.sequence, stream, text, bytes))
        record.eventBytes += bytes
        while (record.eventBytes > EVENT_CAP || record.events.size > 256) record.eventBytes -= record.events.removeFirst().bytes
    }

    private fun drain(record: Record, stream: String, input: InputStream) {
        try {
            InputStreamReader(input, Charsets.UTF_8).use { reader ->
                val buffer = CharArray(2048)
                var pending = ""
                while (true) {
                    val count = reader.read(buffer)
                    if (count < 0) break
                    var text = pending + String(buffer, 0, count)
                    pending = if (text.isNotEmpty() && Character.isHighSurrogate(text.last())) text.takeLast(1) else ""
                    if (pending.isNotEmpty()) text = text.dropLast(1)
                    if (text.isNotEmpty()) {
                        if (stream == "stderr" && !record.pidRead) {
                            record.pidLine.append(text)
                            val lineEnd = record.pidLine.indexOf("\n")
                            if (lineEnd >= 0 || record.pidLine.length > 256) {
                                record.pidRead = true
                                val first = if (lineEnd >= 0) record.pidLine.substring(0, lineEnd) else record.pidLine.toString()
                                val prefix = "__AGENT_GROUP_" + record.request.id + ":"
                                val identity = first.removePrefix(prefix).trim().split(':')
                                val pid = identity.firstOrNull()?.toIntOrNull()
                                if (first.startsWith(prefix) && pid != null && pid > 1 && identity.size == 2 && identity[1].toLongOrNull() != null) {
                                    record.pid = pid
                                    record.groupIdentity = identity[1]
                                    if (lineEnd >= 0 && lineEnd + 1 < record.pidLine.length) emit(record, stream, record.pidLine.substring(lineEnd + 1))
                                } else emit(record, stream, record.pidLine.toString())
                                record.pidLine.clear()
                            }
                        } else emit(record, stream, text)
                    }
                }
                if (stream == "stderr" && record.pidLine.isNotEmpty()) { emit(record, stream, record.pidLine.toString()); record.pidLine.clear() }
                if (pending.isNotEmpty()) emit(record, stream, "\uFFFD")
            }
        } catch (_: Exception) { /* Cancellation or inherited child descriptors can close a drain. */ }
    }

    private fun execute(record: Record, argv: List<String>, environment: Map<String, String>, cwd: String?) {
        var process: Process? = null
        try {
            if (record.stopReason != null) return
            val builder = ProcessBuilder(argv)
            builder.environment().clear()
            builder.environment().putAll(environment)
            if (cwd != null) builder.directory(java.io.File(cwd))
            process = builder.start()
            record.process = process
            process.outputStream.close()
            val out = io.submit { drain(record, "stdout", process.inputStream) }
            val err = io.submit { drain(record, "stderr", process.errorStream) }
            val deadline = record.started + record.request.timeoutSeconds * 1000
            while (process.isAlive) {
                if (record.stopReason == null && SystemClock.elapsedRealtime() >= deadline) record.stopReason = "timed_out"
                if (record.stopReason != null) { terminate(record); break }
                process.waitFor(50, TimeUnit.MILLISECONDS)
            }
            if (process.waitFor(1500, TimeUnit.MILLISECONDS)) record.exitCode = process.exitValue()
            else terminate(record)
            // Detached grandchildren may hold a pipe open: never block completion forever.
            try { out.get(750, TimeUnit.MILLISECONDS) } catch (_: Exception) { process.inputStream.close(); out.cancel(true) }
            try { err.get(750, TimeUnit.MILLISECONDS) } catch (_: Exception) { process.errorStream.close(); err.cancel(true) }
            record.status = record.stopReason ?: if (record.exitCode == 0) "succeeded" else "failed"
        } catch (failure: Exception) {
            emit(record, "stderr", "Native execution failed: "+(failure.message ?: failure.javaClass.simpleName)+"\n")
            record.status = record.stopReason ?: "failed"
        } finally {
            if (record.stopReason != null) record.status = record.stopReason!!
            if (record.status == "running") record.status = "cancelled"
            if (process?.isAlive == true) terminate(record)
            synchronized(record) {
                record.duration = SystemClock.elapsedRealtime() - record.started
                record.done = true
            }
        }
    }

    private fun terminate(record: Record) {
        val process = record.process ?: return
        val pid = record.pid
        if (pid > 1) try {
            // The launcher uses setsid. Never signal an inherited application process group.
            if (record.signal != null) record.signal!!.invoke(pid, OsConstants.SIGTERM, record.groupIdentity) else if (record.groupIdentity != null && ProcessGroups.identity(pid) == record.groupIdentity) Os.kill(-pid, OsConstants.SIGTERM)
        } catch (_: Exception) { }
        try { process.destroy() } catch (_: Exception) { }
        scheduler.schedule({
            if (pid > 1) try { if (record.signal != null) record.signal!!.invoke(pid, OsConstants.SIGKILL, record.groupIdentity) else if (record.groupIdentity != null && ProcessGroups.identity(pid) == record.groupIdentity) Os.kill(-pid, OsConstants.SIGKILL) } catch (_: Exception) { }
            try { if (process.isAlive) process.destroyForcibly() } catch (_: Exception) { }
        }, 500, TimeUnit.MILLISECONDS)
    }

    fun poll(id: String, after: Int, includeResult: Boolean = true, maxEvents: Int = 256): String {
        if (after < 0) return bridgeError("invalid_cursor", "after must be nonnegative")
        val record = records[id] ?: return bridgeError("unknown_command", "Unknown or expired command id")
        return synchronized(record) {
            val events = JSONArray()
            record.events.filter { it.seq > after }.take(maxEvents).forEach { events.put(JSONObject().put("seq", it.seq).put("stream", it.stream).put("text", it.text)) }
            val served = if (events.length() > 0) events.getJSONObject(events.length() - 1).getInt("seq") else after.coerceAtLeast(record.sequence)
            val body = JSONObject().put("ok", true).put("id", id).put("chunks", events).put("done", StreamCursor.done(record.done, served, record.sequence))
                .put("next_seq", served).put("last_seq", record.sequence).put("more", StreamCursor.more(served, record.sequence))
                .put("first_seq", record.events.peekFirst()?.seq ?: record.sequence + 1)
                .put("events_lost", after < (record.events.peekFirst()?.seq ?: 1) - 1)
            if (record.done && includeResult) body.put("result", JSONObject().put("stdout", record.stdout.toString())
                .put("stderr", record.stderr.toString()).put("exit_code", record.exitCode).put("status", record.status)
                .put("truncated", record.truncated).put("duration_ms", record.duration))
            body.toString()
        }
    }

    // Binder transports bounded slices; the main process reconstructs the full <=1 MiB result.
    fun resultSlice(id: String, stream: String, offset: Int): String {
        val record = records[id] ?: return bridgeError("unknown_command", "Unknown command")
        require(stream == "stdout" || stream == "stderr")
        return synchronized(record) {
            val text = (if (stream == "stdout") record.stdout else record.stderr).toString()
            require(offset in 0..text.length)
            var end = minOf(text.length, offset + 32768)
            if (end < text.length && end > offset && Character.isHighSurrogate(text[end - 1])) end--
            JSONObject().put("ok", true).put("text", text.substring(offset, end)).put("next", end).put("done", end == text.length)
                .put("exit_code", record.exitCode).put("status", record.status).put("truncated", record.truncated).put("duration_ms", record.duration).toString()
        }
    }

    fun cancel(id: String): String {
        val record = records[id] ?: return bridgeError("unknown_command", "Unknown or expired command id")
        synchronized(record) { if (!record.done && record.stopReason == null) record.stopReason = "cancelled" }
        if (!record.done) terminate(record)
        return JSONObject().put("ok", true).put("id", id).put("cancelled", !record.done).toString()
    }

    fun cancelAll() { records.keys.toList().forEach { cancel(it) } }
    fun activeCount() = records.values.count { !it.done }
}
