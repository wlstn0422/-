"""경제신문 RSS와 구글 뉴스 검색 RSS에서 기사를 모아 분류한다."""

from __future__ import annotations

import calendar
import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

from .util import KST, clean_text

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    link: str
    source: str = ""
    published: datetime | None = None
    summary: str = ""
    origin: str = ""          # 어느 피드에서 왔는지
    hint: str | None = None   # 구글 뉴스 검색어 분류(사전 분류)
    category: str | None = None
    score: float = 0.0
    coverage: int = 1         # 같은 내용을 다룬 기사 수(중복 합침)
    also: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "category": self.category,
            "coverage": self.coverage,
        }


_SUFFIX_SOURCE = re.compile(r"\s+-\s+([^-]{1,30})$")
_BRACKETS = re.compile(r"[\[\(【<][^\]\)】>]{0,20}[\]\)】>]")
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")


def normalize_title(title: str) -> str:
    t = _BRACKETS.sub(" ", title)
    t = _NON_WORD.sub("", t)
    return t.lower()


def parse_feed(content: bytes, origin: str, hint: str | None = None) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    items: list[NewsItem] = []
    for e in parsed.entries:
        title = clean_text(e.get("title"))
        if not title:
            continue
        source = ""
        src = e.get("source")
        if isinstance(src, dict):
            source = clean_text(src.get("title"))
        m = _SUFFIX_SOURCE.search(title)
        if m and (not source or m.group(1).strip() == source):
            source = source or m.group(1).strip()
            title = title[: m.start()].strip()
        published = None
        tp = e.get("published_parsed") or e.get("updated_parsed")
        if tp:
            published = datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc).astimezone(KST)
        summary = clean_text(e.get("summary") or e.get("description"), limit=240)
        if summary and normalize_title(summary).startswith(normalize_title(title)[:20]):
            summary = ""  # 구글 뉴스 요약은 제목 반복이라 버린다
        items.append(
            NewsItem(
                title=title,
                link=str(e.get("link") or ""),
                source=source or origin,
                published=published,
                summary=summary,
                origin=origin,
                hint=hint,
            )
        )
    return items


def fetch(url: str, timeout: float, session: requests.Session | None = None) -> bytes:
    s = session or requests
    resp = s.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (compatible; casenote/1.0)"})
    resp.raise_for_status()
    return resp.content


def classify(item: NewsItem, categories: list[dict]) -> tuple[str | None, float]:
    best_key, best = None, 0.0
    title = item.title.lower()
    summary = item.summary.lower()
    for cat in categories:
        s = 0.0
        for kw in cat.get("keywords", []):
            k = str(kw).lower()
            if k in title:
                s += 2
            elif k in summary:
                s += 1
        if item.hint == cat["key"]:
            s += 1.5
        if s > best:
            best_key, best = cat["key"], s
    return best_key, best


def dedupe(items: list[NewsItem], threshold: float = 0.78) -> list[NewsItem]:
    """제목이 거의 같은 기사는 하나로 합치고 몇 곳이 다뤘는지 센다."""
    kept: list[NewsItem] = []
    keys: list[str] = []
    for it in items:
        key = normalize_title(it.title)
        if not key:
            continue
        dup_idx = None
        for i, k in enumerate(keys):
            if k == key or (len(key) > 12 and difflib.SequenceMatcher(None, k, key).quick_ratio() >= threshold
                            and difflib.SequenceMatcher(None, k, key).ratio() >= threshold):
                dup_idx = i
                break
        if dup_idx is None:
            kept.append(it)
            keys.append(key)
        else:
            base = kept[dup_idx]
            base.coverage += 1
            if it.source and it.source != base.source and it.source not in base.also:
                base.also.append(it.source)
            if base.hint is None and it.hint:
                base.hint = it.hint
    return kept


def collect_news(sources: dict, lookback_hours: float = 30, timeout: float = 15,
                 now: datetime | None = None, session: requests.Session | None = None) -> tuple[list[NewsItem], list[str]]:
    """모든 피드를 돌며 기사를 모은다. (기사 목록, 실패한 피드 메시지)"""
    now = now or datetime.now(KST)
    since = now - timedelta(hours=lookback_hours)
    raw: list[NewsItem] = []
    errors: list[str] = []
    gn = sources.get("google_news") or {}
    for key, query in (gn.get("queries") or {}).items():
        url = gn["url"].format(query=quote_plus(query))
        try:
            raw.extend(parse_feed(fetch(url, timeout, session), origin="구글뉴스", hint=key))
        except Exception as exc:  # 피드 하나 실패가 전체를 막지 않게
            errors.append(f"구글뉴스({key}): {exc}")
    for feed in sources.get("feeds") or []:
        try:
            raw.extend(parse_feed(fetch(feed["url"], timeout, session), origin=feed["name"]))
        except Exception as exc:
            errors.append(f"{feed['name']}: {exc}")
    fresh = [it for it in raw if it.published is None or it.published >= since]
    # 언론사 직접 피드를 먼저 두어 중복일 때 원문 링크가 남게 한다
    fresh.sort(key=lambda it: (it.origin == "구글뉴스", -(it.published.timestamp() if it.published else 0)))
    return dedupe(fresh), errors


def categorize(items: list[NewsItem], categories: list[dict], per_category: int) -> dict[str, list[NewsItem]]:
    buckets: dict[str, list[NewsItem]] = {c["key"]: [] for c in categories}
    for it in items:
        key, score = classify(it, categories)
        if not key or score < 2:
            continue
        it.category = key
        recency = 0.0
        if it.published:
            hours = max(0.0, (datetime.now(KST) - it.published).total_seconds() / 3600)
            recency = max(0.0, 2 - hours / 12)
        it.score = score + min(it.coverage, 6) * 1.2 + recency
        buckets[key].append(it)
    for key in buckets:
        buckets[key].sort(key=lambda it: it.score, reverse=True)
        buckets[key] = buckets[key][:per_category]
    return buckets


def match_company_news(company_names: list[str], items: list[NewsItem], limit: int = 3) -> dict[str, list[NewsItem]]:
    """회사 이름이 제목에 들어간 기사를 찾는다(두 글자 이하 이름은 오탐이 많아 제외)."""
    out: dict[str, list[NewsItem]] = {}
    for name in company_names:
        n = name.replace("(주)", "").replace("주식회사", "").strip()
        # 'SK', 'LG' 같은 짧은 영문 이름은 계열사 기사까지 잡혀서 제외(한글 두 글자는 허용)
        if len(n) < 2 or (len(n) <= 2 and n.isascii()):
            continue
        hits = [it for it in items if n in it.title]
        if hits:
            out[name] = sorted(hits, key=lambda it: it.coverage, reverse=True)[:limit]
    return out
