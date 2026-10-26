import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

val releaseStore = System.getenv("AGENT_KEYSTORE")?.takeIf { it.isNotBlank() }
val allowDebugReleaseSigning = System.getenv("AGENT_ALLOW_DEBUG_RELEASE_SIGNING") == "1"

android {
    namespace = "io.localagent.android"
    buildFeatures { aidl = true; compose = true }
    // Compile against the installed SDK; supported devices are API 29..37 (Android 10..17).
    // target 28 is required for Termux private-prefix exec on Android 10+. Not Play-target-37 compliant.
    compileSdk = 37
    compileSdkMinor = 2
    buildToolsVersion = "37.0.0"

    defaultConfig {
        applicationId = "com.termux"
        minSdk = 29
        targetSdk = 28
        versionCode = 10308
        versionName = "1.3.8"
        ndk { abiFilters += listOf("arm64-v8a") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    signingConfigs {
        getByName("debug") { enableV2Signing = true; enableV3Signing = true }
        create("ownerRelease") {
            if (releaseStore != null) {
                check(file(releaseStore).isFile) { "AGENT_KEYSTORE must point to an existing release keystore" }
                val storePassword = System.getenv("AGENT_STORE_PASSWORD")
                val keyAlias = System.getenv("AGENT_KEY_ALIAS")
                val keyPassword = System.getenv("AGENT_KEY_PASSWORD")
                check(!storePassword.isNullOrBlank() && !keyAlias.isNullOrBlank() && !keyPassword.isNullOrBlank()) {
                    "AGENT_STORE_PASSWORD, AGENT_KEY_ALIAS and AGENT_KEY_PASSWORD are required for release signing"
                }
                storeFile = file(releaseStore)
                this.storePassword = storePassword
                this.keyAlias = keyAlias
                this.keyPassword = keyPassword
            }
            enableV2Signing = true; enableV3Signing = true
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (releaseStore != null) signingConfigs.getByName("ownerRelease") else signingConfigs.getByName("debug")
        }
    }
    // Sideloaded Termux fork: target28 is deliberately required for private-prefix exec.
    // Do not raise this to satisfy Play lint without replacing/rebuilding the entire runtime.
    lint { disable += "ExpiredTargetSdkVersion" }
    packaging { jniLibs { useLegacyPackaging = true; keepDebugSymbols += "**/libtermux.so" } }

}
dependencies {
    implementation(project(":terminal-view"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3:1.3.2")
    implementation("androidx.annotation:annotation:1.9.1")

    implementation("androidx.work:work-runtime:2.10.5")
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

// Stage only reviewed app code and UI assets, never the whole repository.
val preparedPython = layout.buildDirectory.dir("generated/embeddedPython")
val stageEmbeddedSources by tasks.registering(Sync::class) {
    from(rootProject.file("..")) {
        include("android_agent/**/*.py", "web/index.html", "web/static/**")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    into(preparedPython)
    doFirst {
        check(rootProject.file("../android_agent/android_runtime.py").isFile) {
            "Missing android_agent/android_runtime.py: implement start(files_dir, port), launch_url() and stop()."
        }
        check(rootProject.file("../web/index.html").isFile) { "Missing web/index.html" }
    }
}
chaquopy {
    defaultConfig {
        version = "3.13"
        // Real module paths keep server.py's sibling ../web lookup working.
        extractPackages("android_agent")
        // All app dependencies are stdlib: no build-machine Python or pip required.
        pyc {
            src = false
            pip = false
            stdlib = false
        }
    }
    sourceSets.getByName("main") { setSrcDirs(listOf(preparedPython)) }
}
val verifyTermuxArtifacts by tasks.registering {
    val pinned = mapOf(
        "src/main/assets/termux/bootstrap-aarch64.zip" to "c8d702b6f742935001c37cda81b8ac69504a95d5cf28f2899532dd8cd4b057eb",
        "src/main/jniLibs/arm64-v8a/libtermux.so" to "41fad4b73caa033dc4b3de113f743efbd0039af6889ae7dd40ecb739fef17242"
    )
    inputs.files(pinned.keys.map { file(it) })
    doLast {
        val manifest = groovy.json.JsonSlurper().parseText(rootProject.file("vendor/termux/SOURCE-SHA256.json").readText().removePrefix("\uFEFF")) as List<*>
        manifest.forEach { entry ->
            val record = entry as Map<*, *>
            val source = rootProject.file("vendor/termux/source/termux-app-0.118.3/" + record["path"])
            val digest = MessageDigest.getInstance("SHA-256").digest(source.readBytes()).joinToString("") { "%02x".format(it) }
            check(digest == record["sha256"]) { "Vendored Termux source changed: " + record["path"] }
        }
        pinned.forEach { (path, expected) ->
            val digest = MessageDigest.getInstance("SHA-256")
            file(path).inputStream().use { input -> val buffer = ByteArray(65536); while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) } }
            check(digest.digest().joinToString("") { "%02x".format(it) } == expected) { "Pinned Termux artifact mismatch: " + path }
        }
    }
}

tasks.configureEach {
    if (name == "validateSigningRelease") {
        outputs.upToDateWhen { false }
        doFirst {
            check(releaseStore != null || allowDebugReleaseSigning) {
                "Production release signing is unavailable: set AGENT_KEYSTORE and its credentials; use AGENT_ALLOW_DEBUG_RELEASE_SIGNING=1 only for explicit development builds"
            }
        }
    }
    if (name.contains("Python") || name == "preBuild") {
        dependsOn(stageEmbeddedSources)
        if (name == "preBuild") dependsOn(verifyTermuxArtifacts)
    }
}
