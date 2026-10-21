import java.util.Properties

plugins {
    id("com.android.application")
}

// Release signing. The key never goes in the repo: its location and passwords
// come from environment variables (GitHub Actions fills these from secrets) or,
// on your own PC, from android/keystore.properties (gitignored):
//
//   storeFile=C:/Users/you/tiltwheel-release.jks
//   storePassword=...
//   keyAlias=tiltwheel
//   keyPassword=...
//
// With neither, `assembleRelease` still builds, just unsigned.
val keystoreProps = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun signingValue(env: String, prop: String): String? =
    System.getenv(env)?.takeIf { it.isNotBlank() } ?: keystoreProps.getProperty(prop)

val releaseStoreFile = signingValue("TILTWHEEL_STORE_FILE", "storeFile")

// Version from the release tag (CI passes -PversionName=1.2.3); local builds
// stay at the dev version. versionCode must go up for Android to install an
// update over the old app, so it's derived from the version: 1.2.3 -> 10203.
val appVersionName = (findProperty("versionName") as String?)?.removePrefix("v") ?: "0.1"
val appVersionCode = appVersionName.split(".").map { it.toIntOrNull() ?: 0 }
    .let { (it + listOf(0, 0, 0)).take(3) }
    .let { (major, minor, patch) -> major * 10000 + minor * 100 + patch }
    .coerceAtLeast(1)

android {
    namespace = "com.tiltwheel.controller"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.tiltwheel.controller"
        minSdk = 26
        targetSdk = 37
        versionCode = appVersionCode
        versionName = appVersionName
    }

    signingConfigs {
        if (releaseStoreFile != null) {
            create("release") {
                storeFile = file(releaseStoreFile)
                storePassword = signingValue("TILTWHEEL_STORE_PASSWORD", "storePassword")
                keyAlias = signingValue("TILTWHEEL_KEY_ALIAS", "keyAlias")
                keyPassword = signingValue("TILTWHEEL_KEY_PASSWORD", "keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

// No AndroidX: the app only uses the framework, so there's nothing to keep up to date.
dependencies {
    testImplementation("junit:junit:4.13.2")
}
