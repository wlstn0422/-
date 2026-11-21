package com.casenote.notes

import android.content.Context

/** 토큰과 저장소 정보를 이 휴대폰의 앱 전용 저장소에만 보관한다(백업 제외). */
class AppPrefs(context: Context) : RepoConfig {
    private val sp = context.getSharedPreferences("casenote", Context.MODE_PRIVATE)

    override val token: String get() = sp.getString(KEY_TOKEN, "")?.trim() ?: ""
    override val owner: String get() = value(KEY_OWNER, BuildConfig.REPO_OWNER)
    override val repo: String get() = value(KEY_REPO, BuildConfig.REPO_NAME)
    override val branch: String get() = value(KEY_BRANCH, BuildConfig.REPO_BRANCH)

    private fun value(key: String, default: String): String =
        sp.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() } ?: default

    fun save(token: String, owner: String, repo: String, branch: String) {
        sp.edit()
            .putString(KEY_TOKEN, token.trim())
            .putString(KEY_OWNER, owner.trim())
            .putString(KEY_REPO, repo.trim())
            .putString(KEY_BRANCH, branch.trim())
            .apply()
    }

    private companion object {
        const val KEY_TOKEN = "token"
        const val KEY_OWNER = "owner"
        const val KEY_REPO = "repo"
        const val KEY_BRANCH = "branch"
    }
}
