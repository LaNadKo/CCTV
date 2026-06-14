import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val releaseSigningProperties = Properties()
val releaseSigningPropertiesFile = rootProject.file("key.properties")
if (releaseSigningPropertiesFile.isFile) {
    releaseSigningPropertiesFile.inputStream().use { releaseSigningProperties.load(it) }
}

fun releaseSigningProperty(name: String, envName: String): String? {
    return (releaseSigningProperties.getProperty(name) ?: System.getenv(envName))
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
}

fun releaseBuildRequested(): Boolean {
    return gradle.startParameter.taskNames.any { it.contains("release", ignoreCase = true) }
}

android {
    namespace = "ru.cctv.cctv_console"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "ru.cctv.cctv_console"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            val storeFilePath = releaseSigningProperty("storeFile", "CCTV_ANDROID_STORE_FILE")
            val storePasswordValue = releaseSigningProperty("storePassword", "CCTV_ANDROID_STORE_PASSWORD")
            val keyAliasValue = releaseSigningProperty("keyAlias", "CCTV_ANDROID_KEY_ALIAS")
            val keyPasswordValue = releaseSigningProperty("keyPassword", "CCTV_ANDROID_KEY_PASSWORD")
            val missing = mutableListOf<String>()
            if (storeFilePath == null) missing.add("storeFile/CCTV_ANDROID_STORE_FILE")
            if (storePasswordValue == null) missing.add("storePassword/CCTV_ANDROID_STORE_PASSWORD")
            if (keyAliasValue == null) missing.add("keyAlias/CCTV_ANDROID_KEY_ALIAS")
            if (keyPasswordValue == null) missing.add("keyPassword/CCTV_ANDROID_KEY_PASSWORD")
            if (missing.isNotEmpty()) {
                if (releaseBuildRequested()) {
                    throw GradleException(
                        "Release signing is not configured: ${missing.joinToString(", ")}. " +
                            "Create android/key.properties or set the matching environment variables."
                    )
                }
                return@create
            }
            storeFile = file(requireNotNull(storeFilePath))
            storePassword = requireNotNull(storePasswordValue)
            keyAlias = requireNotNull(keyAliasValue)
            keyPassword = requireNotNull(keyPasswordValue)
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
