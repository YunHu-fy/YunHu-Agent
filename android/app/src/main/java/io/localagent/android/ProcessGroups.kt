package io.localagent.android

import java.io.File

/** No hidden Process.pid/getpgid reflection; verify the announced session leader via procfs. */
internal object ProcessGroups {
    fun identity(pid: Int): String? = try {
        if (pid <= 1) null else {
            val stat = File("/proc/" + pid + "/stat").readText()
            val fields = stat.substring(stat.lastIndexOf(')') + 2).split(' ')
            if (fields.size > 19 && fields[2].toIntOrNull() == pid) fields[19] else null
        }
    } catch (_: Exception) { null }
    fun isLeader(pid: Int): Boolean = identity(pid) != null
    fun announce(request: CommandRequest): String {
        val dollar = 36.toChar()
        val setup = "read -r __agent_stat < /proc/" + dollar + dollar + "/stat; __agent_tail=" + dollar + "{__agent_stat##*) }; set -- " + dollar + "__agent_tail; "
        return setup + "printf '%s%s:%s\\n' " + DeviceCommands.quote("__AGENT_GROUP_" + request.id + ":") + " " + dollar + dollar + " " + dollar + "{20} >&2; "
    }
}
