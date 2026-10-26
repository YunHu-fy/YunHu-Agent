package io.localagent.android

/** Shared stream completion rule: process exit is not completion until the caller drains all retained events. */
internal object StreamCursor {
    fun more(lastServed: Int, lastProduced: Int): Boolean = lastServed < lastProduced
    fun done(processDone: Boolean, lastServed: Int, lastProduced: Int): Boolean = processDone && !more(lastServed, lastProduced)
}
