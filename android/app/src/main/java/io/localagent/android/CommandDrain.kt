package io.localagent.android

/**
 * Bounded drain for the streaming command protocol.
 *
 * Kept free of org.json so the sync/streaming compatibility layer can be unit
 * tested on the JVM: the bridge parses poll chunks and hands plain tuples here.
 */
internal data class DrainedOutput(val after: Int, val retained: Int, val truncated: Boolean)

internal object CommandDrain {
    /** Same retention cap the native process buffer uses for the streaming API. */
    const val LIMIT_BYTES = 1024 * 1024

    fun accept(
        after: Int,
        chunks: List<Triple<Int, String, String>>,
        stdout: StringBuilder,
        stderr: StringBuilder,
        retained: Int,
        truncated: Boolean,
    ): DrainedOutput {
        var cursor = after
        var kept = retained
        var cut = truncated
        for ((seq, stream, text) in chunks) {
            if (seq <= cursor) continue
            cursor = seq
            if (text.isEmpty()) continue
            val bytes = text.toByteArray(Charsets.UTF_8).size
            if (kept + bytes > LIMIT_BYTES) {
                cut = true
                continue
            }
            kept += bytes
            if (stream == "stderr") stderr.append(text) else stdout.append(text)
        }
        return DrainedOutput(cursor, kept, cut)
    }
}
