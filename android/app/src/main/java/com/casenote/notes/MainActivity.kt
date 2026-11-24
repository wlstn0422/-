package com.casenote.notes

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import java.io.ByteArrayInputStream
import java.io.File

/** 매일 경영·경제 케이스 노트 뷰어. 위쪽 탭(오늘의 노트·캘린더·규모지도)으로 GitHub의 docs/ 페이지를 보여 준다. */
class MainActivity : AppCompatActivity() {

    private enum class Tab(val url: String) {
        TODAY(NoteUrls.TODAY),
        CALENDAR(NoteUrls.CALENDAR),
        SCALE(NoteUrls.SCALE),
    }

    private lateinit var webView: WebView
    private lateinit var swipe: SwipeRefreshLayout
    private lateinit var progress: ProgressBar
    private lateinit var prefs: AppPrefs
    private lateinit var source: NoteSource
    private lateinit var tabViews: Map<Tab, TextView>
    private var current = Tab.TODAY
    private var clearHistoryOnLoad = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        supportActionBar?.elevation = 0f  // 제목 줄과 탭 줄이 한 덩어리로 보이게

        prefs = AppPrefs(this)
        source = NoteSource(File(filesDir, "notes"), prefs)
        webView = findViewById(R.id.web)
        swipe = findViewById(R.id.swipe)
        progress = findViewById(R.id.progress)
        tabViews = mapOf(
            Tab.TODAY to findViewById(R.id.tab_today),
            Tab.CALENDAR to findViewById(R.id.tab_calendar),
            Tab.SCALE to findViewById(R.id.tab_scale),
        )
        tabViews.forEach { (tab, view) -> view.setOnClickListener { openTab(tab) } }

        webView.settings.apply {
            javaScriptEnabled = false
            domStorageEnabled = false
            allowFileAccess = false
            allowContentAccess = false
            builtInZoomControls = true
            displayZoomControls = false
            textZoom = (resources.configuration.fontScale * 100).toInt().coerceIn(80, 200)
        }
        webView.webViewClient = NotesClient()
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progress.progress = newProgress
                progress.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
            }
        }
        swipe.setOnRefreshListener { webView.reload() }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    webView.canGoBack() -> webView.goBack()
                    current != Tab.TODAY -> openTab(Tab.TODAY)  // 다른 탭에서는 먼저 오늘의 노트로
                    else -> finish()
                }
            }
        })

        val savedTab = savedInstanceState?.getString(STATE_TAB)?.let { name -> Tab.values().firstOrNull { it.name == name } }
        val restored = savedInstanceState != null && webView.restoreState(savedInstanceState) != null
        if (restored && savedTab != null) markTab(savedTab) else openTab(Tab.TODAY)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
        outState.putString(STATE_TAB, current.name)
    }

    /** 탭을 누르면 그 탭의 첫 화면을 연다. 이미 첫 화면이면 맨 위로 올린다. */
    private fun openTab(tab: Tab) {
        markTab(tab)
        if (webView.url == tab.url) {
            webView.scrollTo(0, 0)
            return
        }
        clearHistoryOnLoad = true  // 탭을 바꾸면 뒤로 가기는 그 탭 안에서만 움직인다
        webView.loadUrl(tab.url)
    }

    private fun markTab(tab: Tab) {
        current = tab
        tabViews.forEach { (t, v) -> v.isSelected = t == tab }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        R.id.action_refresh -> {
            webView.reload()
            true
        }
        R.id.action_settings -> {
            showSettings()
            true
        }
        else -> super.onOptionsItemSelected(item)
    }

    private inner class NotesClient : WebViewClient() {
        /** 웹뷰 백그라운드 스레드에서 불린다. 여기서 GitHub로 요청을 보내 페이지를 돌려준다. */
        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
            val url = request.url
            if (url.host != NoteUrls.HOST) return null
            val rel = NoteUrls.relativePath(url.path)
                ?: return WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), ByteArrayInputStream(ByteArray(0)))
            val page = source.load(rel)
            val body = if (page.mime == "text/html") NoteUrls.forApp(page.body) else page.body
            return WebResourceResponse(
                page.mime, "utf-8", 200, "OK",
                mapOf("Cache-Control" to "no-store"),
                ByteArrayInputStream(body),
            )
        }

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            if (url.scheme == "casenote") {
                showSettings()
                return true
            }
            if (url.host == NoteUrls.HOST) return false
            openExternal(url)
            return true
        }

        /** 뒤로 가기로 탭의 첫 화면에 돌아오면 그 탭에 표시를 옮긴다. */
        override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) {
            Tab.values().firstOrNull { it.url == url }?.let { markTab(it) }
        }

        override fun onPageFinished(view: WebView, url: String?) {
            swipe.isRefreshing = false
            if (clearHistoryOnLoad) {
                clearHistoryOnLoad = false
                view.clearHistory()
            }
        }
    }

    private fun openExternal(uri: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_app_to_open, Toast.LENGTH_SHORT).show()
        }
    }

    private fun showSettings() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
        }

        fun label(text: Int) = TextView(this).apply {
            setText(text)
            setPadding(0, pad / 2, 0, 0)
        }

        fun field(value: String, hidden: Boolean = false) = EditText(this).apply {
            setText(value)
            setSingleLine(true)
            inputType = if (hidden) {
                InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            } else {
                InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            }
        }

        val token = field(prefs.token, hidden = true).apply { hint = "github_pat_…" }
        val owner = field(prefs.owner)
        val repo = field(prefs.repo)
        val branch = field(prefs.branch)

        box.addView(TextView(this).apply { setText(R.string.settings_help) })
        box.addView(label(R.string.label_token))
        box.addView(token)
        box.addView(label(R.string.label_owner))
        box.addView(owner)
        box.addView(label(R.string.label_repo))
        box.addView(repo)
        box.addView(label(R.string.label_branch))
        box.addView(branch)

        AlertDialog.Builder(this)
            .setTitle(R.string.settings_title)
            .setView(ScrollView(this).apply { addView(box) })
            .setPositiveButton(R.string.save) { _, _ ->
                prefs.save(token.text.toString(), owner.text.toString(), repo.text.toString(), branch.text.toString())
                clearHistoryOnLoad = true
                webView.loadUrl(current.url)
            }
            .setNeutralButton(R.string.make_token) { _, _ -> openExternal(Uri.parse(NoteUrls.TOKEN_PAGE)) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private companion object {
        const val STATE_TAB = "tab"
    }
}
