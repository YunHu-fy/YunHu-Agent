package io.localagent.android

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.webkit.ValueCallback
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.RenderProcessGoneDetail
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.CheckBox
import android.widget.ScrollView
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject
import java.util.concurrent.Executors
import java.io.ByteArrayInputStream

/** Native WebView shell; the conversation page gets one origin-checked transcript bridge. */
class MainActivity : ComponentActivity() {
    private val setupWorker = Executors.newSingleThreadExecutor { Thread(it, "native-onboarding") }
    private var setupBusy = false
    private var setupScreen = false
    private var wizard = SetupWizardState()
    private var setupView: OnboardingScreen? = null
    private var setupGeneration = 0L
    private var setupAuthorizedChannel: String? = null
    private var returningFromSetup = false
    private var conversationRoot: FrameLayout? = null
    private var runtimePollBusy = false
    private val uiListener = UiPreferences.Listener { if (!isDestroyed) applyUiPreferences() }
    private fun tr(zh: String, en: String) = UiPreferences.read(this).text(zh, en)
    private fun uiEnglish() = UiPreferences.read(this).language == "en"
    private fun pageFailureMessage() = if (uiEnglish()) "The conversation page is not ready. Retry the page." else pageLoad.message
    companion object { const val EXTRA_SHOW_SETUP = "io.localagent.android.extra.SHOW_SETUP" }

