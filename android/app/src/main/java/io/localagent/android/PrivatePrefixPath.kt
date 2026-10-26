package io.localagent.android

import java.io.File

/** Compare filesystem objects, not spellings: Android data paths may be bind-mounted aliases. */
internal object PrivatePrefixPath {
    const val FILES = "/data/data/com.termux/files"
    data class Identity(val device: Long, val inode: Long, val uid: Int, val directory: Boolean)
    data class Result(
        val actualPath: String, val expectedPath: String, val ownerUid: Int,
        val actual: Identity?, val expected: Identity?, val failure: String?
    ) {
        val matches get() = failure == null
        fun requireMatch() { check(matches) { failure ?: "私有目录验证失败" } }
    }

    fun publicationSource(actualRoot: File, staging: File): File {
        require(staging.parentFile == actualRoot && staging.name.matches(Regex("\\.agent-stage-[A-Za-z0-9-]+"))) { "Invalid private staging directory" }
        return File(FILES, staging.name)
    }

    fun inspect(actualPath: String, ownerUid: Int, stat: (String) -> Identity): Result {
        var actual: Identity? = null
        var expected: Identity? = null
        var failedPath = actualPath
        val failure = try {
            actual = stat(actualPath)
            failedPath = FILES
            expected = stat(FILES)
            when {
                !actual.directory || !expected.directory -> "应用私有路径不是目录"
                actual.uid != ownerUid || expected.uid != ownerUid -> "私有目录的所属 UID 与应用 UID 不一致"
                actual.device != expected.device || actual.inode != expected.inode -> "固定 Termux 路径未映射到本应用的实际私有目录"
                else -> null
            }
        } catch (failure: Exception) {
            "无法读取私有目录身份：" + failedPath + "（" + failure.javaClass.simpleName + ": " + (failure.message ?: "无详细错误").replace('\n', ' ').replace('\r', ' ').take(256) + "）"
        }
        val detail = failure?.let { it + "；实际目录=" + actualPath + "；固定目录=" + FILES + "。不会覆盖未知环境；请查看路径诊断，不要清除应用数据。" }
        return Result(actualPath, FILES, ownerUid, actual, expected, detail)
    }
}
