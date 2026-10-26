package io.localagent.android

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView

/** Five independent native pages. This view never requests privileges or performs IO. */
internal class OnboardingScreen(
    context: Context,
    private val state: SetupWizardState,
    private val returningUser: Boolean,
    private val actions: Actions
) : FrameLayout(context) {
    interface Actions {
        fun next()
        fun back()
        fun consent(checked: Boolean)
        fun select(channel: String)
        fun authorize()
        fun checkEnvironment()
        fun deploy()
        fun licenses()
        fun enter()
    }
    var detail: String = ""
    var environmentReport: String = ""
    var deployment: String = ""
    var deploying: Boolean = false
    private var motif: WelcomeSceneView? = null
    private var active = false
    private var renderedUi: UiPreferenceValues? = null
    private var renderedPalette: UiPalette? = null
    fun refreshPreferences() {
        val ui = UiPreferences.read(context)
        if (ui != renderedUi || UiPreferences.palette(context, ui) != renderedPalette) render()
    }
    fun release() {
        val scene = motif
        motif = null
        active = false
        scene?.setActive(false)
        removeAllViews()
        scene?.release()
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun tr(zh: String, en: String) = UiPreferences.read(context).text(zh, en)
    fun setActive(value: Boolean) { active = value; motif?.setActive(value) }
    private fun background(color: Int, radius: Int = 16): GradientDrawable = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    fun render(animate: Boolean = false) {
        val previousScene = motif
        previousScene?.setActive(false)
        motif = null
        val ui = UiPreferences.read(context)
        val palette = UiPreferences.palette(context, ui)
        renderedUi = ui
        renderedPalette = palette
        setBackgroundColor(palette.background)
        removeAllViews()
        previousScene?.release()
        val shell = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(28), dp(12), dp(28), dp(20))
            setOnApplyWindowInsetsListener { view, insets ->
                view.setPadding(dp(28) + insets.systemWindowInsetLeft, dp(12) + insets.systemWindowInsetTop,
                    dp(28) + insets.systemWindowInsetRight, dp(20) + insets.systemWindowInsetBottom)
                insets
            }
        }
        addView(shell, LayoutParams(-1, -1))
        fun label(text: String, size: Float = 15f, secondary: Boolean = false): TextView = TextView(context).apply {
            this.text = text; textSize = size * ui.scale
            setTextColor(if (secondary) palette.secondary else palette.foreground)
            setLineSpacing(dp(4).toFloat(), 1f)
        }
        fun button(text: String, primary: Boolean = false, enabled: Boolean = true, action: () -> Unit): Button = Button(context).apply {
            this.text = text; isAllCaps = false; textSize = 15f * ui.scale; isEnabled = enabled
            minHeight = dp(52); setPadding(dp(18), dp(8), dp(18), dp(8))
            setTextColor(if (primary) palette.onAccent else palette.accent)
            background = background(if (primary) palette.accent else palette.surface, 18)
            alpha = if (enabled) 1f else .45f
            setOnClickListener { action() }
        }
        val top = LinearLayout(context).apply { gravity = Gravity.CENTER_VERTICAL }
        top.addView(button(tr("返回", "Back"), enabled = !state.busy) { actions.back() }, LinearLayout.LayoutParams(-2, dp(44)))
        top.addView(label(tr("云琥 · 初始设置", "云琥 · Setup"), 12f, true).apply { gravity = Gravity.END }, LinearLayout.LayoutParams(0, -2, 1f))
        shell.addView(top)
        val progress = LinearLayout(context).apply { setPadding(0, dp(20), 0, dp(4)) }
        SetupWizardState.Page.entries.forEach { page ->
            progress.addView(View(context).apply { background = background(if (page.ordinal <= state.page.ordinal) palette.accent else palette.line, 2) },
                LinearLayout.LayoutParams(0, dp(3), 1f).apply { marginEnd = dp(5) })
        }
        shell.addView(progress)
        progress.contentDescription = tr("第 ", "Step ") + (state.page.ordinal + 1) + " / 5"
        val scroll = ScrollView(context).apply { isFillViewport = true; clipToPadding = false }
        val body = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(26), 0, dp(20)) }
        scroll.addView(body, FrameLayout.LayoutParams(-1, -1))
        shell.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        fun title(text: String) { body.addView(label(text, 30f).apply { typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL); setPadding(0, 0, 0, dp(14)); isAccessibilityHeading = true }) }
        fun paragraph(text: String) { body.addView(label(text, 14f, true).apply { setPadding(0, 0, 0, dp(18)) }) }
        fun inline(view: View) { body.addView(view, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(12) }) }
        when (state.page) {
            SetupWizardState.Page.WELCOME -> {
                body.setPadding(0, dp(8), 0, 0)
                motif = WelcomeSceneView(context, ui.scale, palette.foreground).also { scene ->
                    body.addView(scene, LinearLayout.LayoutParams(-1, 0, 1f))
                    scene.setActive(active)
                }
            }
            SetupWizardState.Page.PRIVACY -> {
                title(tr("了解，然后开始", "Understand, then begin"))
                paragraph(tr("你始终决定应用拥有什么权限。", "You decide which permissions the app may use."))
                paragraph(tr("AI 生成的命令可能出错，导致数据丢失或设备损坏。仅在你拥有或已获授权的设备上使用，重要数据请先备份。", "AI-generated commands can be wrong and may cause data loss or damage. Use only devices you own or are authorized to manage. Back up important data first."))
                paragraph(tr("使用云模型时，你发送的对话、附件、命令和结果会交给你配置的服务，包括为整理上下文而发送的摘要请求。执行记录与记忆保存在本机。本地模型连接不主动上传到额外服务。", "When you use a cloud model, your messages, attachments, commands and results go to the service you configure, including requests that summarize context. Execution history and memory stay on this device. Local model connections do not upload to an additional service."))
                paragraph(tr("应用遵循 GPL-3.0-only 开源许可。内置 Termux 使用 com.termux 包名，与官方 Termux 不可共存；不同签名不能覆盖安装。应用不会自动卸载或清除已有数据。", "The app is licensed under GPL-3.0-only. Bundled Termux requires the com.termux package name and cannot coexist with official Termux. Different signatures cannot overwrite an installation. The app never automatically uninstalls or clears existing data."))
                inline(button(tr("阅读许可与组件来源", "Licenses and component sources")) { actions.licenses() })
                inline(CheckBox(context).apply {
                    text = tr("我已阅读并理解上述风险、隐私和许可说明", "I have read and understood the risks, privacy information and license")
                    textSize = 14f * ui.scale; setTextColor(palette.foreground); buttonTintList = ColorStateList.valueOf(palette.accent)
                    isChecked = state.consent; isEnabled = !state.busy
                    setOnCheckedChangeListener { _, checked -> actions.consent(checked) }
                })
            }
            SetupWizardState.Page.CHANNEL -> {
                title(tr("选择执行通道", "Choose an execution channel"))
                paragraph(tr("选择不会立即请求授权。下一页会明确列出要确认的权限。", "Choosing a channel does not request permission. You will confirm authorization on the next page."))
                val group = RadioGroup(context)
                listOf(Triple("normal", tr("普通应用权限", "Standard app permissions"), tr("推荐起点。可使用应用私有目录与内置 Termux；不需要 Root。", "A good starting point. Access the app's private files and bundled Termux without Root.")),
                    Triple("shizuku", "Shizuku / ADB", tr("需要单独激活 Shizuku 并允许系统授权。不能访问私有 Termux 目录。", "Activate Shizuku separately and approve its permission request. This channel cannot access the private Termux directory.")),
                    Triple("root", "Root", tr("仅对已 Root 的设备。你点击授权后才会请求 su，并核验 UID 0。", "For rooted devices only. The app requests su and verifies UID 0 only after you tap Authorize."))).forEach { (channel, name, description) ->
                    val option = RadioButton(context).apply {
                        id = View.generateViewId(); tag = channel; text = name + "\n" + description
                        textSize = 14f * ui.scale; setTextColor(palette.foreground); buttonTintList = ColorStateList.valueOf(palette.accent)
                        setPadding(dp(8), dp(16), dp(8), dp(16)); background = background(palette.surface)
                        isChecked = channel == state.selectedChannel; isEnabled = !state.busy
                    }
                    group.addView(option, RadioGroup.LayoutParams(-1, -2).apply { bottomMargin = dp(12) })
                }
                group.setOnCheckedChangeListener { current, id -> current.findViewById<RadioButton>(id)?.tag?.toString()?.let(actions::select) }
                inline(group)
                paragraph(tr("每次任务仍使用界面确认的通道；完全权限与逐次审核由任务设置决定。保存的通道选择不会在下次启动时自动恢复 Root 或 Shizuku 授权。", "Tasks use the channel confirmed in the interface. Task settings control full access and individual approval. Saving a choice never restores Root or Shizuku authorization on a later launch."))
            }
            SetupWizardState.Page.CONFIRM -> {
                title(tr("确认你的选择", "Confirm your choice"))
                paragraph(tr("所选通道：", "Selected channel: ") + when (state.selectedChannel) { "root" -> "Root"; "shizuku" -> "Shizuku / ADB"; else -> tr("普通应用权限", "Standard app permissions") })
                paragraph(tr("确认后只读检查 Android 版本、设备环境、SELinux 和工具路径，不运行模型命令。不会自动切换到其他通道。", "Confirmation runs a read-only check of Android compatibility, device environment, SELinux and tool paths. It does not run model commands or silently switch to another channel."))
                if (state.selectedChannel != "normal") inline(button(if (state.selectedChannel == "root") tr("明确请求 Root 授权", "Authorize Root explicitly") else tr("请求 Shizuku 授权", "Request Shizuku permission"), enabled = !state.busy) { actions.authorize() })
                inline(button(tr("确认通道并只读检测", "Confirm channel and run read-only check"), enabled = !state.busy) { actions.checkEnvironment() })
                if (detail.isNotBlank()) inline(label(detail, 14f, true).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE })
                if (environmentReport.isNotBlank()) inline(label(environmentReport, 12f, true).apply { typeface = Typeface.MONOSPACE; setTextIsSelectable(true); setPadding(dp(14), dp(14), dp(14), dp(14)); background = background(palette.surface) })
                paragraph(tr("支持 Android 10–17 / ARM64 / 主用户。Root 与 Shizuku 仍受系统和厂商限制。", "Supports Android 10–17, ARM64 and the primary Android user. Root and Shizuku remain subject to Android and device restrictions."))
            }
            SetupWizardState.Page.READY -> {
                title(tr("一切准备就绪", "You're ready"))
                paragraph(tr("已确认使用风险，并完成所选通道的只读环境检测。", "Risk information is confirmed and the selected channel has passed its read-only environment check."))
                paragraph(tr("你可以进入对话。需要完整终端工具时，再安装 APK 自带的 Termux 环境；无需额外下载。", "You can open your conversation now. If you need the full terminal toolset, install the Termux environment bundled with the APK. No additional download is needed."))
                inline(button(tr("安装内置 Termux 环境", "Install bundled Termux environment"), enabled = !deploying && !state.busy) { actions.deploy() })
                if (deployment.isNotBlank()) inline(label(deployment, 14f, true).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE })
                paragraph(tr("部署不会覆盖未知的现有环境或删除已有 Termux 数据。", "Setup does not overwrite an unknown environment or delete existing Termux data."))
            }
        }
        val footerText = when (state.page) {
            SetupWizardState.Page.WELCOME -> tr("开始设置", "Get started")
            SetupWizardState.Page.PRIVACY -> tr("同意并继续", "Agree and continue")
            SetupWizardState.Page.CHANNEL -> tr("继续", "Continue")
            SetupWizardState.Page.CONFIRM -> tr("检测完成，继续", "Check complete · Continue")
            SetupWizardState.Page.READY -> if (returningUser) tr("返回对话", "Return to conversation") else tr("进入对话", "Open conversation")
        }
        val enabled = !state.busy && when (state.page) { SetupWizardState.Page.PRIVACY -> state.consent; SetupWizardState.Page.CONFIRM, SetupWizardState.Page.READY -> state.canEnter; else -> true }
        if (state.page == SetupWizardState.Page.WELCOME) {
            shell.addView(label(tr("欢迎使用云琥Agent", "Welcome to Yunhu Agent"), 19f).apply { gravity = Gravity.CENTER; setPadding(0, dp(12), 0, dp(5)) })
            shell.addView(label(tr("在自己的设备上，让想法开始行动。", "A calm place to turn your ideas into actions."), 13f, true).apply { gravity = Gravity.CENTER; setPadding(0, 0, 0, dp(18)) })
        }
        shell.addView(button(footerText, primary = true, enabled = enabled) { if (state.page == SetupWizardState.Page.READY) actions.enter() else actions.next() }, LinearLayout.LayoutParams(-1, -2))
        if (state.busy) shell.addView(label(tr("正在处理，请稍候…", "Working, please wait…"), 12f, true).apply { gravity = Gravity.CENTER; setPadding(0, dp(8), 0, 0) })
        shell.requestApplyInsets()
        if (animate && WelcomeSceneView.motionAllowed(context)) { body.alpha = .3f; body.translationY = dp(6).toFloat(); body.animate().alpha(1f).translationY(0f).setDuration(220).start() }
    }
}


