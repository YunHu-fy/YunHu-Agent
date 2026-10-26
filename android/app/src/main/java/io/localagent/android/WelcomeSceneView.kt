package io.localagent.android

import android.animation.ValueAnimator
import android.content.Context
import android.database.ContentObserver
import android.graphics.Color
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView

/** Offline eZ artwork above an independent, lifecycle-bound bilingual greeting. */
internal class WelcomeSceneView(context: Context, scale: Float, color: Int) : FrameLayout(context) {
    private val appContext = context.applicationContext
    private val artwork = WebView(context).apply {
        setBackgroundColor(Color.TRANSPARENT)
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        overScrollMode = View.OVER_SCROLL_NEVER
        isVerticalScrollBarEnabled = false
        isHorizontalScrollBarEnabled = false
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = false
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        settings.javaScriptCanOpenWindowsAutomatically = false
        settings.setSupportZoom(false)
        settings.blockNetworkLoads = true
        webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) { updateArtwork() }
        }
        val animationData = assetText("welcome/eZ.json")
        val renderer = assetText("welcome/lottie.min.js")
        val html = assetText("welcome/eZ.html")
            .replace("<script src=\"lottie.min.js\"></script>", "<script>" + renderer + "</script>")
            .replace("path: 'eZ.json',", "animationData: " + animationData + ",")
        loadDataWithBaseURL("https://welcome.yunhu.invalid/", html, "text/html", "UTF-8", null)
    }
    private val greeting = TextView(context).apply {
        textSize = 42f * scale
        setTextColor(color)
        gravity = Gravity.CENTER
        textDirection = View.TEXT_DIRECTION_LTR
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        includeFontPadding = false
        contentDescription = "你好，hello"
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
    }
    private var active = false
    private var released = false
    private var observerAttached = false
    private var typing: ValueAnimator? = null
    private var elapsed = 0L
    private var lastGreeting: String? = null
    private val motionObserver = object : ContentObserver(Handler(Looper.getMainLooper())) {
        override fun onChange(selfChange: Boolean) { updatePlayback() }
    }

    init {
        addView(artwork, LayoutParams(-1, -1, Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        addView(greeting, LayoutParams(-1, dp(96), Gravity.CENTER))
        showGreeting(WelcomeGreeting.frame(0))
        artwork.addOnLayoutChangeListener { _, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom ->
            if (!released && right > left && bottom > top && (right - left != oldRight - oldLeft || bottom - top != oldBottom - oldTop)) {
                artwork.evaluateJavascript("window.resizeWelcomeArtwork && window.resizeWelcomeArtwork();", null)
            }
        }
    }
    private fun assetText(name: String): String = appContext.assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun shouldAnimate() = active && isAttachedToWindow && windowVisibility == VISIBLE && motionAllowed(context)
    private fun updateArtwork() {
        if (released || !isAttachedToWindow) return
        val enabled = if (shouldAnimate()) "true" else "false"
        val reduced = if (motionAllowed(context)) "false" else "true"
        artwork.evaluateJavascript("window.setWelcomeMotion && window.setWelcomeMotion($enabled, $reduced);", null)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        val textHeight = minOf(dp(96), h)
        val gap = minOf(dp(24), (h - textHeight).coerceAtLeast(0))
        val artHeight = minOf((h * .50f).toInt(), (h - textHeight - gap).coerceAtLeast(0))
        val artLift = minOf(dp(16), (h * .03f).toInt(), artHeight)
        artwork.layoutParams = LayoutParams(-1, artHeight, Gravity.TOP or Gravity.CENTER_HORIZONTAL)
        artwork.translationY = -artLift.toFloat()
        greeting.layoutParams = LayoutParams(-1, textHeight, Gravity.TOP).apply {
            val preferredTop = (h * .70f).toInt() - textHeight / 2
            topMargin = maxOf(preferredTop, artHeight - artLift + gap).coerceIn(0, (h - textHeight).coerceAtLeast(0))
        }
    }
    fun setActive(value: Boolean) {
        if (released) return
        active = value
        if (value) artwork.onResume()
        updatePlayback()
        if (!value) artwork.onPause()
    }
    fun release() {
        if (released) return
        setActive(false)
        typing?.cancel(); typing = null
        if (observerAttached) { context.contentResolver.unregisterContentObserver(motionObserver); observerAttached = false }
        released = true
        removeView(artwork)
        artwork.stopLoading()
        artwork.destroy()
    }
    private fun showGreeting(value: String) {
        if (lastGreeting == value) return
        lastGreeting = value
        val full = when {
            value.isEmpty() -> ""
            "你好".startsWith(value) -> "你好"
            "hello".startsWith(value) -> "hello"
            else -> value
        }
        greeting.text = android.text.SpannableString(full).apply {
            if (value.length < full.length) setSpan(android.text.style.ForegroundColorSpan(Color.TRANSPARENT), value.length, full.length, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
    }
    private fun updatePlayback() {
        if (released) return
        updateArtwork()
        val run = shouldAnimate()
        if (!run) {
            typing?.let { elapsed = it.currentPlayTime; it.cancel() }
            typing = null
            if (!motionAllowed(context)) showGreeting("你好 / hello")
            return
        }
        if (typing != null) return
        val position = elapsed
        typing = ValueAnimator.ofInt(0, WelcomeGreeting.CYCLE_MS.toInt()).apply {
            duration = WelcomeGreeting.CYCLE_MS
            repeatCount = ValueAnimator.INFINITE
            interpolator = android.view.animation.LinearInterpolator()
            addUpdateListener { showGreeting(WelcomeGreeting.frame((it.animatedValue as Int).toLong())) }
            start()
            currentPlayTime = position
        }
    }
    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        artwork.onResume()
        if (!observerAttached) {
            context.contentResolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, motionObserver)
            observerAttached = true
        }
        updatePlayback()
    }
    override fun onDetachedFromWindow() {
        if (!released) {
            artwork.evaluateJavascript("window.setWelcomeMotion && window.setWelcomeMotion(false);", null)
            artwork.onPause()
        }
        typing?.let { elapsed = it.currentPlayTime; it.cancel() }
        typing = null
        if (observerAttached) {
            context.contentResolver.unregisterContentObserver(motionObserver)
            observerAttached = false
        }
        super.onDetachedFromWindow()
    }
    override fun onWindowVisibilityChanged(visibility: Int) { super.onWindowVisibilityChanged(visibility); updatePlayback() }
    companion object {
        fun motionAllowed(context: Context): Boolean = ValueAnimator.areAnimatorsEnabled() && try {
            Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) > 0f
        } catch (_: Exception) { false }
    }
}
