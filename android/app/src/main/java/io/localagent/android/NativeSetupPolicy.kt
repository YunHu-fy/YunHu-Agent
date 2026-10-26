package io.localagent.android

/** Shared onboarding/deployment compatibility and explicit authorization routing. */
internal object NativeSetupPolicy {
    const val MIN_SDK = 29
    const val MAX_SDK = 37
    fun supported(sdk: Int, abis: List<String>): Boolean = sdk in MIN_SDK..MAX_SDK && "arm64-v8a" in abis

    fun deploymentStage(stage: String): String = when (stage) {
        "checking" -> "正在检查系统和可用空间"
        "verifying" -> "正在校验 APK 内置环境"
        "extracting" -> "正在解压 APK 内置环境"
        "symlinks" -> "正在建立运行环境链接"
        "linking" -> "正在建立运行环境链接"
        "configuring" -> "正在初始化软件包"
        "publishing" -> "正在发布运行环境"
        "second_stage" -> "正在初始化软件包"
        "ready" -> "已就绪"
        "failed" -> "部署失败"
        "not_installed" -> "尚未部署"
        else -> stage.ifBlank { "正在读取状态" }
    }

    fun authorize(channel: String, configure: (String) -> String, shizuku: () -> String): String = when (channel) {
        "normal", "root" -> configure(channel)
        "shizuku" -> shizuku()
        else -> throw IllegalArgumentException("未知权限通道")
    }
}
