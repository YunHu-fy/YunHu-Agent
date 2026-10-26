package io.localagent.android

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.Toast
import androidx.annotation.Keep
import androidx.core.content.FileProvider
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.FilterOutputStream
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.ceil

/**
 * The only JavaScript bridge exposed by the conversation WebView.
 *
 * It accepts a bounded, data-only transcript, draws it with Canvas (never HTML),
 * and hands private-cache images to the Android share sheet through FileProvider.
 */
@Keep
internal class TranscriptShareBridge(
    private val activity: Activity,
    private val webView: WebView,
    private val isConversationReady: () -> Boolean
) {
    companion object {
        const val JS_NAME = "NativeTranscript"

        private const val LOCAL_HOST = "127.0.0.1"
        private const val LOCAL_PORT = 8686
        private const val MAX_JSON_BYTES = 1024 * 1024
        private const val MAX_REQUEST_ID_CHARS = 128
        private const val MAX_MESSAGES = 100
        private const val MAX_TEXT_CHARS = 16_384
        private const val MAX_OUTPUT_PAGES = 100
        private const val MAX_OUTPUT_BYTES = 32L * 1024L * 1024L
        private const val MAX_BITMAP_BYTES = 12L * 1024L * 1024L
        private const val PAGE_WIDTH = 1_440
        private const val PAGE_HEIGHT = 2_048
        private const val PAGE_MARGIN = 96
        private const val CONTENT_TOP = 132
        private const val CONTENT_BOTTOM = PAGE_HEIGHT - 108
        private const val CACHE_ROOT = "transcript-share"
        private const val CACHE_RETENTION_MS = 30L * 60L * 1000L
        private val cleanupHandler = Handler(Looper.getMainLooper())
    }

    private data class TranscriptMessage(val role: String, val text: String)
    private data class RenderedShare(val directory: File, val files: List<File>)

    private class InputRejected : Exception()
    private class OutputRejected : Exception()

    private class BoundedOutputStream(output: OutputStream, private val byteLimit: Long) : FilterOutputStream(output) {
        private var bytesWritten = 0L

        override fun write(value: Int) {
            ensureCapacity(1)
            out.write(value)
            bytesWritten++
        }

        override fun write(buffer: ByteArray, offset: Int, length: Int) {
            if (offset < 0 || length < 0 || offset > buffer.size - length) throw IndexOutOfBoundsException()
            ensureCapacity(length)
            out.write(buffer, offset, length)
            bytesWritten += length.toLong()
        }

        private fun ensureCapacity(length: Int) {
            if (bytesWritten + length.toLong() > byteLimit) throw OutputRejected()
        }
    }

    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { task ->
        Thread(task, "transcript-image-share")
    }
    private val busy = AtomicBoolean(false)

    @Volatile
    private var closed = false

    /** Legacy fire-and-forget entry point retained for existing callers. */
    @JavascriptInterface
    fun shareTranscript(payload: String?) {
        startShare(payload, requestId = null)
    }

    /** Starts sharing and reports the result to the originating WebView document. */
    @JavascriptInterface
    fun shareTranscriptAsync(requestId: String?, payload: String?) {
        if (requestId == null || !isValidRequestId(requestId)) {
            val boundedRequestId = requestId?.takeIf { it.length <= MAX_REQUEST_ID_CHARS }
            dispatchAsyncResult(boundedRequestId, ok = false, error = "invalid_request_id")
            return
        }
        startShare(payload, requestId)
    }

    private fun startShare(payload: String?, requestId: String?) {
        if (closed) {
            reportFailure(requestId, "unavailable")
            return
        }
        val input = payload ?: run {
            reject(requestId, "无法分享：转录数据无效。", "invalid_input")
            return
        }
        // A UTF-16 length guard avoids a second large allocation for obviously
        // oversized input; the UTF-8 check below enforces the byte contract.
        if (input.length > MAX_JSON_BYTES) {
            reject(requestId, "无法分享：转录内容过大。", "payload_too_large")
            return
        }
        val byteCount = try {
            input.toByteArray(StandardCharsets.UTF_8).size
        } catch (_: RuntimeException) {
            reject(requestId, "无法分享：转录数据无效。", "invalid_input")
            return
        } catch (_: OutOfMemoryError) {
            reject(requestId, "无法分享：转录数据无效。", "invalid_input")
            return
        }
        if (byteCount > MAX_JSON_BYTES) {
            reject(requestId, "无法分享：转录内容过大。", "payload_too_large")
            return
        }
        if (!busy.compareAndSet(false, true)) {
            reject(requestId, "正在准备上一份转录图片，请稍候。", "busy")
            return
        }

        // WebView URL access is performed on the UI thread. The bridge method itself
        // is invoked by WebView on a background thread.
        val posted = webView.post {
            if (closed || activity.isFinishing || activity.isDestroyed) {
                busy.set(false)
                reportFailure(requestId, "unavailable")
                return@post
            }
            if (!isConversationReady() || !isAllowedCaller(webView.url)) {
                busy.set(false)
                reject(requestId, "无法分享：页面来源不受信任。", "untrusted_origin")
                return@post
            }
            try {
                worker.execute {
                    var shareDirectory: File? = null
                    try {
                        val messages = parseMessages(input)
                        val share = renderMessages(messages)
                        shareDirectory = share.directory
                        val postedShare = main.post {
                            if (closed || activity.isFinishing || activity.isDestroyed ||
                                !isConversationReady() || !isAllowedCaller(webView.url)
                            ) {
                                share.directory.deleteRecursively()
                                busy.set(false)
                                reportFailure(requestId, "unavailable")
                                return@post
                            }
                            try {
                                launchShare(share.files)
                                scheduleCleanup(share.directory)
                                reportSuccess(requestId)
                            } catch (_: ActivityNotFoundException) {
                                share.directory.deleteRecursively()
                                notifyUser("没有可用的分享应用。")
                                reportFailure(requestId, "share_unavailable")
                            } catch (_: RuntimeException) {
                                share.directory.deleteRecursively()
                                notifyUser("无法打开系统分享面板。")
                                reportFailure(requestId, "share_failed")
                            } finally {
                                busy.set(false)
                            }
                        }
                        if (!postedShare) {
                            share.directory.deleteRecursively()
                            busy.set(false)
                            reportFailure(requestId, "unavailable")
                        }
                    } catch (_: InputRejected) {
                        shareDirectory?.deleteRecursively()
                        busy.set(false)
                        reject(requestId, "无法分享：转录格式或内容长度无效。", "invalid_input")
                    } catch (_: OutputRejected) {
                        shareDirectory?.deleteRecursively()
                        busy.set(false)
                        reject(requestId, "无法分享：转录图片超出大小限制。", "render_failed")
                    } catch (_: OutOfMemoryError) {
                        shareDirectory?.deleteRecursively()
                        busy.set(false)
                        reject(requestId, "无法生成转录图片：设备内存不足。", "render_failed")
                    } catch (_: Exception) {
                        shareDirectory?.deleteRecursively()
                        busy.set(false)
                        reject(requestId, "无法生成转录图片。", "render_failed")
                    }
                }
            } catch (_: RejectedExecutionException) {
                busy.set(false)
                reject(requestId, "无法生成转录图片。", "unavailable")
            }
        }
        if (!posted) {
            busy.set(false)
            reject(requestId, "无法分享：页面已关闭。", "unavailable")
        }
    }

    private fun isValidRequestId(value: String): Boolean =
        value.length in 1..MAX_REQUEST_ID_CHARS && value.all { character ->
            character in 'a'..'z' || character in 'A'..'Z' || character in '0'..'9' ||
                character == '_' || character == '-'
        }

    private fun reject(requestId: String?, message: String, error: String) {
        notifyUser(message)
        reportFailure(requestId, error)
    }

    private fun reportFailure(requestId: String?, error: String) {
        if (requestId != null) dispatchAsyncResult(requestId, ok = false, error = error)
    }

    private fun reportSuccess(requestId: String?) {
        if (requestId != null) dispatchAsyncResult(requestId, ok = true, error = null)
    }

    private fun dispatchAsyncResult(requestId: String?, ok: Boolean, error: String?) {
        val detail = JSONObject()
            .put("requestId", requestId ?: JSONObject.NULL)
            .put("ok", ok)
            .put("error", error ?: JSONObject.NULL)
            .toString()
        val script = "window.dispatchEvent(new CustomEvent('yunhu-transcript-result',{detail:JSON.parse(" +
            JSONObject.quote(detail) + ")}));"
        main.post {
            // Never deliver a result to a navigated, untrusted, or torn-down document.
            if (closed || activity.isFinishing || activity.isDestroyed ||
                !isConversationReady() || !isAllowedCaller(webView.url)
            ) return@post
            try {
                webView.evaluateJavascript(script, null)
            } catch (_: RuntimeException) {
                // The document may have gone away between the checks and evaluation.
            }
        }
    }

    fun close() {
        closed = true
        busy.set(false)
        worker.shutdownNow()
    }

    private fun isAllowedCaller(url: String?): Boolean {
        val uri = try {
            Uri.parse(url ?: return false)
        } catch (_: RuntimeException) {
            return false
        }
        // The runtime launch URL carries its bearer token in a fragment. The
        // fragment is deliberately ignored; credentials and query parameters are
        // rejected while the approved document path remains exactly "/".
        return uri.scheme == "http" && uri.host == LOCAL_HOST && uri.port == LOCAL_PORT &&
            uri.path == "/" && uri.query == null && uri.userInfo == null
    }

    private fun parseMessages(input: String): List<TranscriptMessage> {
        val trimmed = input.trim()
        val array = try {
            when (trimmed.firstOrNull()) {
                '[' -> JSONArray(input)
                '{' -> {
                    val root = JSONObject(input)
                    root.opt("messages") as? JSONArray ?: throw InputRejected()
                }
                else -> throw InputRejected()
            }
        } catch (_: Exception) {
            throw InputRejected()
        }
        if (array.length() !in 1..MAX_MESSAGES) throw InputRejected()

        val messages = ArrayList<TranscriptMessage>(array.length())
        for (index in 0 until array.length()) {
            val item = array.opt(index) as? JSONObject ?: throw InputRejected()
            val role = item.opt("role") as? String ?: throw InputRejected()
            if (role != "user" && role != "assistant") throw InputRejected()
            val value = if (item.has("text")) item.opt("text") else item.opt("content")
            val text = value as? String ?: throw InputRejected()
            if (text.length > MAX_TEXT_CHARS) throw InputRejected()
            messages += TranscriptMessage(role, text)
        }
        return messages
    }

    private fun renderMessages(messages: List<TranscriptMessage>): RenderedShare {
        val root = File(activity.cacheDir, CACHE_ROOT)
        if (!root.exists() && !root.mkdirs()) throw OutputRejected()
        pruneOldShares(root)
        val directory = File(root, "share-${System.currentTimeMillis()}-${UUID.randomUUID()}")
        if (!directory.mkdirs()) throw OutputRejected()
        return try {
            val renderer = PageRenderer(directory)
            messages.forEach { message ->
                if (closed || Thread.currentThread().isInterrupted) throw OutputRejected()
                renderer.addMessage(message)
            }
            RenderedShare(directory, renderer.finish())
        } catch (_: OutOfMemoryError) {
            directory.deleteRecursively()
            throw OutputRejected()
        } catch (failure: Exception) {
            directory.deleteRecursively()
            throw failure
        }
    }

    private fun pruneOldShares(root: File) {
        val cutoff = System.currentTimeMillis() - CACHE_RETENTION_MS
        root.listFiles()?.forEach { child ->
            if (child.isDirectory && child.lastModified() < cutoff) child.deleteRecursively()
        }
    }

    private fun launchShare(files: List<File>) {
        val uris = ArrayList<Uri>(files.size)
        files.forEach { file ->
            uris += FileProvider.getUriForFile(
                activity,
                "${activity.packageName}.fileprovider",
                file
            )
        }
        if (uris.isEmpty()) throw OutputRejected()

        val send = Intent(Intent.ACTION_SEND_MULTIPLE).apply {
            type = "image/png"
            putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            var clip = ClipData.newRawUri("Transcript image", uris.first())
            uris.drop(1).forEach { clip.addItem(ClipData.Item(it)) }
            clipData = clip
        }
        val chooser = Intent.createChooser(send, "分享转录图片").apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        activity.startActivity(chooser)
    }

    private fun scheduleCleanup(directory: File) {
        cleanupHandler.postDelayed({ directory.deleteRecursively() }, CACHE_RETENTION_MS)
    }

    private fun notifyUser(message: String) {
        main.post {
            if (!closed && !activity.isFinishing && !activity.isDestroyed) {
                Toast.makeText(activity, message, Toast.LENGTH_LONG).show()
            }
        }
    }

    private inner class PageRenderer(private val directory: File) {
        private val bodyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(32, 36, 42)
            textSize = 32f
            typeface = Typeface.create("sans-serif", Typeface.NORMAL)
        }
        private val rolePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(37, 89, 117)
            textSize = 28f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        }
        private val headerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(22, 26, 31)
            textSize = 38f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        }
        private val footerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(110, 118, 128)
            textSize = 22f
            typeface = Typeface.create("sans-serif", Typeface.NORMAL)
        }
        private val dividerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(224, 228, 233)
            strokeWidth = 2f
        }
        private val bodyLineHeight = ceil(bodyPaint.fontMetrics.descent - bodyPaint.fontMetrics.ascent + 10f).toInt()
        private val roleLineHeight = ceil(rolePaint.fontMetrics.descent - rolePaint.fontMetrics.ascent + 8f).toInt()
        private var bitmap: Bitmap? = null
        private var canvas: Canvas? = null
        private var cursor = CONTENT_TOP.toFloat()
        private var pageNumber = 0
        private var hasContent = false
        private var totalBytes = 0L
        private val files = ArrayList<File>()

        init {
            startPage()
        }

        fun addMessage(message: TranscriptMessage) {
            val lines = wrapText(message.text)
            val label = if (message.role == "user") "User" else "Assistant"
            if (hasContent && cursor + roleLineHeight + 14f + bodyLineHeight > CONTENT_BOTTOM) {
                finishPage()
                startPage()
            }
            drawRole(label, message.role == "user")
            lines.forEach { line ->
                if (cursor + bodyLineHeight > CONTENT_BOTTOM) {
                    finishPage()
                    startPage()
                    drawRole("$label (continued)", message.role == "user")
                }
                drawBodyLine(line)
            }
            cursor += 18f
        }

        fun finish(): List<File> {
            if (hasContent) finishPage()
            if (files.isEmpty()) throw OutputRejected()
            return files.toList()
        }

        private fun startPage() {
            if (pageNumber >= MAX_OUTPUT_PAGES) throw OutputRejected()
            val bitmapBytes = PAGE_WIDTH.toLong() * PAGE_HEIGHT.toLong() * 4L
            if (bitmapBytes > MAX_BITMAP_BYTES) throw OutputRejected()
            pageNumber++
            bitmap = try {
                Bitmap.createBitmap(PAGE_WIDTH, PAGE_HEIGHT, Bitmap.Config.ARGB_8888)
            } catch (_: OutOfMemoryError) {
                throw OutputRejected()
            }
            canvas = Canvas(requireNotNull(bitmap))
            canvas!!.drawColor(Color.WHITE)
            canvas!!.drawText("Transcript", PAGE_MARGIN.toFloat(), 72f, headerPaint)
            canvas!!.drawLine(
                PAGE_MARGIN.toFloat(), 96f,
                (PAGE_WIDTH - PAGE_MARGIN).toFloat(), 96f,
                dividerPaint
            )
            cursor = CONTENT_TOP.toFloat()
            hasContent = false
        }

        private fun finishPage() {
            val current = bitmap ?: return
            if (!hasContent) {
                current.recycle()
                bitmap = null
                canvas = null
                return
            }
            canvas!!.drawText(
                "Page $pageNumber",
                PAGE_MARGIN.toFloat(),
                (PAGE_HEIGHT - 48).toFloat(),
                footerPaint
            )
            val file = File(directory, "transcript-${pageNumber.toString().padStart(3, '0')}.png")
            try {
                val remainingOutputBytes = MAX_OUTPUT_BYTES - totalBytes
                if (remainingOutputBytes <= 0L) throw OutputRejected()
                val bounded = BoundedOutputStream(FileOutputStream(file), remainingOutputBytes)
                BufferedOutputStream(bounded).use { output ->
                    if (!current.compress(Bitmap.CompressFormat.PNG, 100, output)) throw OutputRejected()
                }
                val bytes = file.length()
                if (bytes <= 0L || totalBytes + bytes > MAX_OUTPUT_BYTES) throw OutputRejected()
                totalBytes += bytes
                files += file
            } finally {
                current.recycle()
                bitmap = null
                canvas = null
            }
        }

        private fun drawRole(label: String, user: Boolean) {
            val c = requireNotNull(canvas)
            rolePaint.color = if (user) Color.rgb(37, 89, 117) else Color.rgb(91, 70, 136)
            c.drawText(label, PAGE_MARGIN.toFloat(), cursor - rolePaint.fontMetrics.ascent, rolePaint)
            cursor += roleLineHeight
            c.drawLine(
                PAGE_MARGIN.toFloat(), cursor + 3f,
                (PAGE_WIDTH - PAGE_MARGIN).toFloat(), cursor + 3f,
                dividerPaint
            )
            cursor += 14f
            hasContent = true
        }

        private fun drawBodyLine(line: String) {
            val c = requireNotNull(canvas)
            c.drawText(line, PAGE_MARGIN.toFloat(), cursor - bodyPaint.fontMetrics.ascent, bodyPaint)
            cursor += bodyLineHeight
        }

        private fun wrapText(raw: String): List<String> {
            val text = normalizeText(raw)
            val result = ArrayList<String>()
            var paragraphStart = 0
            var index = 0
            while (index <= text.length) {
                if (index == text.length || text[index] == '\n') {
                    appendWrappedParagraph(text.substring(paragraphStart, index), result)
                    paragraphStart = index + 1
                }
                index++
            }
            if (result.isEmpty()) result += ""
            return result
        }

        private fun appendWrappedParagraph(paragraph: String, target: MutableList<String>) {
            if (paragraph.isEmpty()) {
                target += ""
                return
            }
            var start = 0
            while (start < paragraph.length) {
                val remaining = paragraph.substring(start)
                var count = bodyPaint.breakText(remaining, true, (PAGE_WIDTH - 2 * PAGE_MARGIN).toFloat(), null)
                if (count <= 0) count = 1
                if (start + count < paragraph.length && count > 1 &&
                    Character.isHighSurrogate(paragraph[start + count - 1]) &&
                    Character.isLowSurrogate(paragraph[start + count])
                ) {
                    count--
                }
                target += remaining.substring(0, count)
                start += count
            }
        }

        private fun normalizeText(raw: String): String {
            val result = StringBuilder(raw.length)
            raw.forEach { character ->
                when {
                    character == '\n' -> result.append('\n')
                    character == '\t' -> result.append("    ")
                    character.code < 0x20 || character.code == 0x7f -> result.append(' ')
                    else -> result.append(character)
                }
            }
            return result.toString()
        }
    }
}