    private fun nativeContent(view: View) { setContent { MaterialTheme { androidx.compose.runtime.key(view) { AndroidView(modifier = Modifier.fillMaxSize(), factory = { view }) } } } }
    private lateinit var webView: WebView
    private var transcriptBridge: TranscriptShareBridge? = null
    private lateinit var status: TextView
    private lateinit var retry: Button
    private lateinit var controls: LinearLayout
    private var loadedLaunchUrl: String? = null
    private var observing = false
    private val pageLoad = PageLoadState()
    private var pageProbePending = false
    private var rendererGone = false
    private var serviceWaitSince = 0L
    private var fileSelection: ValueCallback<Array<Uri>>? = null
    private var fileSelectionView: WebView? = null
    private var fileSelectionGeneration = 0L
    private var documentGeneration = 0L
    private var documentPickerActive = false
    private val chosenContent = java.util.concurrent.ConcurrentHashMap.newKeySet<Uri>()
    private val documentPicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        documentPickerActive = false
        val callback = fileSelection
        val owner = fileSelectionView
        fileSelection = null; fileSelectionView = null
        val currentUrl = owner?.url?.let(Uri::parse)
        val valid = callback != null && result.resultCode == Activity.RESULT_OK && owner === webView && !setupScreen && !rendererGone &&
            fileSelectionGeneration == documentGeneration && currentUrl != null && AgentRuntime.isLocal(currentUrl) && currentUrl.path == "/"
        val returned = linkedSetOf<Uri>()
        result.data?.clipData?.let { clip -> for (i in 0 until clip.itemCount) returned.add(clip.getItemAt(i).uri) }
        result.data?.data?.let { returned.add(it) }
        val safe = if (valid) returned.filter { it.scheme == "content" }.take(8) else emptyList()
        returned.filter { it.scheme == "content" && it !in safe }.forEach(::revokeContentGrant)
        chosenContent.addAll(safe)
        callback?.onReceiveValue(safe.takeIf { it.isNotEmpty() }?.toTypedArray())
    }
    private fun revokeContentGrant(uri: Uri) {
        try { revokeUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } catch (_: SecurityException) { }
    }
    private fun cancelFileSelection() {
        val callback = fileSelection
        fileSelection = null; fileSelectionView = null
        callback?.onReceiveValue(null)
    }
    private fun invalidateDocumentAccess() {
        documentGeneration++
        chosenContent.forEach(::revokeContentGrant)
        chosenContent.clear()
        cancelFileSelection()
    }

    private val observe = object : Runnable {
        override fun run() {
            if (!observing) return
            renderRuntime()
            AgentRuntime.main.postDelayed(this, 300)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        UiPreferences.applyWindow(this)
        super.onCreate(savedInstanceState)
        DeviceBridge.initialize(this)
        UiPreferences.addListener(uiListener)
        UiPreferences.applyWindow(this)
        if (savedInstanceState?.getBoolean("setup_screen") == true) {
            wizard = SetupWizardState.restore(savedInstanceState.getString("setup_page"), savedInstanceState.getBoolean("setup_consent"), savedInstanceState.getString("setup_channel"))
            showSetup(restored = true)
            return
        }
        val onboarding = getSharedPreferences(FirstRunGate.PREFS_NAME, MODE_PRIVATE)
        val decision = FirstRunGate.startupDecision(
            firstRunComplete = if (onboarding.contains(FirstRunGate.FIRST_RUN_COMPLETE)) onboarding.getBoolean(FirstRunGate.FIRST_RUN_COMPLETE, false) else null,
            consentGiven = onboarding.getBoolean(FirstRunGate.CONSENT_V1, false),
            serviceDesired = ServiceLifecycle.desired()
        )
        if (decision.migrateLegacy) {
            onboarding.edit()
                .putBoolean(FirstRunGate.FIRST_RUN_COMPLETE, true)
                .putString(FirstRunGate.SELECTED_CHANNEL, FirstRunGate.selectedChannel(onboarding.getString(FirstRunGate.SELECTED_CHANNEL, null)))
                .apply()
        }
        // Saved onboarding is a UI decision, never a Root/Shizuku grant to replay.
        if (!decision.bypassSetup || intent.getBooleanExtra(EXTRA_SHOW_SETUP, false)) { showSetup(); return }
        buildConversation()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_SHOW_SETUP, false) && !setupScreen) showSetup()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun buildConversation() {
        invalidateDocumentAccess()
        setupScreen = false
        setupView?.release(); setupView = null
        AgentRuntime.main.removeCallbacks(deploymentRefresh)
        if (::webView.isInitialized) {
            transcriptBridge?.close()
            transcriptBridge = null
            webView.removeJavascriptInterface(TranscriptShareBridge.JS_NAME)
            if (!rendererGone) webView.destroy()
        }
        pageLoad.reset(); pageProbePending = false; rendererGone = false; loadedLaunchUrl = null
        val root = FrameLayout(this).apply {
            layoutParams = android.view.ViewGroup.LayoutParams(-1, -1)
            setBackgroundColor(0xfff4f5f2.toInt())
            setOnApplyWindowInsetsListener { view, insets ->
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
                insets
            }
        }
        status = TextView(this).apply { textSize = 15f; gravity = Gravity.CENTER; setPadding(24, 24, 24, 12); text = tr("正在启动本地服务…", "Starting the local service…") }
        retry = Button(this).apply { text = tr("启动服务", "Start service"); setOnClickListener { retryConversation() } }
        controls = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(0xfff4f5f2.toInt())
            addView(status)
            addView(retry)
        }
        webView = WebView(this).apply {
            setBackgroundColor(0xfff7f8fa.toInt())
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                allowFileAccess = false
                allowContentAccess = true // Only explicit document selections pass the request allowlist below.
                javaScriptCanOpenWindowsAutomatically = false
                setSupportMultipleWindows(false)
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                mediaPlaybackRequiresUserGesture = true
            }
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
            val bridge = TranscriptShareBridge(this@MainActivity, this) {
                !setupScreen && !rendererGone && pageLoad.phase == PageLoadState.Phase.READY
            }
            transcriptBridge = bridge
            addJavascriptInterface(bridge, TranscriptShareBridge.JS_NAME)
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                    val origin = view.url?.let { Uri.parse(it) }
                    if (view !== webView || origin == null || !AgentRuntime.isLocal(origin) || origin.path != "/" || setupScreen || rendererGone || documentPickerActive) {
                        callback.onReceiveValue(null); return true
                    }
                    cancelFileSelection()
                    fileSelection = callback; fileSelectionView = view; fileSelectionGeneration = documentGeneration
                    val types = params.acceptTypes.filter { it.isNotBlank() && it.contains('/') }.toTypedArray()
                    val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).apply {
                        type = if (types.size == 1) types[0] else "*/*"
                        if (types.size > 1) putExtra(Intent.EXTRA_MIME_TYPES, types)
                        putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    try { documentPickerActive = true; documentPicker.launch(pick) }
                    catch (_: RuntimeException) { documentPickerActive = false; cancelFileSelection(); Toast.makeText(this@MainActivity, tr("系统文件选择器不可用，请稍后重试。", "The system file picker is unavailable. Please try again."), Toast.LENGTH_LONG).show() }
                    return true
                }
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val blocked = !AgentRuntime.isLocal(request.url)
                    if (!blocked && request.isForMainFrame && view === webView) invalidateDocumentAccess()
                    return blocked
                }

                override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                    if (view === webView) invalidateDocumentAccess()
                }

                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    if (AgentRuntime.isLocal(request.url)) return null
                    if (request.url.scheme == "content" && chosenContent.contains(request.url)) return null
                    return WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
                }

                override fun onPageCommitVisible(view: WebView, url: String) {
                    if (view === webView && AgentRuntime.isLocal(android.net.Uri.parse(url))) {
                        pageLoad.committed(pageLoad.generation)
                        renderRuntime()
                    }
                }
                override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                    if (view === webView && essentialResource(request)) showPageError("会话页面资源加载失败（网络错误 " + error.errorCode + "），请重试。")
                }
                override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
                    if (view === webView && essentialResource(request)) showPageError("会话页面资源加载失败（HTTP " + response.statusCode + "），请重试。")
                }
                override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                    if (view === webView) {
                        invalidateDocumentAccess()
                        rendererGone = true
                        transcriptBridge?.close()
                        transcriptBridge = null
                        view.removeJavascriptInterface(TranscriptShareBridge.JS_NAME)
                        (view.parent as? android.view.ViewGroup)?.removeView(view)
                        view.destroy()
                        showPageError("系统 WebView 渲染进程已退出，请重试页面；反复出现时请更新 Android System WebView。")
                    }
                    return true
                }
            }
        }
        // Both children fill the viewport. The loading/error overlay never determines WebView height.
        root.addView(webView, FrameLayout.LayoutParams(-1, -1))
        root.addView(controls, FrameLayout.LayoutParams(-1, -1))
        conversationRoot = root
        nativeContent(root)
        applyUiPreferences()
        root.requestApplyInsets()
        if (AgentRuntime.phase == AgentRuntime.Phase.STOPPED && ServiceLifecycle.desired()) startAgent()
        renderRuntime()
    }

    private fun essentialResource(request: WebResourceRequest): Boolean = AgentRuntime.isLocal(request.url) &&
        (request.isForMainFrame || request.url.path in setOf("/static/app.js", "/static/markdown.js", "/static/app.css", "/static/preferences.js", "/static/i18n.js"))

    private fun showSetup(restored: Boolean = false) {
        invalidateDocumentAccess()
        setupGeneration++
        setupScreen = true
        setupBusy = false
        setupAuthorizedChannel = null
        val prefs = getSharedPreferences(FirstRunGate.PREFS_NAME, MODE_PRIVATE)
        returningFromSetup = prefs.getBoolean(FirstRunGate.FIRST_RUN_COMPLETE, false)
        if (!restored) wizard = SetupWizardState(consent = prefs.getBoolean(FirstRunGate.CONSENT_V1, false), selectedChannel = prefs.getString(FirstRunGate.SELECTED_CHANNEL, "normal") ?: "normal")
        // The web object stays intact while settings opens setup; its DOM/conversation is not reloaded.
        setupView?.release()
        val screen = OnboardingScreen(this, wizard, returningFromSetup, object : OnboardingScreen.Actions {
            override fun next() { if (wizard.next()) renderSetup(true) }
            override fun back() { handleSetupBack() }
            override fun consent(checked: Boolean) { wizard.consent(checked); setupAuthorizedChannel = null; renderSetup() }
            override fun select(channel: String) { wizard.select(channel); setupAuthorizedChannel = null; setupView?.detail = ""; setupView?.environmentReport = "" }
            override fun authorize() { authorizeSetup() }
            override fun checkEnvironment() { checkSetupEnvironment() }
            override fun deploy() { deploySetupEnvironment() }
            override fun licenses() { startActivity(Intent(this@MainActivity, LicensesActivity::class.java)) }
            override fun enter() { completeSetup() }
        })
        setupView = screen
        nativeContent(screen)
        UiPreferences.applyWindow(this)
        screen.setActive(observing)
        screen.render()
        pollDeployment()
    }
    private fun renderSetup(animate: Boolean = false) { wizard.busy = setupBusy; setupView?.render(animate) }
    private fun setupMessage(zh: String, en: String) { setupView?.detail = tr(zh, en); renderSetup() }
    private fun setupOperation(work: () -> String, apply: (JSONObject) -> Unit) {
        if (setupBusy || !wizard.consent || isDestroyed) return
        val generation = setupGeneration
        setupBusy = true; renderSetup()
        setupWorker.execute {
            val result = try { JSONObject(work()) } catch (_: Exception) { JSONObject().put("ok", false).put("error", JSONObject().put("code", "setup_failed")) }
            runOnUiThread {
                if (isDestroyed || !setupScreen || generation != setupGeneration) return@runOnUiThread
                setupBusy = false
                apply(result)
                renderSetup()
            }
        }
    }
    private fun setupFailure(result: JSONObject): String {
        val code = result.optJSONObject("error")?.optString("code").orEmpty()
        return when (code) {
            "root_unavailable" -> tr("未找到可用的 su。请检查设备 Root 状态或返回选择普通通道。", "No executable su was found. Check the device's Root status or go back and choose the standard channel.")
            "root_timeout" -> tr("Root 授权超时，请在授权管理器中核对后重试。", "Root authorization timed out. Check your Root manager and try again.")
            "root_denied" -> tr("Root 未获准，未核验 UID 0。", "Root was not granted; UID 0 was not verified.")
            "shizuku_unavailable" -> tr("请先安装并激活 Shizuku，再重新请求授权。", "Install and activate Shizuku before requesting permission.")
            "channel_changed" -> tr("通道已变化，本次结果已失效，请重新确认。", "The channel changed. This result is no longer valid; confirm again.")
            else -> tr("所选通道尚未就绪。请检查授权与设备状态后重试；应用不会自动切换通道。", "The selected channel is not ready. Check its permission and device status, then retry. The app will not switch channels automatically.")
        }
    }
    private fun authorizeSetup() {
        val channel = wizard.selectedChannel
        if (channel == "normal") return
        setupMessage("正在请求授权…", "Requesting authorization…")
        setupOperation({ NativeSetupPolicy.authorize(channel, DeviceBridge::configureChannel, DeviceBridge::requestShizuku) }) { result ->
            if (result.optBoolean("ok")) {
                // Root configure may show su only for this explicit button. The check button never requests Root.
                setupAuthorizedChannel = if (channel == "root") channel else null
                setupView?.detail = if (channel == "root") tr("Root 已授权且 UID 0 已核验。请继续只读检测。", "Root is authorized and UID 0 is verified. Continue with the read-only check.")
                    else tr("已向 Shizuku 请求授权。允许系统弹窗后，继续只读检测。", "Shizuku permission was requested. Approve the system dialog, then run the read-only check.")
            } else { setupAuthorizedChannel = null; setupView?.detail = setupFailure(result) }
        }
    }
    private fun checkSetupEnvironment() {
        if (!NativeSetupPolicy.supported(Build.VERSION.SDK_INT, Build.SUPPORTED_ABIS.toList())) { setupMessage("此版本支持 Android 10–17（API 29–37）的 ARM64 设备。", "This release supports Android 10–17 (API 29–37) on ARM64 devices."); return }
        val channel = wizard.selectedChannel
        if (!wizard.consent) return
        if (channel == "root" && setupAuthorizedChannel != "root") { setupMessage("请先点击明确请求 Root 授权，再检测环境。", "Tap Authorize Root explicitly before checking the environment."); return }
        setupMessage("正在确认通道并进行只读环境检查…", "Confirming the channel and checking the environment without changes…")
        setupOperation({
            val configured = if (channel == "root") {
                val current = JSONObject(DeviceBridge.status())
                JSONObject().put("ok", current.optString("selected_channel") == channel && current.optJSONObject("root")?.optBoolean("granted") == true)
            } else JSONObject(DeviceBridge.configureChannel(channel))
            if (!configured.optBoolean("ok")) configured.toString()
            else JSONObject().put("ok", true).put("diagnostics", JSONObject(DeviceBridge.diagnostics())).toString()
        }) { result ->
            val diagnostics = result.optJSONObject("diagnostics")
            val environment = diagnostics?.optJSONObject("environment")
            val valid = wizard.checked(channel, result.optBoolean("ok"), diagnostics?.optBoolean("ok") == true && environment != null)
            setupView?.detail = if (valid) tr("通道已确认，只读环境检测已通过。", "Channel confirmed. The read-only environment check passed.") else setupFailure(result)
            setupView?.environmentReport = if (valid) environment?.toString(2).orEmpty() else ""
        }
    }
    private fun completeSetup() {
        if (setupBusy || !wizard.canEnter) return
        getSharedPreferences(FirstRunGate.PREFS_NAME, MODE_PRIVATE).edit()
            .putBoolean(FirstRunGate.CONSENT_V1, true).putString(FirstRunGate.SELECTED_CHANNEL, wizard.selectedChannel)
            .putBoolean(FirstRunGate.FIRST_RUN_COMPLETE, true).apply()
        intent.removeExtra(EXTRA_SHOW_SETUP)
        closeSetup()
        if (!returningFromSetup) startAgent()
    }
    private fun closeSetup() {
        setupView?.release()
        setupGeneration++
        setupScreen = false
        setupView = null
        AgentRuntime.main.removeCallbacks(deploymentRefresh)
        if (conversationRoot != null && ::webView.isInitialized && !rendererGone) {
            nativeContent(conversationRoot!!); applyUiPreferences(); renderRuntime()
        } else buildConversation()
    }
    private fun handleSetupBack() {
        if (setupBusy) { setupMessage("请等待当前操作结束。", "Wait for the current operation to finish."); return }
        if (wizard.back()) renderSetup(true)
        else if (returningFromSetup) { intent.removeExtra(EXTRA_SHOW_SETUP); closeSetup() }
        else finish()
    }
    private fun deploySetupEnvironment() {
        if (setupBusy || !wizard.canEnter) return
        setupView?.deployment = tr("正在启动内置环境部署…", "Starting bundled environment installation…")
        setupOperation({ DeviceBridge.runtimeDeploy() }) { result ->
            if (!result.optBoolean("ok")) setupView?.deployment = tr("无法启动部署，请检查存储空间与环境兼容性后重试。", "Installation could not start. Check storage and environment compatibility, then retry.")
            pollDeployment()
        }
    }
    private val deploymentRefresh = Runnable { pollDeployment() }
    private fun pollDeployment() {
        AgentRuntime.main.removeCallbacks(deploymentRefresh)
        if (!setupScreen || isFinishing || isDestroyed || runtimePollBusy) return
        runtimePollBusy = true
        val generation = setupGeneration
        setupWorker.execute {
            val runtime = try { JSONObject(DeviceBridge.runtimeStatus()) } catch (_: Exception) { null }
            runOnUiThread {
                runtimePollBusy = false
                if (isDestroyed || !setupScreen || generation != setupGeneration) return@runOnUiThread
                val screen = setupView ?: return@runOnUiThread
                val installing = runtime?.optBoolean("installing") == true
                val message = when {
                    runtime == null -> tr("暂时无法读取环境状态，正在重试。", "Environment status is temporarily unavailable. Retrying.")
                    runtime.optString("stage") == "failed" -> tr("部署未完成。请检查空间与兼容性后重试；已有数据不会被覆盖。", "Installation did not finish. Check free space and compatibility before retrying. Existing data is not overwritten.")
                    runtime.optBoolean("installed") -> tr("内置环境已就绪 · 100%", "Bundled environment ready · 100%")
                    installing -> tr("正在部署 · ", "Installing · ") + runtime.optInt("progress") + "%"
                    else -> tr("内置环境尚未安装，可稍后安装。", "Bundled environment is not installed. You can install it later.")
                }
                if (screen.deployment != message || screen.deploying != installing) { screen.deployment = message; screen.deploying = installing; if (wizard.page == SetupWizardState.Page.READY) renderSetup() }
                if (installing || runtime == null) AgentRuntime.main.postDelayed(deploymentRefresh, if (runtime == null) 1500 else 500)
            }
        }
    }
    private fun applyUiPreferences() {
        UiPreferences.applyWindow(this)
        val ui = UiPreferences.read(this)
        val colors = UiPreferences.palette(this, ui)
        setupView?.refreshPreferences()
        conversationRoot?.setBackgroundColor(colors.background)
        if (::controls.isInitialized) { controls.setBackgroundColor(colors.background); status.setTextColor(colors.foreground); status.textSize = 15f * ui.scale; retry.textSize = 14f * ui.scale; retry.setTextColor(colors.accent) }
        if (!setupScreen && ::webView.isInitialized) { webView.setBackgroundColor(colors.background); renderRuntime() }
    }

    private fun showPageError(message: String) {
        if (AgentRuntime.phase != AgentRuntime.Phase.RUNNING) return
        pageLoad.fail(pageLoad.generation, message)
        controls.visibility = View.VISIBLE
        status.text = pageFailureMessage()
        retry.text = tr("重试页面", "Retry page")
        retry.visibility = View.VISIBLE
    }

    private fun retryConversation() {
        if (AgentRuntime.phase == AgentRuntime.Phase.RUNNING) {
            if (rendererGone) { buildConversation(); return }
            invalidateDocumentAccess()
            webView.stopLoading()
            loadedLaunchUrl = null
            pageLoad.reset(); pageProbePending = false
            renderRuntime()
        } else if (AgentRuntime.phase == AgentRuntime.Phase.STARTING || AgentRuntime.phase == AgentRuntime.Phase.STOPPING) {
            serviceWaitSince = SystemClock.elapsedRealtime()
            renderRuntime()
        } else startAgent()
    }

    private fun startAgent() {
        invalidateDocumentAccess()
        loadedLaunchUrl = null
        pageLoad.reset(); pageProbePending = false
        serviceWaitSince = SystemClock.elapsedRealtime()
        try { ServiceLifecycle.requestStart() }
        catch (_: RuntimeException) { AgentRuntime.update(AgentRuntime.Phase.FAILED, "系统未允许启动前台服务，请检查系统权限后重试。") }
        renderRuntime()
    }

    private fun probePage() {
        if (pageProbePending || rendererGone || pageLoad.phase != PageLoadState.Phase.LOADING) return
        val attempt = pageLoad.generation
        val view = webView
        pageProbePending = true
        try {
            // Read only booleans. No JavaScript interface and no credentials passed back from the page.
            view.evaluateJavascript("(function(){return location.origin==='http://127.0.0.1:8686' && location.pathname==='/' && document.documentElement.dataset.agentUiReady==='1' && document.documentElement.dataset.agentNavigationId==='" + attempt + "' && !!document.querySelector('#chat-form') && !!document.querySelector('#message-input') && getComputedStyle(document.querySelector('.app-shell')).display==='flex';})()") { value ->
                if (attempt != pageLoad.generation || view !== webView || isDestroyed) return@evaluateJavascript
                if (value == "true") {
                    view.postVisualStateCallback(attempt, object : WebView.VisualStateCallback() {
                        override fun onComplete(requestId: Long) {
                            if (view === webView && requestId == pageLoad.generation && !isDestroyed) { pageProbePending = false; pageLoad.initialized(requestId); renderRuntime() }
                        }
                    })
                } else pageProbePending = false
            }
        } catch (_: RuntimeException) { pageProbePending = false; showPageError(tr("会话页面初始化失败，请重试页面。", "Conversation initialization failed. Retry the page.")) }
    }

    private fun renderRuntime() {
        if (setupScreen || !::webView.isInitialized) return
        val launchUrl = AgentRuntime.launchUrlIfReady()
        if (launchUrl != null) {
            serviceWaitSince = 0
            if (loadedLaunchUrl != launchUrl) {
                invalidateDocumentAccess()
                loadedLaunchUrl = launchUrl
                pageProbePending = false
                pageLoad.begin(SystemClock.elapsedRealtime())
                controls.visibility = View.VISIBLE
                status.text = tr("本地服务已启动，正在加载会话页面…", "Local service started. Loading your conversation…")
                retry.visibility = View.GONE
                // Fragment is consumed by app.js, and is never shown in native diagnostics.
                webView.loadUrl(launchUrl + "&native_navigation=" + pageLoad.generation)
            }
            pageLoad.expire(SystemClock.elapsedRealtime())
            when (pageLoad.phase) {
                PageLoadState.Phase.READY -> controls.visibility = View.GONE
                PageLoadState.Phase.FAILED -> { controls.visibility = View.VISIBLE; status.text = pageFailureMessage(); retry.text = tr("重试页面", "Retry page"); retry.visibility = View.VISIBLE }
                else -> { controls.visibility = View.VISIBLE; status.text = tr("本地服务已启动，正在加载会话页面…", "Local service started. Loading your conversation…"); retry.visibility = View.GONE; probePage() }
            }
        } else {
            if (loadedLaunchUrl != null) {
                invalidateDocumentAccess()
                loadedLaunchUrl = null
                pageLoad.reset(); pageProbePending = false
                if (!rendererGone) webView.stopLoading()
            }
            controls.visibility = View.VISIBLE
            val waiting = AgentRuntime.phase == AgentRuntime.Phase.STARTING || AgentRuntime.phase == AgentRuntime.Phase.STOPPING
            if (waiting && serviceWaitSince == 0L) serviceWaitSince = SystemClock.elapsedRealtime()
            val delayed = waiting && SystemClock.elapsedRealtime() - serviceWaitSince >= 60_000
            status.text = if (delayed) tr("本地服务启动或停止仍未完成，请稍后重新检查。若持续无响应，可从系统设置停止应用后重新打开；已有会话会保留。", "The local service is still starting or stopping. Check again shortly. If it remains unresponsive, stop the app in Android settings and reopen it. Saved conversations are kept.") else if (uiEnglish()) when (AgentRuntime.phase) { AgentRuntime.Phase.STARTING -> "Starting the local service…"; AgentRuntime.Phase.STOPPING -> "Stopping the local service…"; AgentRuntime.Phase.FAILED -> "The local service could not start. Check Android permissions and try again."; else -> "Local service is stopped." } else AgentRuntime.detail
            retry.visibility = if (!waiting || delayed) View.VISIBLE else View.GONE
            retry.text = if (waiting) tr("重新检查状态", "Check status again") else tr("启动本地服务", "Start local service")
        }
    }

    override fun onStart() {
        super.onStart()
        DeviceBridge.attach(this)
        if (setupScreen) pollDeployment()
        if (::webView.isInitialized && !rendererGone) webView.onResume()
        observing = true
        setupView?.setActive(true)
        applyUiPreferences()
        observe.run()
    }

    override fun onStop() {
        DeviceBridge.detach(this)
        observing = false
        setupView?.setActive(false)
        AgentRuntime.main.removeCallbacks(observe)
        AgentRuntime.main.removeCallbacks(deploymentRefresh)
        if (::webView.isInitialized && !rendererGone) webView.onPause()
        super.onStop()
    }

    @Deprecated("Platform back callback retained for minSdk 24")
    override fun onBackPressed() {
        if (setupScreen) { handleSetupBack(); return }
        if (::webView.isInitialized && webView.visibility == View.VISIBLE && webView.canGoBack()) { invalidateDocumentAccess(); webView.goBack() }
        else super.onBackPressed()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("setup_screen", setupScreen)
        if (setupScreen) { outState.putString("setup_page", wizard.page.name); outState.putBoolean("setup_consent", wizard.consent); outState.putString("setup_channel", wizard.selectedChannel) }
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        UiPreferences.removeListener(uiListener)
        setupGeneration++
        invalidateDocumentAccess()
        observing = false
        setupView?.release()
        AgentRuntime.main.removeCallbacks(observe)
        AgentRuntime.main.removeCallbacks(deploymentRefresh)
        if (::webView.isInitialized) {
            transcriptBridge?.close()
            transcriptBridge = null
            webView.removeJavascriptInterface(TranscriptShareBridge.JS_NAME)
            if (!rendererGone) { webView.stopLoading(); webView.destroy() }
        }
        setupWorker.shutdownNow()
        super.onDestroy()
    }
}
