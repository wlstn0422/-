"""이론·제도 카드: 사례에 맞는 카드 고르기, 이론 수업과 전공 수업 돌리기, 뉴스 사례 고르기, 퀴즈."""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BUSINESS_FIELDS = ["경영전략", "마케팅", "재무관리", "조직·인사", "생산·운영", "미시경제", "거시경제", "국제경제", "행동경제"]
SUBJECT_FIELDS = ["재무회계", "원가관리회계", "세법", "상법", "재정학"]
FIELD_ORDER = BUSINESS_FIELDS + SUBJECT_FIELDS
GROUP_LABELS = {"finance": "재무·자본시장", "business": "경영", "economics": "경제", "institution": "회계·세무·법·재정"}

# 카드의 law 블록을 보여줄 때 쓰는 이름. 세법·상법은 입법, 재정학은 정책, 재무회계는 기준, 원가관리회계는 기법 이야기다.
_STORY_COMMON = {"theory": "바탕이 된 이론", "economic_effects": "경제적 효과", "cases": "실제 사례에 대입하면",
                 "evidence": "실제로 어떤 효과가 있었나", "recent": "지금의 쟁점"}
STORY_LABELS = {
    "세법": {"title": "입법 이야기", "basis": "근거 조문", "purpose": "왜 만들었나(입법 취지)",
             "background": "만들 당시 무슨 일이 있었나(입법 배경)", **_STORY_COMMON},
    "상법": {"title": "입법 이야기", "basis": "근거 조문", "purpose": "왜 만들었나(입법 취지)",
             "background": "만들 당시 무슨 일이 있었나(입법 배경)", **_STORY_COMMON},
    "재정학": {"title": "정책 이야기", "basis": "근거 법령", "purpose": "왜 만들었나(정책 취지)",
               "background": "그때 무슨 일이 있었나(정책 배경)", **_STORY_COMMON},
    "재무회계": {"title": "기준 이야기", "basis": "근거 기준", "purpose": "왜 만들었나(제정 취지)",
                 "background": "만들 당시 무슨 일이 있었나(제정 배경)", **_STORY_COMMON},
    "원가관리회계": {"title": "기법 이야기", "basis": "출발점", "purpose": "왜 나왔나",
                     "background": "나온 배경", **_STORY_COMMON},
}
DEFAULT_SUBJECT_ROTATION = ["재무회계", "원가관리회계", "세법", "상법", "재정학"]


def is_subject(t: dict) -> bool:
    return t.get("field") in SUBJECT_FIELDS


def split_library(theories: list[dict]) -> tuple[list[dict], list[dict]]:
    """경영·경제 이론과 전공(회계·세법·상법·재정학) 카드로 나눈다."""
    return [t for t in theories if not is_subject(t)], [t for t in theories if is_subject(t)]


def story_labels(field: str) -> dict[str, str]:
    return STORY_LABELS.get(field, STORY_LABELS["재무회계"])


def subject_of_day(day: date, rotation: list[str] | None = None) -> str:
    """요일별 전공 과목. 월~금은 순서대로, 주말에 따로 돌리면 날짜에 따라 돌아간다."""
    rotation = rotation or DEFAULT_SUBJECT_ROTATION
    if day.weekday() < 5:
        return rotation[day.weekday() % len(rotation)]
    return rotation[day.toordinal() % len(rotation)]


def applies(card: dict, kind: str) -> list[str]:
    return list(((card.get("applies_to") or {}).get(kind)) or [])


def subject_candidates(cards: list[dict], rule_keys: list[str], news_keys: list[str]) -> list[str]:
    """오늘 공시 유형(가중치 2)과 기사가 있는 뉴스 분류(1)에 이어진 카드 id를 관련도만큼 반복해서 돌려준다."""
    out: list[str] = []
    for key in rule_keys:
        out += [c["id"] for c in cards if key in applies(c, "filings")] * 2
    for key in news_keys:
        out += [c["id"] for c in cards if key in applies(c, "news")]
    return out


# 공시 사례에 이어 볼 전공 카드의 과목 우선순위(공시는 회계·세법·상법 쟁점이 먼저다)
FILING_SUBJECT_PRIORITY = {"재무회계": 0, "세법": 1, "상법": 2, "재정학": 3, "원가관리회계": 4}


