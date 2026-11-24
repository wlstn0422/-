from datetime import date
from types import SimpleNamespace

from casenote import brief as br
from casenote import report
from casenote.news import NewsItem, is_local, quality_adjust
from casenote.site import build_site, rebase_md_links

CATS = [{"key": "macro", "label": "거시경제"}, {"key": "fiscal", "label": "재정·예산·복지"},
        {"key": "global", "label": "글로벌 기업"}, {"key": "marketing", "label": "마케팅·브랜드"}]
TH = {"disclosure_group_assets": 5e12}


def item(title, coverage=1, source="모의일보", also=(), summary="", link=None):
    return NewsItem(title=title, link=link or f"https://news.example.com/{abs(hash(title))}", source=source,
                    summary=summary, coverage=coverage, also=list(also))


def test_headline_cleanup_and_text_choice():
    assert br.clean_headline("젠슨 황의 귀환에 뒤집힌 월가...엔비디아 31%·나스닥 6.5% 폭등 [월가월부]") == \
        "젠슨 황의 귀환에 뒤집힌 월가…엔비디아 31%·나스닥 6.5% 폭등"
    assert br.clean_headline("[다음주 경제] 기준금리 결정 주간(종합)") == "기준금리 결정 주간"
    # 따옴표는 짝이 맞게 그대로 남긴다
    assert br.clean_headline("골드만삭스 \u201c내년 기준금리 3.5%가 상단\u201d") == "골드만삭스 \u201c내년 기준금리 3.5%가 상단\u201d"
    assert br.drop_question(br.clean_headline("'젠슨 황 엔비디아 복귀'에 5천피 회복...추세 반등?")) == \
        "'젠슨 황 엔비디아 복귀'에 5천피 회복"
    # 핵심 숫자가 제목에만 있으면 제목을, 첫 문장에도 숫자가 있으면 첫 문장을 쓴다
    nasdaq = item("엔비디아 호실적도 못 막았다…나스닥, 기술주 매도에 5.3% 폭락",
                  summary="20일(현지시간) 미국 뉴욕증시 주요 지수가 일제히 급락했다. 다우지수는")
    assert br.story_text(nasdaq) == "엔비디아 호실적도 못 막았다…나스닥, 기술주 매도에 5.3% 폭락"
    rate = item("[다음주 경제] 숨 고르기 한 기준금리, 인상할까…한은 성장률 전망은",
                summary="다음 주(11월 23∼27일)에는 한국은행 금융통화위원회가 기준금리를 결정한다. 이번 회의는")
    assert br.story_text(rate) == "다음 주(11월 23∼27일)에는 한국은행 금융통화위원회가 기준금리를 결정한다."


def test_topic_quality():
    # 큰 주제는 가산, 홍보성·시세·사진 기사는 감점
    assert quality_adjust(item("골드만삭스 \u201c내년 한은 기준금리 3.5%가 상단\u201d"), "macro") == 3
    assert quality_adjust(item("대동, 한국ESG기준원 ESG 평가 2년 연속 통합 A등급 획득"), "esg") == -6
    assert quality_adjust(item("[외환] 원/달러 환율 3.5원 내린 1,342.4원(15:30 기준가)"), "macro") == -5
    assert quality_adjust(item("[포토] 서울교통공사 임단협 최종 교섭"), "hr") == -10
    assert br.clean_headline("젠슨 황 11일 만의 귀환…엔비디아 급등, 한국 증시에 가져온 건?｜빽투빽") == \
        "젠슨 황 11일 만의 귀환…엔비디아 급등, 한국 증시에 가져온 건?"
    assert br.drop_question("젠슨 황 11일 만의 귀환…엔비디아 급등, 한국 증시에 가져온 건?") == "젠슨 황 11일 만의 귀환…엔비디아 급등"
    assert br.drop_question("엔비디아 일주일 만에 23% 폭락…SEC 조사에 위기 더 커지나?") == "엔비디아 일주일 만에 23% 폭락"
    assert br.drop_question("기준금리 동결") == "기준금리 동결"


def test_local_news_is_pushed_back():
    assert is_local(item("울진군, 2027년도 예산안 7,840억 원 편성"), "fiscal")
    assert not is_local(item("울진군, 2027년도 예산안 7,840억 원 편성"), "macro")  # 분야가 다르면 따지지 않는다
    assert not is_local(item("증시, 기술주 매도에 급락"), "fiscal")


