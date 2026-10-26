plugins { id("com.android.library") }
android {
    namespace = "com.termux.view"
    buildToolsVersion = "37.0.0"
    compileSdk = 37
    compileSdkMinor = 2
    defaultConfig { minSdk = 29 }
    sourceSets.getByName("main") {
        java.setSrcDirs(listOf("../vendor/termux/source/termux-app-0.118.3/terminal-view/src/main/java"))
        res.setSrcDirs(listOf("../vendor/termux/source/termux-app-0.118.3/terminal-view/src/main/res"))
        manifest.srcFile("../vendor/termux/source/termux-app-0.118.3/terminal-view/src/main/AndroidManifest.xml")
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
dependencies { api(project(":terminal-emulator")); implementation("androidx.annotation:annotation:1.9.1") }