def subject_cards_for_rule(rule_key: str, cards: list[dict], limit: int = 3) -> list[dict]:
    """공시 유형에 이어진 전공 카드. 과목이 겹치지 않게 먼저 고르고 남는 자리를 채운다."""
    hits = [c for c in cards if rule_key in applies(c, "filings")]
    hits.sort(key=lambda c: FILING_SUBJECT_PRIORITY.get(c.get("field", ""), 9))
    out: list[dict] = []
    seen_fields: set[str] = set()
    for c in hits:
        if c["field"] not in seen_fields:
            out.append(c)
            seen_fields.add(c["field"])
    for c in hits:
        if c not in out:
            out.append(c)
    return out[:limit]


def keyword_score(card: dict, text: str) -> int:
    """카드의 '더 찾아볼 말'이 기사 제목·요약에 몇 개 나오는지(띄어쓰기 무시)."""
    flat = text.replace(" ", "")
    return sum(1 for kw in card.get("keywords") or [] if len(str(kw)) >= 2 and str(kw).replace(" ", "") in flat)


def theory_by_id(theories: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in theories}


def ordered_library(theories: list[dict]) -> list[dict]:
    """분야 순서대로 정렬(같은 분야 안에서는 파일 순서 유지)."""
    rank = {f: i for i, f in enumerate(FIELD_ORDER)}
    return sorted(theories, key=lambda t: (rank.get(t.get("field", ""), len(FIELD_ORDER)), theories.index(t)))


def recent_lessons(archive_dir: Path, before: date, days: int, key: str = "lessons") -> list[str]:
    """지난 기록에서 최근 다룬 수업 id(최근 것이 앞). key는 lessons(이론) 또는 subject_lessons(전공)."""
    out: list[str] = []
    if not archive_dir.exists():
        return out
    for i in range(1, days + 1):
        p = archive_dir / f"{(before - timedelta(days=i)).isoformat()}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for tid in data.get(key) or []:
            if tid not in out:
                out.append(tid)
    return out


def lesson_history(archive_dir: Path, before: date, key: str = "lessons") -> list[str]:
    """지난 기록의 수업 id를 날짜 순서대로(오래된 것이 앞)."""
    out: list[str] = []
    if not archive_dir.exists():
        return out
    for p in sorted(archive_dir.glob("*.json")):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d >= before:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.extend(data.get(key) or [])
    return out


def taught_this_round(history: list[str], ids: set[str]) -> set[str]:
    """이론 사전을 한 바퀴 도는 동안 이미 배운 이론. 전부 배우면 새 바퀴를 시작한다."""
    done: set[str] = set()
    for tid in history:
        if tid in ids:
            done.add(tid)
            if done >= ids:
                done = set()
    return done


def _ranked(ids: list[str], by_id: dict[str, dict]) -> list[str]:
    """많이 나온 순, 같으면 먼저 나온 순."""
    ids = [i for i in ids if i in by_id]
    counts = Counter(ids)
    first_seen: dict[str, int] = {}
    for i, tid in enumerate(ids):
        first_seen.setdefault(tid, i)
    return sorted(counts, key=lambda c: (-counts[c], first_seen[c]))


def pick_lessons(theories: list[dict], candidates: list[str], recent: list[str], day: date, n: int = 1,
                 done: set[str] | None = None, pool: list[str] | None = None) -> list[dict]:
    """이론 수업 고르기.

    이론 사전을 한 바퀴 다 돌 때까지는 이번 바퀴에서 아직 안 배운 이론만 고른다. 그 안에서
    1) 오늘 사례와 관련이 많은 이론(candidates)
    2) 오늘 기사 분야나 사례 이론과 이어진 이론(pool)
    3) 남은 이론을 분야 순서대로 돌아가며
    순으로 고르고, 최근에 다룬 이론(recent)은 어느 경우에도 피한다.
    """
    by_id = theory_by_id(theories)
    done = set(done or ())
    blocked = set(recent)
    library = ordered_library(theories)
    start = day.toordinal() % len(library) if library else 0
    rotation = [library[(start + i) % len(library)]["id"] for i in range(len(library))]
    tiers = [_ranked(candidates, by_id), _ranked(list(pool or []), by_id), rotation]
    chosen: list[str] = []

    def take(skip_done: bool) -> None:
        for tier in tiers:
            for tid in tier:
                if len(chosen) >= n:
                    return
                if tid in chosen or tid in blocked or (skip_done and tid in done):
                    continue
                chosen.append(tid)

    take(skip_done=True)
    if len(chosen) < n:  # 이번 바퀴를 다 돌았으면 최근 것만 피해서
        take(skip_done=False)
    if len(chosen) < n:  # 이론 수가 너무 적어 전부 최근에 다뤘으면 관련 순으로 다시
        for tid in tiers[0] + rotation:
            if tid not in chosen:
                chosen.append(tid)
            if len(chosen) >= n:
                break
    return [by_id[t] for t in chosen[:n]]