def test_pick_brief_prefers_big_national_issues():
    local = item("울진군, 2027년도 예산안 7,840억 원 편성", coverage=9, source="드림저널")
    pr = item("대동, 한국ESG기준원 ESG 평가 2년 연속 통합 A등급 획득", coverage=9, source="연합뉴스",
              also=["뉴스1", "뉴시스", "아시아경제"])  # 여러 곳이 받아썼어도 홍보성 기사
    budget = item("국회, 728조 내년 예산안 처리 착수", coverage=4, source="연합뉴스", also=["한국경제", "매일경제"])
    rate = item("한은, 기준금리 연 2.25% 동결", coverage=6, source="연합뉴스", also=["서울경제"])
    rate2 = item("한은, 기준금리 연 2.25% 동결…물가 경계", coverage=2, source="뉴스1")  # 같은 이슈
    nvda = item("엔비디아 시가총액 6조달러 돌파", coverage=5, source="조선비즈")
    ad = item("모의식품 리브랜딩 캠페인", coverage=1, source="모의일보")  # 한 곳만 다룬 기사는 빼다
    buckets = {"fiscal": [local, budget], "macro": [rate, rate2], "global": [nvda], "marketing": [ad, pr]}
    news_cases = [{"item": nvda}]
    ev = SimpleNamespace(corp_name="테스트전자", rule=SimpleNamespace(label="합병"), amount=3e11,
                         amount_label="합병가액", fin={"assets": 1e12}, url="https://dart.example/1")
    small = SimpleNamespace(corp_name="작은회사", rule=SimpleNamespace(label="자사주 취득"), amount=5e9,
                            amount_label="취득금액", fin={"assets": 1e11}, url="https://dart.example/2")
    easy = {"what": "전자부품 제조 기업 테스트전자가 모의부품과 합병한다. (앞서 제출한 공시를 정정한 공시이다.)"}
    out = br.pick_brief(buckets, CATS, news_cases, [{"ev": small}, {"ev": ev, "easy": easy}], TH, limit=3)
    texts = [o["text"] for o in out]
    assert texts[0] == "한은, 기준금리 연 2.25% 동결"  # 거시경제·여러 언론
    assert "국회, 728조 내년 예산안 처리 착수" in texts and not any("울진군" in t for t in texts)
    assert sum("기준금리" in t for t in texts) == 1  # 같은 이슈는 한 번만
    assert not any("리브랜딩" in t or "A등급" in t for t in texts)
    nv = next(o for o in out if "엔비디아" in o["text"])
    assert nv["anchor"] == "n1" and nv["tag"] == "글로벌 기업"  # 아래 뉴스 사례로 이어진다
    assert out[-1] == {"text": "전자부품 제조 기업 테스트전자가 모의부품과 합병한다.", "tag": "공시",
                       "link": "https://dart.example/1", "anchor": "c2"}  # 대형 공시 1건만, 해설 첫 문장으로
    assert br.case_text({"ev": ev}) == "테스트전자 합병(합병가액 3,000억원)"  # 해설이 없을 때
    assert len(out) == 4


def test_calendar_and_today_page(settings):
    rd = settings.reports_dir
    for d in ("2026-11-20", "2026-11-23", "2026-11-24"):
        p = rd / "daily" / "2026" / f"{d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {d} 노트\n\n[이론·제도 사전](../../theories.md#valuation) · [위로](#brief)\n", encoding="utf-8")
    (rd / "weekly").mkdir(parents=True, exist_ok=True)
    (rd / "weekly" / "2026-W47.md").write_text("# 복습\n", encoding="utf-8")
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    (settings.archive_dir / "2026-11-24.json").write_text(
        '{"brief": [{"tag": "거시경제", "text": "한은, 기준금리 동결", "link": "x"}]}', encoding="utf-8")
    report.write_reports_index(settings)
    cal = (rd / "calendar.md").read_text(encoding="utf-8")
    assert "## 2026년 11월" in cal and "| 일 | 월 | 화 | 수 | 목 | 금 | 토 |" in cal
    assert "**[24](daily/2026/2026-11-24.md)**" in cal  # 가장 최근 노트는 굵게
    assert "[20](daily/2026/2026-11-20.md)" in cal and '<span class="off">25</span>' in cal
    assert "<br>[복습](weekly/2026-W47.md)" in cal  # 2026년 47주 토요일(11월 21일) 칸
    assert "- [2026년 11월 21일 주간 복습](weekly/2026-W47.md)" in cal
    assert "[24일(화)](daily/2026/2026-11-24.md): 한은, 기준금리 동결" in cal
    build_site(settings)
    today = (settings.docs_dir / "today.html").read_text(encoding="utf-8")
    assert "2026-11-24 노트" in today and 'href="theories.html#valuation"' in today and 'href="#brief"' in today
    assert 'href="calendar.html">캘린더' in today and 'href="today.html">오늘의 노트' in today
    assert (settings.docs_dir / "calendar.html").exists()
    assert rebase_md_links("[a](../../scale.md) [b](https://x.y/z) [c](#n1)", "daily/2026") == \
        "[a](scale.md) [b](https://x.y/z) [c](#n1)"
    assert date(2026, 11, 24).weekday() == 1
