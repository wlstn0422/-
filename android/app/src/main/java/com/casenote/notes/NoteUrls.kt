package com.casenote.notes

/** 노트 주소 규칙. 앱 안의 웹뷰는 가상의 주소(appassets.androidplatform.net/notes/...)를 열고,
 *  그 요청을 가로채 GitHub 저장소의 docs/ 폴더에서 같은 경로의 파일을 읽어 온다. */
object NoteUrls {
    /** 안드로이드가 앱 내부 콘텐츠용으로 정해 둔 주소. 실제 인터넷으로 나가지 않는다. */
    const val HOST = "appassets.androidplatform.net"
    const val BASE = "https://$HOST/notes/"
    const val HOME = BASE + "index.html"
    const val SETTINGS_LINK = "casenote://settings"
    const val TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new"

    /** "/notes/daily/2026/x.html" → "daily/2026/x.html". 노트 경로가 아니거나 상위 폴더로 나가려 하면 null. */
    fun relativePath(path: String?): String? {
        val p = path ?: return null
        if (p != "/notes" && !p.startsWith("/notes/")) return null
        var rel = p.removePrefix("/notes").trimStart('/')
        if (rel.isEmpty() || rel.endsWith("/")) rel += "index.html"
        val parts = rel.split('/').filter { it.isNotEmpty() && it != "." }
        if (parts.isEmpty() || parts.any { it == ".." }) return null
        return parts.joinToString("/")
    }

    /** RFC 3986의 예약되지 않은 문자만 그대로 두고 나머지는 %XX로 바꾼다. */
    fun encodeSegment(s: String): String = buildString {
        for (b in s.toByteArray(Charsets.UTF_8)) {
            val c = b.toInt() and 0xff
            val ch = c.toChar()
            if (c < 128 && (ch.isLetterOrDigit() || ch == '-' || ch == '.' || ch == '_' || ch == '~')) {
                append(ch)
            } else {
                append('%').append("%02X".format(c))
            }
        }
    }

    fun encodePath(path: String): String = path.split('/').joinToString("/") { encodeSegment(it) }

    /** 토큰이 있으면 GitHub API(비공개 저장소), 없으면 raw.githubusercontent.com(공개 저장소)에서 읽는다. */
    fun request(config: RepoConfig, rel: String, etag: String?): HttpRequest {
        val headers = linkedMapOf("User-Agent" to "casenote-android")
        val url = if (config.token.isNotBlank()) {
            headers["Accept"] = "application/vnd.github.raw+json"
            headers["Authorization"] = "Bearer ${config.token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            "https://api.github.com/repos/${encodeSegment(config.owner)}/${encodeSegment(config.repo)}" +
                "/contents/docs/${encodePath(rel)}?ref=${encodeSegment(config.branch)}"
        } else {
            "https://raw.githubusercontent.com/${encodeSegment(config.owner)}/${encodeSegment(config.repo)}" +
                "/refs/heads/${encodePath(config.branch)}/docs/${encodePath(rel)}"
        }
        if (!etag.isNullOrBlank()) headers["If-None-Match"] = etag
        return HttpRequest(url, headers)
    }

    /** 캐시 파일 이름: 폴더 구분자를 밑줄로 바꾼다. */
    fun cacheName(rel: String): String = rel.replace('/', '_')

    fun mime(rel: String): String = when {
        rel.endsWith(".html") || rel.endsWith(".htm") -> "text/html"
        rel.endsWith(".css") -> "text/css"
        rel.endsWith(".js") -> "application/javascript"
        rel.endsWith(".json") -> "application/json"
        rel.endsWith(".png") -> "image/png"
        rel.endsWith(".svg") -> "image/svg+xml"
        else -> "application/octet-stream"
    }

    fun escape(s: String): String = s
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")

    /** 저장해 둔 노트를 보여 줄 때 맨 위에 안내 띠를 붙인다. */
    fun withBanner(html: ByteArray, message: String, settingsLink: Boolean = false): ByteArray {
        val text = String(html, Charsets.UTF_8)
        val link = if (settingsLink) " <a href=\"$SETTINGS_LINK\">설정 열기</a>" else ""
        val banner = "<div style=\"margin:12px 0;padding:10px 12px;border-radius:8px;background:#fff6e0;color:#3b2f0b;" +
            "border:1px solid #e8c46a;font-size:0.92rem\">${escape(message)}$link</div>"
        val anchor = listOf("<main", "<body").map { text.indexOf(it) }.firstOrNull { it >= 0 }
        val out = if (anchor != null) {
            val end = text.indexOf('>', anchor)
            if (end >= 0) text.substring(0, end + 1) + banner + text.substring(end + 1) else banner + text
        } else {
            banner + text
        }
        return out.toByteArray(Charsets.UTF_8)
    }
}