def briefing_articles(card: dict, buckets: dict[str, list], categories: list[dict], limit: int = 3,
                      extra_keys: list[str] | tuple = ()) -> list:
    """오늘 뉴스에서 이 카드로 읽을 만한 기사. 카드를 쓰는 분류와 카드가 가리키는 분류(extra_keys)의 기사 중
    카드의 '더 찾아볼 말'이 제목에 많이 나오는 것, 분류 안에서 순위가 높은 것, 점수가 높은 것 순."""
    scored = []
    for cat in categories:
        items = buckets.get(cat["key"]) or []
        if not items or not (card["id"] in (cat.get("theories") or []) or cat["key"] in extra_keys):
            continue
        for rank, it in enumerate(items):
            text = f"{it.title} {getattr(it, 'summary', '') or ''}"
            scored.append((keyword_score(card, text), -rank, it.score, it))
    scored.sort(key=lambda x: x[:3], reverse=True)
    out, seen = [], set()
    for *_, it in scored:
        if it.link not in seen:
            out.append(it)
            seen.add(it.link)
    return out[:limit]


def theories_for(ids: list[str], by_id: dict[str, dict], limit: int = 2) -> list[dict]:
    return [by_id[i] for i in ids if i in by_id][:limit]


def pick_news_cases(buckets: dict[str, list], categories: list[dict], by_id: dict[str, dict],
                    recent: list[str], n: int = 3) -> list[dict]:
    """분류별 최고 기사 중에서 재무·경영·경제·제도 분야가 고르게 섞이도록 고르고, 각각 읽을 카드를 붙인다.
    카드는 분류에 정한 순서가 기본이고, 기사 제목·요약에 카드의 '더 찾아볼 말'이 나오면 그 카드를 앞세운다."""
    cat_by_key = {c["key"]: c for c in categories}
    tops = []
    for key, items in buckets.items():
        if items and key in cat_by_key:
            tops.append((items[0].score, key, items[0]))
    tops.sort(key=lambda x: x[0], reverse=True)
    picked: list[tuple[str, object]] = []
    used_groups: set[str] = set()
    for _, key, item in tops:  # 1차: 분야(group)가 겹치지 않게
        group = cat_by_key[key].get("group", "")
        if group not in used_groups:
            picked.append((key, item))
            used_groups.add(group)
        if len(picked) >= n:
            break
    for _, key, item in tops:  # 2차: 남은 자리는 점수 순
        if len(picked) >= n:
            break
        if all(k != key for k, _ in picked):
            picked.append((key, item))
    used_theories: set[str] = set()
    cases = []
    for idx, (key, item) in enumerate(picked, start=1):
        cat = cat_by_key[key]
        options = [t for t in cat.get("theories", []) if t in by_id]
        text = f"{item.title} {getattr(item, 'summary', '') or ''}"
        scores = {t: keyword_score(by_id[t], text) for t in options}
        options.sort(key=lambda t: -scores[t])  # 같은 점수면 원래 순서 유지(정렬 안정성)
        # 같은 날 다른 사례와 겹치지 않고, 최근 수업에서 다루지 않은 카드를 먼저
        main = next((t for t in options if t not in used_theories and t not in recent), None) \
            or next((t for t in options if t not in used_theories), None) \
            or (options[0] if options else None)
        if not main:
            continue
        used_theories.add(main)
        cases.append({
            "id": f"n{idx}",
            "item": item,
            "category": cat,
            "group_label": GROUP_LABELS.get(cat.get("group", ""), ""),
            "theory": by_id[main],
            "others": [by_id[t] for t in options if t != main][:2],
        })
    return cases


def theory_quiz(theories: list[dict], rng: random.Random, n: int = 2) -> list[dict]:
    pool = []
    for t in theories:
        for q in t.get("quiz", []) or []:
            pool.append({**q, "topic": t["title"]})
    picked = rng.sample(pool, min(n, len(pool))) if pool else []
    out = []
    for q in picked:
        idx = list(range(len(q["choices"])))
        rng.shuffle(idx)
        choices = [q["choices"][i] for i in idx]
        out.append({"q": q["q"], "choices": choices, "answer": idx.index(int(q["answer"])),
                    "explain": q.get("explain", ""), "topic": q["topic"]})
    return out


def library_by_field(theories: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for t in ordered_library(theories):
        groups.setdefault(t.get("field", "기타"), []).append(t)
    return list(groups.items())
