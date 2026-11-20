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


def _item(title, origin="구글뉴스", source="모의일보"):
    from casenote.news import NewsItem
    return NewsItem(title=title, link="https://news.example.com/x", source=source, origin=origin)


def test_same_story_merges_rewordings_but_not_other_companies(settings):
    from casenote.news import same_story
    a = _item("테스트전자, 7월 매입한 자사주 1천억원어치 이달말 소각")
    b = _item("테스트전자, 1000억 규모 자사주 소각…내년에도 추가 소각")
    c = _item("테스트전자, 자사주 처분 결정")
    assert same_story(a, b)
    assert not same_story(a, c)
    d = _item("(특징주) 모의에어로다이내믹스, 코스닥 상장 첫날 공모가 대비 73% 급등")
    e = _item("모의에어로, 코스닥 상장 첫날 장 초반 73% 상승")
    assert same_story(d, e)
    f = _item("가상테크 3분기 매출 4% 증가…영업이익 3% 감소")
    g = _item("모의소재 3분기 매출 28.4% 증가…영업이익 60억원")
    assert not same_story(f, g)
    cats = settings.news_sources["categories"]
    buckets = categorize([a, b, f, g], cats, per_category=5)
    capital = buckets["capital"]
    assert len(capital) == 1 and capital[0].coverage == 2
    assert len(buckets["earnings"]) == 2


def test_double_source_suffix_and_url_source():
    rss = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
    <item><title>모의기업 자사주 소각 - 모의일보 - 모의일보</title><link>https://n.example.com/1</link>
    <source url="https://n.example.com">모의일보</source></item>
    <item><title>가상기업 인수 추진 - https://www.example.kr/</title><link>https://n.example.com/2</link>
    <source url="https://www.example.kr/">https://www.example.kr/</source></item>
    </channel></rss>"""
    items = parse_feed(rss.encode("utf-8"), origin="구글뉴스")
    assert items[0].title == "모의기업 자사주 소각"
    assert items[1].source == "example.kr"
    assert items[1].title == "가상기업 인수 추진"


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
