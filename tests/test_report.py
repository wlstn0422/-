import json
from datetime import date

from casenote import report
from casenote.knowledge import build_quiz
from casenote.news import dedupe, parse_feed
from casenote.site import build_site

from fake_data import GOOGLE_NEWS_RSS, FakeDart

DAY = date(2026, 11, 20)


def arch_lessons(settings):
    return json.loads((settings.archive_dir / "2026-11-20.json").read_text(encoding="utf-8")).get("lessons")


def _news():
    items = dedupe(parse_feed(GOOGLE_NEWS_RSS.encode("utf-8"), origin="구글뉴스"))
    return items, []


def test_daily_end_to_end(settings):
    client = FakeDart()
    out = report.run_daily(settings, DAY, client=client, news_fetcher=_news)
    md = out.read_text(encoding="utf-8")
    # 핵심 사례와 각 섹션
    assert "## 1. 오늘의 공시 사례" in md
    assert "## 2. 뉴스로 보는 경영·경제 사례" in md
    assert "## 3. 오늘의 이론 수업" in md
    assert "이론으로 읽기" in md and "../../theories.md#" in md
    assert "이 기사를 읽는 이론" in md
    assert "테스트전자 합병" in md
    assert "샘플화학 분할" in md or "샘플화학 자사주 취득" in md
    assert "물적분할" in md
    assert "숫자로 보기" in md
    assert "dart.fss.or.kr/dsaf001/main.do?rcpNo=" in md
    assert "## 4. 오늘의 기업" in md
    assert "이 업종이 돈 버는 구조" in md
    assert "듀퐁 분해" in md
    assert "유효세율" in md
    assert "## 8. 오늘의 퀴즈" in md and "<details" in md
    assert "## 7. 회계·세무 카드" in md
    assert (settings.reports_dir / "theories.md").exists()
    assert arch_lessons(settings)
    assert "개 중 1번째 수업" in md  # 기록이 없으면 첫 수업
    assert "IPO(공모)" in md and "예시물산" in md
    # 철회 공시는 없어야 한다
    assert "전환사채(CB)" not in md
    # 표 앞뒤 줄바꿈이 살아 있는지(템플릿 공백 처리 회귀 방지)
    assert "\n| 항목 | 내용 |\n|---|---|\n" in md
    # 기록과 목차
    arch = json.loads((settings.archive_dir / "2026-11-20.json").read_text(encoding="utf-8"))
    assert arch["key_cases"] and arch["quiz"]
    index = (settings.reports_dir / "README.md").read_text(encoding="utf-8")
    assert "daily/2026/2026-11-20.md" in index
    # 규모 지도 캐시
    assert (settings.generated_dir / "scale.json").exists()
    # 웹페이지
    pages = build_site(settings)
    html = (settings.docs_dir / "daily" / "2026" / "2026-11-20.html").read_text(encoding="utf-8")
    assert "<table>" in html and "<details" in html
    assert (settings.docs_dir / "index.html").exists()
    assert any(p.name == "index.html" for p in pages)
    assert "2026-11-20.html" in (settings.docs_dir / "index.html").read_text(encoding="utf-8")


def test_daily_without_keys(settings):
    out = report.run_daily(settings, DAY, news_fetcher=lambda: ([], ["피드 실패"]))
    md = out.read_text(encoding="utf-8")
    assert "DART_API_KEY가 없어" in md
    assert "## 3. 오늘의 이론 수업" in md
    assert "## 7. 회계·세무 카드" in md
    assert "## 8. 오늘의 퀴즈" in md


def test_company_scale_weekly(settings):
    client = FakeDart()
    report.run_daily(settings, DAY, client=client, news_fetcher=_news)
    out = report.run_company(settings, "테스트전자", client=client)
    md = out.read_text(encoding="utf-8")
    assert "테스트전자 기업 분석 노트" in md
    assert "감사의견" in md and "가상회계법인" in md
    assert "평균 급여" in md
    scale = report.run_scale(settings, 2025, client=client)
    smd = scale.read_text(encoding="utf-8")
    assert "업종별 규모 지도" in smd and "테스트전자" in smd
    weekly = report.run_weekly(settings, date(2026, 11, 21))
    wmd = weekly.read_text(encoding="utf-8")
    assert "복습 노트" in wmd and "테스트전자" in wmd
    assert "이번 주 이론 수업" in wmd


def test_quiz_answers_valid(settings):
    cards = settings.cards
    for i in range(30):
        d = date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i)
        quiz = build_quiz(d, cards[:3], settings.benchmarks, ("테스트전자", {"revenue": 1200e8, "operating_income": 150e8}, 2025), [])
        for q in quiz:
            assert 0 <= q["answer"] < len(q["choices"])
            assert len(set(q["choices"])) == len(q["choices"]), q


def test_cards_are_well_formed(settings):
    ids = set()
    for c in settings.cards:
        assert c["id"] not in ids
        ids.add(c["id"])
        for key in ("title", "summary", "accounting", "law", "numbers", "quiz"):
            assert key in c, (c["id"], key)
        for q in c["quiz"]:
            assert 0 <= q["answer"] < len(q["choices"]), (c["id"], q["q"])
    # 공시 규칙과 뉴스 분류가 가리키는 카드가 모두 있어야 한다
    from casenote.events import RULES
    for r in RULES:
        assert r.card is None or r.card in ids, r.key
    for cat in settings.news_sources["categories"]:
        for cid in cat.get("cards", []):
            assert cid in ids, cid
