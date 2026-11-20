"""경영·경제 이론 카드: 사례에 맞는 이론 고르기, 간격을 두고 이론 수업 돌리기, 뉴스 사례 고르기, 이론 퀴즈."""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

FIELD_ORDER = ["경영전략", "마케팅", "재무관리", "조직·인사", "생산·운영", "미시경제", "거시경제", "국제경제", "행동경제"]
GROUP_LABELS = {"finance": "재무·자본시장", "business": "경영", "economics": "경제"}


def theory_by_id(theories: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in theories}


def ordered_library(theories: list[dict]) -> list[dict]:
    """분야 순서대로 정렬(같은 분야 안에서는 파일 순서 유지)."""
    rank = {f: i for i, f in enumerate(FIELD_ORDER)}
    return sorted(theories, key=lambda t: (rank.get(t.get("field", ""), len(FIELD_ORDER)), theories.index(t)))


def recent_lessons(archive_dir: Path, before: date, days: int) -> list[str]:
    """지난 기록에서 최근 다룬 이론 수업 id(최근 것이 앞)."""
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
        for tid in data.get("lessons") or []:
            if tid not in out:
                out.append(tid)
    return out


def lesson_history(archive_dir: Path, before: date) -> list[str]:
    """지난 기록의 이론 수업 id를 날짜 순서대로(오래된 것이 앞)."""
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
        out.extend(data.get("lessons") or [])
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


def briefing_articles(tid: str, buckets: dict[str, list], categories: list[dict], limit: int = 3) -> list:
    """오늘 뉴스 브리핑에서 이 이론으로 읽을 만한 기사(분야별 대표 기사, 점수 순)."""
    out = []
    for cat in categories:
        items = buckets.get(cat["key"]) or []
        if items and tid in (cat.get("theories") or []):
            out.append(items[0])
    out.sort(key=lambda it: it.score, reverse=True)
    return out[:limit]


def theories_for(ids: list[str], by_id: dict[str, dict], limit: int = 2) -> list[dict]:
    return [by_id[i] for i in ids if i in by_id][:limit]


def pick_news_cases(buckets: dict[str, list], categories: list[dict], by_id: dict[str, dict],
                    recent: list[str], n: int = 3) -> list[dict]:
    """분류별 최고 기사 중에서 재무·경영·경제 분야가 고르게 섞이도록 고르고, 각각 읽을 이론을 붙인다."""
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
        # 같은 날 다른 사례와 겹치지 않고, 최근 수업에서 다루지 않은 이론을 먼저
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
