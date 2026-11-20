from datetime import datetime

from casenote.news import categorize, dedupe, match_company_news, parse_feed
from casenote.settings import load_yaml
from casenote.util import KST

from fake_data import GOOGLE_NEWS_RSS


def _items():
    return parse_feed(GOOGLE_NEWS_RSS.encode("utf-8"), origin="구글뉴스", hint=None)


def test_parse_google_news_strips_source_suffix():
    items = _items()
    first = items[0]
    assert first.title == "테스트전자, 모의부품 흡수합병 결정…부품 내재화"
    assert first.source == "가상경제"
    assert first.published.tzinfo is not None
    assert first.summary == ""  # 제목 반복 요약은 버린다


def test_dedupe_merges_same_story():
    items = dedupe(_items())
    merger = [i for i in items if "흡수합병" in i.title]
    assert len(merger) == 1
    assert merger[0].coverage == 2
    assert "모의일보" in merger[0].also


def test_categorize_and_match(settings):
    cats = settings.news_sources["categories"]
    items = dedupe(_items())
    buckets = categorize(items, cats, per_category=5)
    titles = {k: [i.title for i in v] for k, v in buckets.items()}
    assert any("물적분할" in t for t in titles["split"])
    assert any("흡수합병" in t for t in titles["ma"])
    assert any("유상증자" in t for t in titles["capital"])
    assert any("공모가" in t for t in titles["ipo"])
    assert any("리브랜딩" in t for t in titles["marketing"])
    assert not any("날씨" in t for v in titles.values() for t in v)
    related = match_company_news(["테스트전자", "SK"], items)
    assert "테스트전자" in related and "SK" not in related
