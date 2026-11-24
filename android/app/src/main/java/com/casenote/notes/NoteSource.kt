package com.casenote.notes

import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64

/** 노트를 읽어 올 저장소 정보. */
interface RepoConfig {
    val token: String
    val owner: String
    val repo: String
    val branch: String
}

data class HttpRequest(val url: String, val headers: Map<String, String>)

class HttpResponse(val code: Int, val body: ByteArray, val etag: String?)

fun interface Fetcher {
    @Throws(IOException::class)
    fun fetch(request: HttpRequest): HttpResponse
}

/** 안드로이드 기본 HTTP 클라이언트로 요청한다(추가 라이브러리 없이). */
class HttpFetcher : Fetcher {
    override fun fetch(request: HttpRequest): HttpResponse {
        val conn = URL(request.url).openConnection() as HttpURLConnection
        conn.connectTimeout = 10_000
        conn.readTimeout = 20_000
        conn.instanceFollowRedirects = true
        conn.useCaches = false
        request.headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.use { it.readBytes() } ?: ByteArray(0)
            return HttpResponse(code, body, conn.getHeaderField("ETag"))
        } finally {
            conn.disconnect()
        }
    }
}

/** 노트 한 페이지를 내려받고, 받은 페이지는 휴대폰에 저장해 두었다가 인터넷이 없을 때 대신 보여 준다. */
class NoteSource(
    private val cacheDir: File,
    private val config: RepoConfig,
    private val fetcher: Fetcher = HttpFetcher(),
) {
    class Page(val body: ByteArray, val mime: String)

    @Synchronized
    fun load(rel: String): Page {
        val mime = NoteUrls.mime(rel)
        val cacheFile = File(cacheDir, NoteUrls.cacheName(rel))
        val etagFile = File(cacheDir, NoteUrls.cacheName(rel) + ".etag")
        val cached: ByteArray? = if (cacheFile.exists()) cacheFile.readBytes() else null
        val etag: String? = if (cached != null && etagFile.exists()) etagFile.readText().trim() else null
        val isHtml = mime == "text/html"
        return try {
            val res = fetcher.fetch(NoteUrls.request(config, rel, etag))
            when {
                res.code in 200..299 -> {
                    val body = unwrap(res.body)
                    cacheDir.mkdirs()
                    cacheFile.writeBytes(body)
                    if (res.etag.isNullOrBlank()) etagFile.delete() else etagFile.writeText(res.etag)
                    Page(body, mime)
                }
                res.code == 304 && cached != null -> Page(cached, mime)
                !isHtml -> Page(cached ?: ByteArray(0), mime)
                cached != null -> Page(NoteUrls.withBanner(cached, ErrorPages.bannerFor(res.code, config), settingsLink = true), mime)
                else -> Page(ErrorPages.forStatus(res.code, rel, config).toByteArray(Charsets.UTF_8), "text/html")
            }
        } catch (e: IOException) {
            when {
                !isHtml -> Page(cached ?: ByteArray(0), mime)  // 스타일 파일 등은 저장본을 그대로
                cached != null -> Page(NoteUrls.withBanner(cached, "인터넷에 연결되어 있지 않아 저장해 둔 노트를 표시합니다."), mime)
                else -> Page(ErrorPages.offline().toByteArray(Charsets.UTF_8), "text/html")
            }
        }
    }

    /** GitHub가 원문 대신 JSON(파일 정보 + base64 내용)으로 답한 경우 내용을 풀어낸다.
     *  내용이 비어 있으면(큰 파일) 함께 온 내려받기 주소에서 원문을 다시 받는다. 원문이면 그대로 돌려준다. */
    private fun unwrap(body: ByteArray): ByteArray {
        val text = String(body, Charsets.UTF_8).trimStart()
        if (!text.startsWith("{") || !text.contains("\"encoding\"")) return body
        val content = JSON_CONTENT.find(text)?.groupValues?.get(1)
            ?.replace("\\n", "")?.replace("\\r", "")?.replace("\\/", "/")
        if (!content.isNullOrEmpty()) {
            try {
                return Base64.getMimeDecoder().decode(content)
            } catch (e: IllegalArgumentException) {
                // 아래 내려받기 주소로 넘어간다
            }
        }
        val download = JSON_DOWNLOAD.find(text)?.groupValues?.get(1)?.replace("\\/", "/")
        if (download != null && download.startsWith("https://")) {
            val res = fetcher.fetch(HttpRequest(download, mapOf("User-Agent" to "casenote-android")))
            if (res.code in 200..299) return res.body
        }
        return body
    }

    private companion object {
        val JSON_CONTENT = Regex("\"content\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")
        val JSON_DOWNLOAD = Regex("\"download_url\"\\s*:\\s*\"([^\"]+)\"")
    }
}
