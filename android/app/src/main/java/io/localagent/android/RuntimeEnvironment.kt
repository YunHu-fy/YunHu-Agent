package io.localagent.android

import android.content.Context
import android.os.Process
import android.system.Os
import android.system.OsConstants
import org.json.JSONObject
import java.io.File

internal object RuntimeEnvironment {
    const val PREFIX = "/data/data/com.termux/files/usr"
    const val HOME = "/data/data/com.termux/files/home"
    lateinit var app: Context
        private set
    fun initialize(context: Context) { app = context.applicationContext }
    /**
     * Kernel page size in bytes. Android 15+ devices may run a 16 KB kernel, where the vendored
     * 4 KB-aligned `libtermux.so` cannot be mapped; diagnostics reports it so a crash is explainable.
     */
    fun pageSizeBytes(): Int = try { Os.sysconf(OsConstants._SC_PAGE_SIZE).toInt() } catch (_: Exception) { 0 }
    fun privatePrefixCheck(): PrivatePrefixPath.Result = PrivatePrefixPath.inspect(app.filesDir.absolutePath, Process.myUid()) { path ->
        val identity = Os.stat(path) // stat follows Android's directory aliases; never create or modify paths to probe them.
        PrivatePrefixPath.Identity(identity.st_dev, identity.st_ino, identity.st_uid, OsConstants.S_ISDIR(identity.st_mode))
    }
    fun privatePrefixDiagnostics(result: PrivatePrefixPath.Result = privatePrefixCheck()): JSONObject {
        fun identity(value: PrivatePrefixPath.Identity?): Any = value?.let {
            JSONObject().put("device", it.device.toString()).put("inode", it.inode.toString()).put("uid", it.uid).put("directory", it.directory)
        } ?: JSONObject.NULL
        return JSONObject().put("matches", result.matches).put("method", "stat_device_inode_owner")
            .put("actual_files_dir", result.actualPath).put("fixed_files_dir", result.expectedPath).put("app_uid", result.ownerUid)
            .put("actual", identity(result.actual)).put("fixed", identity(result.expected)).put("error", result.failure ?: JSONObject.NULL)
    }

    fun environment(runtime: String): MutableMap<String, String> {

        val env = mutableMapOf("PATH" to "/system/bin:/system/xbin:/vendor/bin", "HOME" to app.filesDir.absolutePath,
            "TMPDIR" to app.cacheDir.absolutePath, "LANG" to "en_US.UTF-8", "ANDROID_ROOT" to "/system", "ANDROID_DATA" to "/data")
        // Chaquopy's LD_LIBRARY_PATH/PYTHONHOME must not leak into native children.
        for (key in listOf("ANDROID_ART_ROOT", "ANDROID_I18N_ROOT", "ANDROID_RUNTIME_ROOT", "ANDROID_TZDATA_ROOT", "BOOTCLASSPATH", "DEX2OATBOOTCLASSPATH", "EXTERNAL_STORAGE")) {
            System.getenv(key)?.let { env[key] = it }
        }
        if (runtime == "termux") {
            env.putAll(mapOf("HOME" to HOME, "PREFIX" to PREFIX, "TERMUX_PREFIX" to PREFIX,
                "TMPDIR" to "$PREFIX/tmp", "PATH" to "$PREFIX/bin:/system/bin:/system/xbin:/vendor/bin",
                "SHELL" to "$PREFIX/bin/bash", "TERM" to "xterm-256color", "COLORTERM" to "truecolor",
                "TERMUX_VERSION" to "0.118.3", "TERMUX_APK_RELEASE" to "GITHUB",
                "TERMUX_APP_PACKAGE_MANAGER" to "apt", "TERMUX_APP_PACKAGE_VARIANT" to "apt-android-7",
                "TERMUX__UID" to Process.myUid().toString(), "TERMUX__USER_ID" to "0",
                "TERMUX__HOME" to HOME, "TERMUX__PREFIX" to PREFIX, "TERMUX__ROOTFS_DIR" to "/data/data/com.termux/files",
                "ANDROID__BUILD_VERSION_SDK" to android.os.Build.VERSION.SDK_INT.toString(),
                "TERMUX_APP__DATA_DIR" to app.applicationInfo.dataDir, "TERMUX_APP__LEGACY_DATA_DIR" to "/data/data/com.termux",
                "TERMUX_APP_PID" to Process.myPid().toString(), "PWD" to HOME,
                "TERMUX__APP_PACKAGE_NAME" to "com.termux", "TERMUX__APP_VERSION_NAME" to "0.118.3"))
            val preload = File("$PREFIX/lib/libtermux-exec.so").takeIf { it.isFile } ?: File("$PREFIX/lib/libtermux-exec-ld-preload.so")
            if (preload.isFile) env["LD_PRELOAD"] = preload.absolutePath
        }
        return env
    }

    fun shell(request: CommandRequest, rootExecutable: String? = null): Pair<List<String>, Map<String, String>> {
        val env = environment(request.runtime).apply { putAll(request.environment) }
        val cwd = request.cwd ?: if (request.runtime == "termux") HOME else app.filesDir.absolutePath
        val shell = if (request.runtime == "termux") "$PREFIX/bin/bash" else "/system/bin/sh"
        val run = ProcessGroups.announce(request) + "cd " + DeviceCommands.quote(cwd) + " || exit 125; exec " + DeviceCommands.quote(shell) + " -c " + DeviceCommands.quote(request.command)
        // setsid runs inside the selected authority for privileged children; the outer group is best effort.
        val setsid = if (request.runtime == "termux") "$PREFIX/bin/setsid" else "/system/bin/setsid"
        val outer = if (File("/system/bin/setsid").canExecute()) listOf("/system/bin/setsid") else listOf("/system/bin/toybox", "setsid")
        val argv = if (rootExecutable == null) outer + listOf("/system/bin/sh", "-c", run) else {
            val export = env.entries.joinToString(" ") { it.key + "=" + DeviceCommands.quote(it.value) }
            val rootRun = "export $export; " + if (File(setsid).canExecute()) "exec " + DeviceCommands.quote(setsid) + " /system/bin/sh -c " + DeviceCommands.quote(run) else run
            outer + listOf(rootExecutable, "-c", "/system/bin/sh -c " + DeviceCommands.quote(rootRun))
        }
        return argv to env
    }
}
