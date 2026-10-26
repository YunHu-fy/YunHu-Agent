package io.localagent.android

import android.content.Context
import android.os.Build
import android.system.Os
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.SimpleFileVisitor
import java.nio.file.FileVisitResult
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream
import org.json.JSONObject

/** Official ARM64 bootstrap, installed offline into its compiled private prefix. */
internal object TermuxRuntime {
    const val ZIP_SHA256 = "c8d702b6f742935001c37cda81b8ac69504a95d5cf28f2899532dd8cd4b057eb"
    private lateinit var app: Context
    private val worker = Executors.newSingleThreadExecutor { Thread(it, "termux-bootstrap") }
    @Volatile private var installing = false
    @Volatile private var stage = "not_installed"
    @Volatile private var progress = 0
    @Volatile private var error: String? = null
    @Volatile private var pathCheck: String? = null
    private val prefix get() = File(RuntimeEnvironment.PREFIX)
    private val marker get() = File(app.filesDir, ".agent-bootstrap-complete.json")
    private val pending get() = File(app.filesDir, ".agent-bootstrap-pending")
    fun initialize(context: Context) { app = context.applicationContext }
    fun installed(): Boolean = ::app.isInitialized && marker.isFile && File(prefix, "bin/bash").canExecute() && File(prefix, "bin/pkg").isFile && File(prefix, "bin/apt").canExecute()
    @Synchronized fun status(): String = JSONObject().put("ok", true).put("installed", installed()).put("installing", installing)
        .put("progress", if (installed()) 100 else progress).put("stage", if (installed()) "ready" else stage)
        .put("error", error ?: JSONObject.NULL).put("path_check", pathCheck?.let { JSONObject(it) } ?: JSONObject.NULL).put("prefix", RuntimeEnvironment.PREFIX).put("home", RuntimeEnvironment.HOME)
        .put("version", "0.118.3").put("terminal_available", installed()).put("bootstrap_sha256", ZIP_SHA256)
        .put("offline", true).put("supported_sdk_min", NativeSetupPolicy.MIN_SDK).put("supported_sdk_max", NativeSetupPolicy.MAX_SDK).toString()

