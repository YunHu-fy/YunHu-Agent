package io.localagent.android

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Complete locally bundled legal texts; available offline, without a WebView bridge. */
class LicensesActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        UiPreferences.applyWindow(this)
        super.onCreate(savedInstanceState)
        val ui = UiPreferences.read(this)
        val colors = UiPreferences.palette(this, ui)
        title = ui.text("许可与说明", "Licenses & notices")
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(20, 20, 20, 20); setBackgroundColor(colors.background) }
        val text = TextView(this).apply { textSize = 13f * ui.scale; setTextColor(colors.foreground); setTextIsSelectable(true) }
        val scroll = ScrollView(this).apply { addView(text) }
        val tabs = LinearLayout(this)
        for ((label, file) in listOf("NOTICE" to "NOTICE.txt", "GPL v3" to "GPL-3.0.txt", "Apache 2" to "Apache-2.0.txt", "Lottie" to "Lottie-MIT.txt")) tabs.addView(Button(this).apply {
            this.text = label
            textSize = 12f * ui.scale; setTextColor(colors.foreground)
            setOnClickListener { text.text = assets.open("licenses/"+file).bufferedReader().use { it.readText() }; scroll.scrollTo(0,0) }
        }, LinearLayout.LayoutParams(0,-2,1f))
        root.addView(tabs); root.addView(scroll, LinearLayout.LayoutParams(-1,0,1f)); setContentView(root)
        text.text = assets.open("licenses/NOTICE.txt").bufferedReader().use { it.readText() }
    }
}
