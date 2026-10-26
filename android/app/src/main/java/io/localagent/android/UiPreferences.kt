package io.localagent.android

import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.os.Looper
import android.view.View
import org.json.JSONObject

/** Python settings own these values; this local mirror controls native presentation only. */
internal data class UiPreferenceValues(
    val theme: String = "system",
    val fontSize: String = "md",
    val language: String = "zh"
) {
    val scale: Float get() = when (fontSize) { "xs" -> .84f; "sm" -> .92f; "lg" -> 1.12f; "xl" -> 1.24f; else -> 1f }
    fun text(chinese: String, english: String): String = if (language == "en") english else chinese
    fun dark(systemDark: Boolean): Boolean = theme == "dark" || (theme == "system" && systemDark)
    companion object {
        private val keys = setOf("ui_theme", "ui_font_size", "ui_language")
        fun parse(values: Map<String, Any?>): UiPreferenceValues {
            require(values.keys == keys) { "Expected ui_theme, ui_font_size and ui_language only" }
            val theme = values["ui_theme"]
            val size = values["ui_font_size"]
            val language = values["ui_language"]
            require(theme is String && theme in setOf("system", "light", "dark")) { "Invalid ui_theme" }
            require(size is String && size in setOf("xs", "sm", "md", "lg", "xl")) { "Invalid ui_font_size" }
            require(language is String && language in setOf("zh", "en")) { "Invalid ui_language" }
            return UiPreferenceValues(theme, size, language)
        }
    }
}

internal data class UiPalette(val background: Int, val surface: Int, val foreground: Int, val secondary: Int, val line: Int, val accent: Int, val onAccent: Int)

internal object UiPreferences {
    private const val PREFS = "native_ui_preferences"
    fun interface Listener { fun onUiPreferencesChanged() }
    private val listeners = linkedSetOf<Listener>() // Main-thread only; listeners detach with their Activity.
    fun read(context: Context): UiPreferenceValues {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return try { UiPreferenceValues.parse(mapOf(
            "ui_theme" to prefs.getString("ui_theme", "system"),
            "ui_font_size" to prefs.getString("ui_font_size", "md"),
            "ui_language" to prefs.getString("ui_language", "zh")
        )) } catch (_: Exception) { UiPreferenceValues() }
    }
    fun update(context: Context, payload: String) {
        require(payload.length <= 2048) { "UI preferences payload too large" }
        val json = JSONObject(payload)
        val values = UiPreferenceValues.parse(json.keys().asSequence().associateWith { json.get(it) })
        val app = context.applicationContext
        val apply = Runnable {
            if (read(app) == values) return@Runnable
            app.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("ui_theme", values.theme).putString("ui_font_size", values.fontSize)
                .putString("ui_language", values.language).apply()
            listeners.toList().forEach { it.onUiPreferencesChanged() }
        }
        if (Looper.myLooper() == Looper.getMainLooper()) apply.run() else AgentRuntime.main.post(apply)
    }
    fun addListener(listener: Listener) { check(Looper.myLooper() == Looper.getMainLooper()); listeners.add(listener) }
    fun removeListener(listener: Listener) { listeners.remove(listener) }
    fun palette(context: Context, values: UiPreferenceValues = read(context)): UiPalette = if (isDark(context, values))
        UiPalette(0xff11151b.toInt(), 0xff1b222b.toInt(), 0xffedf1f6.toInt(), 0xffaab4c3.toInt(), 0xff354151.toInt(), 0xffa9baff.toInt(), 0xff17233e.toInt())
    else UiPalette(0xfffbfcfe.toInt(), 0xfff1f4f9.toInt(), 0xff192432.toInt(), 0xff637186.toInt(), 0xffdce3ed.toInt(), 0xff4d66c6.toInt(), 0xffffffff.toInt())
    fun isDark(context: Context, values: UiPreferenceValues = read(context)): Boolean = values.dark(context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES)
    @Suppress("DEPRECATION")
    fun applyWindow(activity: Activity) {
        val values = read(activity)
        activity.setTheme(if (isDark(activity, values)) R.style.AppThemeDark else R.style.AppThemeLight)
        val colors = palette(activity, values)
        activity.window.statusBarColor = colors.background
        activity.window.navigationBarColor = colors.background
        val flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        activity.window.decorView.systemUiVisibility = if (isDark(activity, values)) activity.window.decorView.systemUiVisibility and flags.inv()
            else activity.window.decorView.systemUiVisibility or flags
        activity.window.decorView.setBackgroundColor(colors.background)
    }
}
