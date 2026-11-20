"""개념카드 고르기와 퀴즈 만들기."""

from __future__ import annotations

import random
from datetime import date

from .util import fmt_krw, josa


def card_by_id(cards: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in cards}


def select_cards(cards: list[dict], case_cards: list[str], news_cards: list[str], day: date, limit: int = 3) -> list[dict]:
    """그날 핵심 사례 → 뉴스 분류 → 날짜 순환 순서로 카드를 고른다."""
    by_id = card_by_id(cards)
    chosen: list[str] = []
    for cid in case_cards + news_cards:
        if cid and cid in by_id and cid not in chosen:
            chosen.append(cid)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        order = [c["id"] for c in cards]
        start = day.toordinal() % len(order)
        for i in range(len(order)):
            cid = order[(start + i) % len(order)]
            if cid not in chosen:
                chosen.append(cid)
            if len(chosen) >= limit:
                break
    return [by_id[c] for c in chosen[:limit]]


def _shuffle_choices(rng: random.Random, choices: list[str], answer: int) -> tuple[list[str], int]:
    idx = list(range(len(choices)))
    rng.shuffle(idx)
    new_choices = [choices[i] for i in idx]
    return new_choices, idx.index(answer)


def concept_quiz(cards: list[dict], benchmark_quiz: list[dict], rng: random.Random, n: int = 2) -> list[dict]:
    pool: list[dict] = []
    for c in cards:
        for q in c.get("quiz", []) or []:
            pool.append({**q, "topic": c["title"]})
    picked = rng.sample(pool, min(n, len(pool))) if pool else []
    if benchmark_quiz:
        b = rng.choice(benchmark_quiz)
        picked.append({**b, "topic": "규모·세율 감각"})
    out = []
    for q in picked:
        choices, ans = _shuffle_choices(rng, list(q["choices"]), int(q["answer"]))
        out.append({"q": q["q"], "choices": choices, "answer": ans, "explain": q.get("explain", ""), "topic": q.get("topic", "")})
    return out


def _distractors_pct(rng: random.Random, value: float) -> list[float]:
    base = [value * 0.5, value * 1.6, value + 6 if value >= 0 else value - 6, value * 2.4]
    rng.shuffle(base)
    out = []
    for v in base:
        if all(abs(v - x) > max(1.0, abs(value) * 0.2) for x in out + [value]):
            out.append(v)
        if len(out) == 3:
            break
    while len(out) < 3:
        out.append(value + (len(out) + 1) * 4)
    return out


def numbers_quiz(company_name: str, cur: dict, year: int, rng: random.Random) -> list[dict]:
    """오늘의 기업 실제 숫자로 만드는 감각 퀴즈."""
    out = []
    rev = cur.get("revenue")
    op = cur.get("operating_income")
    if rev and op is not None:
        m = op / rev * 100
        opts = [m] + _distractors_pct(rng, m)
        rng.shuffle(opts)
        labels = [f"{v:.1f}%" for v in opts]
        out.append({
            "q": f"{company_name}의 {year}년 영업이익률(영업이익 ÷ 매출)은 대략 얼마일까?",
            "choices": labels,
            "answer": opts.index(m),
            "explain": f"매출 {fmt_krw(rev)}, 영업이익 {fmt_krw(op)} → {m:.1f}%.",
            "topic": "오늘의 기업",
        })
    if rev:
        daily = rev / 365
        opts = [daily, daily * 10, daily / 10, daily * 3.3]
        rng.shuffle(opts)
        out.append({
            "q": f"{company_name}의 연 매출을 365일로 나누면 하루 평균 얼마일까?",
            "choices": [fmt_krw(v) for v in opts],
            "answer": opts.index(daily),
            "explain": f"{fmt_krw(rev)} ÷ 365 = {fmt_krw(daily)}.",
            "topic": "돈 감각",
        })
    return out


def scale_quiz(scale_rows: list[dict], rng: random.Random) -> dict | None:
    """서로 다른 업종 두 회사의 매출 비교."""
    rows = [r for r in scale_rows if r.get("revenue") and not r.get("financial")]
    if len(rows) < 2:
        return None
    for _ in range(20):
        a, b = rng.sample(rows, 2)
        if a.get("industry") != b.get("industry") and 0.4 < a["revenue"] / b["revenue"] < 2.5:
            break
    big, small = (a, b) if a["revenue"] >= b["revenue"] else (b, a)
    choices = [a["name"], b["name"]]
    return {
        "q": f"{a['industry']}의 {a['name']}{josa(a['name'], '과', '와')} {b['industry']}의 {b['name']}, {a.get('year', '')}년 매출이 더 큰 쪽은?",
        "choices": choices,
        "answer": choices.index(big["name"]),
        "explain": f"{big['name']} {fmt_krw(big['revenue'])}, {small['name']} {fmt_krw(small['revenue'])}. 약 {big['revenue'] / small['revenue']:.1f}배 차이.",
        "topic": "업종 규모 감각",
    }


def build_quiz(day: date, cards: list[dict], benchmarks: dict, company: tuple[str, dict, int] | None,
               scale_rows: list[dict]) -> list[dict]:
    rng = random.Random(int(day.strftime("%Y%m%d")))
    quiz = concept_quiz(cards, benchmarks.get("quiz", []), rng, n=1)
    if company:
        name, cur, year = company
        quiz.extend(numbers_quiz(name, cur, year, rng)[:1])
    sq = scale_quiz(scale_rows, rng)
    if sq:
        quiz.append(sq)
    for q in quiz:
        q["answer_label"] = "ABCD"[q["answer"]] if q["answer"] < 4 else str(q["answer"] + 1)
    return quiz


def topic_particle(name: str) -> str:
    return josa(name, "은", "는")
