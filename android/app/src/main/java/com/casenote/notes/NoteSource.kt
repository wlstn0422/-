package com.casenote.notes

import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

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
                    cacheDir.mkdirs()
                    cacheFile.writeBytes(res.body)
                    if (res.etag.isNullOrBlank()) etagFile.delete() else etagFile.writeText(res.etag)
                    Page(res.body, mime)
                }
                res.code == 304 && cached != null -> Page(cached, mime)
                !isHtml -> Page(ByteArray(0), mime)
                cached != null -> Page(NoteUrls.withBanner(cached, ErrorPages.bannerFor(res.code, config), settingsLink = true), mime)
                else -> Page(ErrorPages.forStatus(res.code, rel, config).toByteArray(Charsets.UTF_8), "text/html")
            }
        } catch (e: IOException) {
            when {
                !isHtml -> Page(ByteArray(0), mime)
                cached != null -> Page(NoteUrls.withBanner(cached, "인터넷에 연결되어 있지 않아 저장해 둔 노트를 표시합니다."), mime)
                else -> Page(ErrorPages.offline().toByteArray(Charsets.UTF_8), "text/html")
            }
        }
    }
}
