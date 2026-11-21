package com.casenote.notes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files

class NoteSourceTest {

    private data class Cfg(
        override val token: String,
        override val owner: String = "wlstn0422",
        override val repo: String = "-",
        override val branch: String = "claude/business-case-learning-automation-943oyj",
    ) : RepoConfig

    @Test
    fun relativePathMapsNotesPaths() {
        assertEquals("index.html", NoteUrls.relativePath("/notes/"))
        assertEquals("index.html", NoteUrls.relativePath("/notes"))
        assertEquals("daily/2026/2026-11-21.html", NoteUrls.relativePath("/notes/daily/2026/2026-11-21.html"))
        assertEquals("theories.html", NoteUrls.relativePath("/notes/theories.html"))
        assertNull(NoteUrls.relativePath("/notes/../secret"))
        assertNull(NoteUrls.relativePath("/favicon.ico"))
    }

    @Test
    fun privateRepoUsesContentsApiWithToken() {
        val req = NoteUrls.request(Cfg(token = "github_pat_x"), "daily/2026/2026-11-21.html", "\"abc\"")
        assertEquals(
            "https://api.github.com/repos/wlstn0422/-/contents/docs/daily/2026/2026-11-21.html" +
                "?ref=claude%2Fbusiness-case-learning-automation-943oyj",
            req.url,
        )
        assertEquals("Bearer github_pat_x", req.headers["Authorization"])
        assertEquals("application/vnd.github.raw+json", req.headers["Accept"])
        assertEquals("\"abc\"", req.headers["If-None-Match"])
    }

    @Test
    fun publicRepoUsesRawUrlWithoutToken() {
        val req = NoteUrls.request(Cfg(token = ""), "index.html", null)
        assertEquals(
            "https://raw.githubusercontent.com/wlstn0422/-/refs/heads/claude/business-case-learning-automation-943oyj/docs/index.html",
            req.url,
        )
        assertNull(req.headers["Authorization"])
    }

    @Test
    fun bannerGoesInsideMain() {
        val html = "<html><body><main class=\"wrap\"><h1>노트</h1></main></body></html>".toByteArray()
        val out = String(NoteUrls.withBanner(html, "저장된 노트", settingsLink = true), Charsets.UTF_8)
        assertTrue(out.indexOf("저장된 노트") > out.indexOf("<main"))
        assertTrue(out.indexOf("저장된 노트") < out.indexOf("<h1>"))
        assertTrue(out.contains(NoteUrls.SETTINGS_LINK))
    }

    @Test
    fun cachesPagesAndFallsBackWhenOffline() {
        val dir = Files.createTempDirectory("notes").toFile()
        var online = true
        var calls = 0
        val fetcher = Fetcher { req ->
            calls++
            if (!online) throw IOException("offline")
            if (req.headers["If-None-Match"] == "\"v1\"") HttpResponse(304, ByteArray(0), "\"v1\"")
            else HttpResponse(200, "<html><body><main>오늘 노트</main></body></html>".toByteArray(), "\"v1\"")
        }
        val source = NoteSource(dir, Cfg(token = "t"), fetcher)
        assertTrue(String(source.load("index.html").body).contains("오늘 노트"))
        assertTrue(File(dir, "index.html.etag").exists())
        // 바뀐 것이 없으면(304) 저장해 둔 페이지를 그대로 쓴다
        assertTrue(String(source.load("index.html").body).contains("오늘 노트"))
        // 인터넷이 끊기면 저장해 둔 페이지에 안내 띠를 붙여 보여 준다
        online = false
        val offline = String(source.load("index.html").body)
        assertTrue(offline.contains("오늘 노트") && offline.contains("인터넷에 연결되어 있지 않아"))
        assertEquals(3, calls)
    }

    @Test
    fun unwrapsJsonContentWhenGithubDoesNotSendRawFile() {
        val dir = Files.createTempDirectory("notes").toFile()
        val html = "<html><body><main>오늘의 공시 사례</main></body></html>"
        val b64 = java.util.Base64.getMimeEncoder(60, "\n".toByteArray()).encodeToString(html.toByteArray())
        val json = "{\"name\":\"index.html\",\"encoding\":\"base64\",\"content\":\"" +
            b64.replace("\n", "\\n") + "\",\"download_url\":null}"
        val source = NoteSource(dir, Cfg(token = "t"), Fetcher { HttpResponse(200, json.toByteArray(), "\"e\"") })
        assertEquals(html, String(source.load("index.html").body, Charsets.UTF_8))
        // 내용이 비어 있으면(큰 파일) 내려받기 주소에서 원문을 받는다
        val big = "{\"encoding\":\"none\",\"content\":\"\",\"download_url\":\"https:\\/\\/raw.example\\/x.html?token=abc\"}"
        val source2 = NoteSource(dir, Cfg(token = "t"), Fetcher { req ->
            if (req.url.startsWith("https://raw.example/x.html")) HttpResponse(200, html.toByteArray(), null)
            else HttpResponse(200, big.toByteArray(), null)
        })
        assertEquals(html, String(source2.load("theories.html").body, Charsets.UTF_8))
    }

    @Test
    fun explainsMissingTokenForPrivateRepo() {
        val dir = Files.createTempDirectory("notes").toFile()
        val source = NoteSource(dir, Cfg(token = ""), Fetcher { HttpResponse(404, ByteArray(0), null) })
        val page = String(source.load("index.html").body)
        assertTrue(page.contains("GitHub 토큰을 입력해 주세요"))
        assertTrue(page.contains(NoteUrls.TOKEN_PAGE))
        val bad = NoteSource(dir, Cfg(token = "old"), Fetcher { HttpResponse(401, ByteArray(0), null) })
        assertTrue(String(bad.load("theories.html").body).contains("토큰이 만료"))
    }
}
