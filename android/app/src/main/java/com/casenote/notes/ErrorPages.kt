package com.casenote.notes

/** 노트를 불러오지 못했을 때 보여 주는 안내 화면. */
object ErrorPages {
    private fun page(title: String, body: String): String = """
        <!doctype html><html lang="ko"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>${NoteUrls.escape(title)}</title>
        <style>
        :root { --bg:#fbfaf7; --text:#1d1f23; --muted:#5d636e; --accent:#1f5f8b; --line:#e4e1da; }
        @media (prefers-color-scheme: dark) { :root { --bg:#15171b; --text:#e6e6e3; --muted:#a2a7b0; --accent:#7db7e0; --line:#2e3238; } }
        body { margin:0; padding:24px 18px 48px; background:var(--bg); color:var(--text); line-height:1.7;
               font-family:-apple-system,"Noto Sans KR",sans-serif; word-break:keep-all; }
        h1 { font-size:1.3rem; margin:8px 0 12px; }
        ol { padding-left:20px; } li { margin:6px 0; }
        .btn { display:block; margin:12px 0; padding:12px 14px; border-radius:10px; text-align:center;
               background:var(--accent); color:#fff; text-decoration:none; font-weight:600; }
        .btn.sub { background:transparent; color:var(--accent); border:1px solid var(--accent); }
        .note { color:var(--muted); font-size:0.9rem; border-top:1px solid var(--line); padding-top:12px; margin-top:20px; }
        </style></head><body><h1>${NoteUrls.escape(title)}</h1>$body</body></html>
    """.trimIndent()

    private val tokenSteps = """
        <ol>
        <li>아래 '토큰 만들기'를 누르고 GitHub에 로그인합니다.</li>
        <li>Token name에 casenote-app처럼 알아보기 쉬운 이름을 넣고, Expiration은 길게(예: 1년) 정합니다.</li>
        <li>Repository access에서 <b>Only select repositories</b>를 고르고 노트 저장소를 선택합니다.</li>
        <li>Permissions의 Repository permissions에서 <b>Contents</b>를 <b>Read-only</b>로 바꿉니다.</li>
        <li>Generate token을 누른 뒤 나온 토큰(github_pat_로 시작)을 복사합니다.</li>
        <li>이 앱으로 돌아와 '설정 열기'에 붙여 넣고 저장합니다.</li>
        </ol>
        <a class="btn" href="${NoteUrls.TOKEN_PAGE}">토큰 만들기</a>
        <a class="btn sub" href="${NoteUrls.SETTINGS_LINK}">설정 열기</a>
        <p class="note">토큰은 이 휴대폰에만 저장되며 노트 저장소를 읽는 데만 씁니다. 휴대폰을 잃어버리면 GitHub의 같은 화면에서 토큰을 삭제하면 됩니다.</p>
    """.trimIndent()

    fun needToken(): String = page(
        "GitHub 토큰을 입력해 주세요",
        "<p>케이스 노트 저장소는 비공개라서, 앱이 노트를 읽으려면 본인 계정의 <b>읽기 전용 토큰</b>이 한 번 필요합니다.</p>$tokenSteps",
    )

    fun badToken(): String = page(
        "토큰이 만료되었거나 올바르지 않습니다",
        "<p>GitHub가 토큰을 받아들이지 않았습니다. 새 토큰을 만들어 다시 입력해 주세요.</p>$tokenSteps",
    )

    fun notFound(rel: String, config: RepoConfig): String = page(
        "노트를 찾지 못했습니다",
        """
        <p>요청한 파일(${NoteUrls.escape(rel)})이 저장소에 없거나, 토큰에 이 저장소를 읽을 권한이 없습니다.</p>
        <ol>
        <li>토큰을 만들 때 저장소(${NoteUrls.escape(config.owner)}/${NoteUrls.escape(config.repo)})를 선택했는지 확인합니다.</li>
        <li>Contents 권한이 Read-only 이상인지 확인합니다.</li>
        <li>설정의 저장소 이름과 브랜치가 맞는지 확인합니다.</li>
        </ol>
        <a class="btn" href="${NoteUrls.SETTINGS_LINK}">설정 열기</a>
        <a class="btn sub" href="${NoteUrls.HOME}">전체 노트로 가기</a>
        """.trimIndent(),
    )

    fun forbidden(): String = page(
        "GitHub가 요청을 거절했습니다",
        """
        <p>토큰 권한이 부족하거나, 잠시 동안 요청이 너무 많았습니다(시간당 한도). 잠시 뒤 화면을 아래로 당겨 새로고침하거나 토큰 권한을 확인해 주세요.</p>
        <a class="btn" href="${NoteUrls.SETTINGS_LINK}">설정 열기</a>
        """.trimIndent(),
    )

    fun server(code: Int): String = page(
        "노트를 불러오지 못했습니다",
        "<p>GitHub 서버가 응답하지 않습니다(코드 $code). 잠시 뒤 화면을 아래로 당겨 새로고침해 주세요.</p>",
    )

    fun offline(): String = page(
        "인터넷에 연결되어 있지 않습니다",
        "<p>와이파이나 모바일 데이터를 켠 뒤 화면을 아래로 당겨 새로고침해 주세요. 한 번 열어 본 노트는 이후 인터넷 없이도 볼 수 있습니다.</p>",
    )

    fun forStatus(code: Int, rel: String, config: RepoConfig): String = when {
        code == 401 -> badToken()
        code == 404 && config.token.isBlank() -> needToken()
        code == 404 -> notFound(rel, config)
        code == 403 || code == 429 -> forbidden()
        else -> server(code)
    }

    /** 저장해 둔 노트를 대신 보여 줄 때 맨 위에 붙이는 한 줄 안내. */
    fun bannerFor(code: Int, config: RepoConfig): String = when {
        code == 401 -> "토큰이 만료되어 최신 노트를 받지 못했습니다. 저장해 둔 노트를 표시합니다."
        code == 404 && config.token.isBlank() -> "토큰이 없어 최신 노트를 받지 못했습니다. 저장해 둔 노트를 표시합니다."
        code == 404 -> "최신 노트를 찾지 못했습니다(저장소 설정 확인). 저장해 둔 노트를 표시합니다."
        code == 403 || code == 429 -> "GitHub 요청 한도에 걸려 저장해 둔 노트를 표시합니다."
        else -> "GitHub 서버 오류(코드 $code)로 저장해 둔 노트를 표시합니다."
    }
}
