package io.localagent.android

import org.junit.Assert.*
import org.junit.Test

class UiPreferenceValuesTest {
    private fun values(theme: Any? = "system", size: Any? = "md", language: Any? = "zh") =
        mapOf("ui_theme" to theme, "ui_font_size" to size, "ui_language" to language)
    @Test fun defaultAndExplicitThemesFollowTheSelectedPolicy() {
        val defaults = UiPreferenceValues.parse(values())
        assertFalse(defaults.dark(false)); assertTrue(defaults.dark(true))
        assertFalse(UiPreferenceValues.parse(values("light")).dark(true))
        assertTrue(UiPreferenceValues.parse(values("dark")).dark(false))
        assertEquals(1f, defaults.scale, 0f)
    }
    @Test fun fiveFontSizesMatchWebScales() {
        val scales = listOf("xs" to .84f, "sm" to .92f, "md" to 1f, "lg" to 1.12f, "xl" to 1.24f)
        scales.forEach { (size, scale) -> assertEquals(scale, UiPreferenceValues.parse(values(size = size)).scale, .0001f) }
    }
    @Test fun interfaceLanguageChoosesLabelsOnly() {
        assertEquals("中文", UiPreferenceValues.parse(values()).text("中文", "English"))
        assertEquals("English", UiPreferenceValues.parse(values(language = "en")).text("中文", "English"))
    }
    @Test fun invalidDisplayPayloadsAndAuthorityFieldsAreRejected() {
        val cases = listOf(values(theme = "automatic"), values(theme = true), values(size = 2), values(size = "huge"),
            values(language = null), values(language = "fr"), values() + ("full_access" to true), values() - "ui_theme")
        cases.forEach { candidate ->
            try { UiPreferenceValues.parse(candidate); fail("Invalid display payload was accepted") }
            catch (_: IllegalArgumentException) { }
        }
    }
}
