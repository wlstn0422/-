plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 서명 키는 GitHub Actions가 만들어 캐시에 보관한다(저장소에 올리지 않는다). 없으면 서명하지 않은 빌드가 나온다.
val keystorePath: String? = System.getenv("CASENOTE_KEYSTORE")
val runNumber: Int = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toIntOrNull() ?: 1

android {
    namespace = "com.casenote.notes"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.casenote.notes"
        minSdk = 26
        targetSdk = 34
        versionCode = runNumber
        versionName = "1.0.$runNumber"
        // 노트를 읽어 올 기본 저장소. 앱의 설정 화면에서 바꿀 수 있다.
        buildConfigField("String", "REPO_OWNER", "\"wlstn0422\"")
        buildConfigField("String", "REPO_NAME", "\"-\"")
        buildConfigField("String", "REPO_BRANCH", "\"claude/business-case-learning-automation-943oyj\"")
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("CASENOTE_KEYSTORE_PASSWORD")
                keyAlias = "casenote"
                keyPassword = System.getenv("CASENOTE_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePath != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    testImplementation("junit:junit:4.13.2")
}
