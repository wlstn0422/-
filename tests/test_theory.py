import json
import random
from datetime import date, timedelta
from pathlib import Path

from casenote import theory as th
from casenote.events import RULE_THEORIES
from casenote.news import NewsItem
from casenote.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


def real_settings():
    return load_settings(ROOT)


def test_theory_cards_well_formed():
    s = real_settings()
    theories = s.theories
    assert len(theories) >= 35
    ids = [t["id"] for t in theories]
    assert len(ids) == len(set(ids)), "이론 id 중복"
    for t in theories:
        for key in ("title", "field", "one_line", "easy", "deep", "how_to", "example", "pitfalls", "related", "quiz"):
            assert t.get(key), (t["id"], key)
        assert t["field"] in th.FIELD_ORDER, (t["id"], t["field"])
        assert len(t["easy"].strip().splitlines()) >= 2, (t["id"], "쉬운 설명은 두 문단 이상")
        assert len(t["deep"]) >= 2 and len(t["how_to"]) >= 3, t["id"]
        for r in t["related"]:
            assert r in ids, (t["id"], "related", r)
        for q in t["quiz"]:
            assert 0 <= q["answer"] < len(q["choices"]), (t["id"], q["q"])
            assert len(set(q["choices"])) == len(q["choices"]), (t["id"], q["q"])


def test_every_theory_reference_exists():
    s = real_settings()
    ids = {t["id"] for t in s.theories}
    for rule, refs in RULE_THEORIES.items():
        for r in refs:
            assert r in ids, (rule, r)
    queries = s.news_sources["google_news"]["queries"]
    for cat in s.news_sources["categories"]:
        assert cat.get("group") in th.GROUP_LABELS, cat["key"]
        assert cat.get("numbers"), cat["key"]
        assert cat["key"] in queries, ("구글 뉴스 검색어 없음", cat["key"])
        for r in cat.get("theories", []):
            assert r in ids, (cat["key"], r)
    for ind in s.industries:
        assert ind.get("profile"), ind["name"]
        for r in ind.get("theories", []):
            assert r in ids, (ind["name"], r)
    card_ids = {c["id"] for c in s.cards}
    for cat in s.news_sources["categories"]:
        for c in cat.get("cards", []):
            assert c in card_ids, (cat["key"], c)


def test_lessons_cover_library_without_repeats(tmp_path):
    s = real_settings()
    ids = {t["id"] for t in s.theories}
    archive = tmp_path / "archive"
    archive.mkdir()
    start = date(2026, 1, 1)
    last: dict[str, date] = {}
    first: dict[str, date] = {}
    # 매일 같은 사례가 나와 같은 이론이 후보 1순위여도, 이론 사전을 한 바퀴 다 돌기 전에는 다시 나오지 않는다
    for i in range(60):
        day = start + timedelta(days=i)
        recent = th.recent_lessons(archive, day, 21)
        done = th.taught_this_round(th.lesson_history(archive, day), ids)
        picked = th.pick_lessons(s.theories, ["signaling", "signaling", "payout_policy"], recent, day, n=1,
                                 done=done, pool=["valuation"])
        assert len(picked) == 1
        tid = picked[0]["id"]
        if tid in last:
            assert (day - last[tid]).days > 21, (tid, last[tid], day)
        last[tid] = day
        first.setdefault(tid, day)
        (archive / f"{day.isoformat()}.json").write_text(json.dumps({"lessons": [tid]}), encoding="utf-8")
    assert first["signaling"] == start  # 첫날은 관련도 1위
    assert first["payout_policy"] == start + timedelta(days=1)  # 다음 날은 2순위
    assert first["valuation"] == start + timedelta(days=2)  # 사례 이론이 다 나오면 이어진 이론
    assert set(first) == ids  # 이론 수만큼의 날 안에 한 바퀴를 다 돈다
    assert max(first.values()) == start + timedelta(days=len(ids) - 1)
    assert last["signaling"] == start + timedelta(days=len(ids))  # 새 바퀴는 다시 관련도 1위부터


def test_round_resets_after_full_library():
    ids = {"a", "b", "c"}
    assert th.taught_this_round(["a", "b"], ids) == {"a", "b"}
    assert th.taught_this_round(["a", "b", "c"], ids) == set()
    assert th.taught_this_round(["a", "b", "c", "b", "zzz"], ids) == {"b"}


def test_news_cases_mix_fields():
    s = real_settings()
    cats = s.news_sources["categories"]
    by_id = th.theory_by_id(s.theories)

    def item(title, score):
        it = NewsItem(title=title, link="https://news.example.com/x", source="모의일보")
        it.score = score
        return it

    buckets = {
        "ma": [item("가상기업 경영권 인수", 9)],
        "capital": [item("모의기업 자사주 소각", 8)],
        "pricing": [item("모의식품 가격 인상", 6)],
        "macro": [item("기준금리 동결", 5)],
    }
    cases = th.pick_news_cases(buckets, cats, by_id, recent=[], n=3)
    groups = [c["category"]["group"] for c in cases]
    assert len(cases) == 3
    assert len(set(groups)) == 3, groups  # 재무·경영·경제가 하나씩
    assert all(c["theory"]["id"] in by_id for c in cases)
    assert len({c["theory"]["id"] for c in cases}) == 3


def test_theory_quiz_valid():
    s = real_settings()
    rng = random.Random(1)
    for _ in range(20):
        qs = th.theory_quiz(s.theories, rng, n=3)
        for q in qs:
            assert 0 <= q["answer"] < len(q["choices"])


def test_theory_book_page(settings):
    from casenote.report import write_theory_book
    out = write_theory_book(settings)
    md = out.read_text(encoding="utf-8")
    assert md.startswith("# 경영·경제 이론 사전")
    assert '<a name="five_forces"></a>' in md
    assert "### 포터의 5가지 경쟁요인" in md
    assert "(#generic_strategy)" in md