    @Synchronized fun deploy(): String {
        if (installed() || installing) return status()
        if (!::app.isInitialized) return bridgeError("not_initialized", "Native runtime not initialized")
        installing = true; error = null; pathCheck = null; stage = "checking"; progress = 1
        val install = Runnable {
            var stageDir: File? = null
            try {
                check(app.packageName == "com.termux") { "Official binaries require applicationId com.termux" }
                check(NativeSetupPolicy.supported(Build.VERSION.SDK_INT, Build.SUPPORTED_ABIS.toList())) { "支持 Android 10–17（API 29–37）的 ARM64 设备。" }
                check(Build.SUPPORTED_ABIS.contains("arm64-v8a")) { "ARM64 device required" }
                check(android.os.Process.myUid() / 100000 == 0) { "Official bootstrap requires Android primary user; work profiles and secondary users are unsupported" }
                val directoryCheck = RuntimeEnvironment.privatePrefixCheck()
                pathCheck = RuntimeEnvironment.privatePrefixDiagnostics(directoryCheck).toString()
                directoryCheck.requireMatch()
                check(!prefix.exists()) { "Existing Termux prefix detected. It will not be overwritten. Back it up before clearing app data." }
                check(!pending.exists()) { "Interrupted deployment detected. Data preserved; inspect diagnostics and back up before clearing app data." }
                check(app.filesDir.usableSpace > 384L * 1024 * 1024) { "At least 384 MiB free internal storage is required" }
                val zip = File(app.cacheDir, "agent-bootstrap-verified.zip")
                stage = "verifying"; progress = 3
                val digest = MessageDigest.getInstance("SHA-256")
                app.assets.open("termux/bootstrap-aarch64.zip").use { input -> FileOutputStream(zip).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n); output.write(buffer, 0, n) }
                    output.fd.sync()
                } }
                check(digest.digest().joinToString("") { "%02x".format(it) } == ZIP_SHA256) { "Bundled bootstrap SHA-256 mismatch" }
                stageDir = File(app.filesDir, ".agent-stage-" + java.util.UUID.randomUUID())
                check(stageDir!!.mkdir()) { "Cannot create private staging directory" }
                Os.chmod(stageDir!!.path, 448)
                val links = mutableListOf<Pair<String, String>>()
                var files = 0
                var expanded = 0L
                val names = HashSet<String>()
                stage = "extracting"; progress = 10
                ZipInputStream(zip.inputStream().buffered()).use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val entry = input.nextEntry ?: break
                        check(++files <= 30000) { "Bootstrap has too many entries" }
                        val name = normalizeName(entry.name)
                        check(names.add(name)) { "Duplicate ZIP entry" }
                        if (name == "SYMLINKS.txt") {
                            val bytes = java.io.ByteArrayOutputStream()
                            while (true) { val n = input.read(buffer); if (n < 0) break; check(bytes.size() + n <= 1024 * 1024); bytes.write(buffer, 0, n) }
                            bytes.toString("UTF-8").lineSequence().filter { it.isNotBlank() }.forEach { line ->
                                val parts = line.split('←')
                                check(parts.size == 2 && links.size < 10000) { "Malformed bootstrap symlink" }
                                val destination = normalizeName(parts[1])
                                check(parts[0].isNotEmpty() && '\u0000' !in parts[0])
                                validateLink(parts[0], destination)
                                links.add(parts[0] to destination)
                            }
                        } else {
                            val target = File(stageDir, name)
                            check(target.canonicalPath.startsWith(stageDir!!.canonicalPath + "/")) { "ZIP entry escapes staging" }
                            if (entry.isDirectory) check(target.mkdirs() || target.isDirectory) else {
                                check(target.parentFile!!.mkdirs() || target.parentFile!!.isDirectory)
                                FileOutputStream(target).use { out -> while (true) {
                                    val n = input.read(buffer); if (n < 0) break
                                    expanded += n; check(expanded <= 512L * 1024 * 1024) { "Bootstrap expansion limit exceeded" }; out.write(buffer, 0, n)
                                } }
                                val executable = name.startsWith("bin/") || name.startsWith("libexec/") || name.startsWith("var/lib/dpkg/info/") || name.startsWith("lib/apt/methods/") || name == "lib/apt/apt-helper" || name == "etc/termux/bootstrap/termux-bootstrap-second-stage.sh"
                                Os.chmod(target.path, if (executable) 448 else 384)
                            }
                        }
                        progress = (10 + files * 65 / 15000).coerceAtMost(75)
                        input.closeEntry()
                    }
                }
                check(links.isNotEmpty()) { "Missing bootstrap symlink manifest" }
                // Create links last, so no archive entry can write through one.
                stage = "symlinks"; progress = 78
                val linked = HashSet<String>()
                links.forEach { (source, destination) ->
                    check(linked.add(destination) && !names.contains(destination)) { "Duplicate link destination" }
                    val target = File(stageDir, destination)
                    check(target.parentFile!!.mkdirs() || target.parentFile!!.isDirectory)
                    check(target.parentFile!!.canonicalPath.startsWith(stageDir!!.canonicalPath)) { "Link parent escapes staging" }
                    Os.symlink(source, target.path)
                }
                check(File(stageDir, "bin/bash").isFile && File(stageDir, "bin/apt").isFile && File(stageDir, "bin/pkg").isFile) { "Bootstrap tools missing" }
                File(RuntimeEnvironment.HOME).mkdirs()
                // Recheck before publication; express both rename endpoints through the fixed mount alias.
                val publicationCheck = RuntimeEnvironment.privatePrefixCheck()
                pathCheck = RuntimeEnvironment.privatePrefixDiagnostics(publicationCheck).toString()
                publicationCheck.requireMatch()
                val publicationSource = PrivatePrefixPath.publicationSource(app.filesDir, stageDir!!)
                pending.writeText("official-v0.118.3:" + ZIP_SHA256)
                check(!prefix.exists() && publicationSource.renameTo(prefix)) { "Atomic prefix publication failed; existing environment was not replaced" }
                stageDir = null
                stage = "configuring"; progress = 85
                val second = File(prefix, "etc/termux/bootstrap/termux-bootstrap-second-stage.sh")
                if (second.isFile) runSecondStage(second)
                val required = listOf("bash", "apt", "pkg", "curl", "tar", "gzip")
                check(required.all { File(prefix, "bin/" + it).canExecute() }) { "Bootstrap tool validation failed" }
                val complete = File(app.filesDir, ".agent-bootstrap-complete.tmp")
                complete.writeText(JSONObject().put("version", "0.118.3").put("sha256", ZIP_SHA256).put("installed_at", System.currentTimeMillis()).toString())
                check(complete.renameTo(marker)) { "Cannot commit bootstrap completion record" }
                pending.delete(); zip.delete()
                stage = "ready"; progress = 100
            } catch (failure: Throwable) {
                deploymentFailed(failure)
                if (failure is VirtualMachineError || failure is ThreadDeath) throw failure
            } finally {
                try { stageDir?.let { privateDeleteTree(it) } }
                catch (failure: Throwable) {
                    deploymentFailed(failure)
                    if (failure is VirtualMachineError || failure is ThreadDeath) throw failure
                } finally { installing = false }
            }
        }
        try { worker.execute(install) } catch (failure: Throwable) {
            deploymentFailed(failure); installing = false
            if (failure is VirtualMachineError || failure is ThreadDeath) throw failure
        }
        return status()
    }

    private fun deploymentFailed(failure: Throwable) {
        error = failure.javaClass.simpleName + ": " + (failure.message ?: "未知部署错误")
        stage = "failed"
    }

    private fun normalizeName(raw: String): String {
        require(raw.length <= 4096 && '\u0000' !in raw && '\\' !in raw && !raw.startsWith('/')) { "Invalid ZIP path" }
        val name = raw.removePrefix("./").trimEnd('/')
        require(name.isNotEmpty() && name.split('/').none { it.isEmpty() || it == "." || it == ".." }) { "Invalid ZIP path components" }
        return name
    }
    private fun validateLink(source: String, destination: String) {
        val logical = File(RuntimeEnvironment.PREFIX)
        val target = if (source.startsWith('/')) File(source) else File(File(logical, destination).parentFile, source)
        val normalized = target.toPath().normalize().toString()
        require(normalized == logical.path || normalized.startsWith(logical.path + "/")) { "Bootstrap symlink escapes private prefix" }
    }
    private fun runSecondStage(script: File) {
        val log = File(app.filesDir, "bootstrap-install.log")
        val builder = ProcessBuilder(RuntimeEnvironment.PREFIX + "/bin/bash", script.path)
        builder.environment().clear(); builder.environment().putAll(RuntimeEnvironment.environment("termux"))
        builder.directory(File(RuntimeEnvironment.HOME)); builder.redirectErrorStream(true); builder.redirectOutput(log)
        val process = builder.start(); process.outputStream.close()
        try {
            check(process.waitFor(180, TimeUnit.SECONDS)) { "Official bootstrap second stage timed out; see bootstrap-install.log" }
            check(process.exitValue() == 0) { "Official bootstrap second stage failed; see bootstrap-install.log" }
        } finally { if (process.isAlive) process.destroyForcibly() }
    }
    private fun privateDeleteTree(file: File) {
        try {
            check(file.parentFile!!.canonicalFile == app.filesDir.canonicalFile && file.name.startsWith(".agent-stage-"))
            Files.walkFileTree(file.toPath(), object : SimpleFileVisitor<Path>() {
                override fun visitFile(path: Path, attrs: BasicFileAttributes): FileVisitResult { Files.delete(path); return FileVisitResult.CONTINUE }
                override fun postVisitDirectory(path: Path, exc: java.io.IOException?): FileVisitResult { Files.delete(path); return FileVisitResult.CONTINUE }
            })
        } catch (_: Exception) { }
    }
}
