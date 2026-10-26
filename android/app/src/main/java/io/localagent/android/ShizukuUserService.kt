package io.localagent.android

import android.os.Binder

/** Official Shizuku UserService. No app-private Termux paths are accessible to shell UID. */
class ShizukuUserService : IDeviceUserService.Stub() {
    @Volatile private var ownerUid: Int? = null
    @Synchronized private fun verifyOwner() {
        val caller = Binder.getCallingUid()
        val owner = ownerUid
        if (owner == null) { require(caller >= 10000) { "Application caller required" }; ownerUid = caller }
        else check(owner == caller) { "Unexpected binder caller" }
    }
    override fun commandStart(requestJson: String): String = try {
        verifyOwner()
        val request = DeviceCommands.parse(requestJson)
        require(request.channel == "shizuku") { "Shizuku channel required" }
        require(request.runtime == "system") { "Shizuku UID cannot access private Termux prefix; select normal or Root for Termux." }
        val cwd = request.cwd ?: "/data/local/tmp"
        val env = mutableMapOf("PATH" to "/system/bin:/system/xbin:/vendor/bin", "HOME" to "/data/local/tmp", "TMPDIR" to "/data/local/tmp", "ANDROID_ROOT" to "/system", "ANDROID_DATA" to "/data", "LANG" to "en_US.UTF-8")
        env.putAll(request.environment)
        val script = ProcessGroups.announce(request) + "cd " + DeviceCommands.quote(cwd) + " || exit 125; exec /system/bin/sh -c " + DeviceCommands.quote(request.command)
        DeviceProcess.start(request, listOf("/system/bin/toybox", "setsid", "/system/bin/sh", "-c", script), env, null)
    } catch (failure: Exception) { bridgeError("shizuku_start_failed", failure.message ?: "Shizuku command failed") }
    override fun commandPoll(id: String, after: Int): String { verifyOwner(); return DeviceProcess.poll(id, after, false, 16) }
    override fun resultSlice(id: String, stream: String, offset: Int): String { verifyOwner(); return DeviceProcess.resultSlice(id, stream, offset) }
    override fun commandCancel(id: String): String { verifyOwner(); return DeviceProcess.cancel(id) }
    override fun cancelAll() { verifyOwner(); DeviceProcess.cancelAll() }
    override fun destroy() { verifyOwner(); DeviceProcess.cancelAll(); kotlin.system.exitProcess(0) }
}
