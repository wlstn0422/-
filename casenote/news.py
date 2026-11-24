"""경제신문 RSS와 구글 뉴스 검색 RSS에서 기사를 모아 분류한다."""

from __future__ import annotations

import calendar
import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

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
        raw_source = source
        if source.startswith("http"):
            source = urlparse(source).netloc.removeprefix("www.") or source
        # 언론사 제목에 이미 '- 매체명'이 있고 구글이 한 번 더 붙이는 경우가 있어 두 번까지 뗀다
        for _ in range(2):
            m = _SUFFIX_SOURCE.search(title)
            if not m or (source and m.group(1).strip() not in (source, raw_source)):
                break
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


_TOKEN = re.compile(r"[0-9A-Za-z가-힣%]+")
_LEADING_TAGS = re.compile(r"^(\s*[\[\(【<][^\]\)】>]{0,20}[\]\)】>]\s*)+")


def _subject_and_tokens(title: str) -> tuple[str, set[str]]:
    """제목 맨 앞 주어(대개 회사 이름)와 두 글자 이상 단어 집합."""
    t = _LEADING_TAGS.sub("", title).strip().strip("'\"‘’“”")
    tokens = [w for w in _TOKEN.findall(t) if len(w) >= 2]
    subject = tokens[0] if tokens else ""
    return subject, set(tokens)


def same_story(a: NewsItem, b: NewsItem) -> bool:
    """같은 회사(주어)로 시작하고 핵심 단어를 2개 이상 더 공유하면 같은 사건으로 본다."""
    sa, ta = _subject_and_tokens(a.title)
    sb, tb = _subject_and_tokens(b.title)
    if not sa or not sb:
        return False
    short, long_ = sorted((sa, sb), key=len)
    if not (short == long_ or (len(short) >= 3 and long_.startswith(short))):
        return False
    return len((ta & tb) - {sa, sb}) >= 2


# 전국 단위 통신사·종합지·경제지·방송. 이들이 함께 다룬 기사일수록 그날의 주요 이슈일 가능성이 크다.
MAJOR_OUTLETS = (
    "연합뉴스", "연합인포맥스", "뉴스1", "뉴시스", "한국경제", "매일경제", "서울경제", "머니투데이", "이데일리",
    "아시아경제", "헤럴드경제", "파이낸셜뉴스", "조선비즈", "조선일보", "중앙일보", "동아일보", "한겨레",
    "경향신문", "한국일보", "국민일보", "세계일보", "문화일보", "서울신문", "KBS", "MBC", "SBS", "YTN",
    "JTBC", "MBN", "채널A", "TV조선", "한국경제TV", "비즈니스워치", "뉴스핌", "아주경제", "이투데이",
    "디지털타임스", "전자신문", "더벨", "대한경제", "머니S", "데일리안", "노컷뉴스",
)

# 지자체 예산·정책 기사는 전국 단위 이슈보다 뒤로 미룬다(지역 매체가 일제히 받아써 보도량이 부풀려지는 경우가 많다).
_LOCAL = re.compile(r"^(?:[가-힣]{1,4}(?:시|군|구)|(?:경기|강원|충북|충남|충청북|충청남|전북|전남|전라북|전라남|경북|경남|"
                    r"경상북|경상남|제주)(?:특별자치)?도)(?:청|의회|교육청)?$")
_NOT_LOCAL = {"증시", "당시", "동시", "임시", "즉시", "수시", "상시", "전시", "개시", "공시", "게시", "지시", "제시", "표시",
              "감시", "도시", "역시", "다시", "연구", "지구", "요구", "가구", "인구", "기구", "도구", "창구", "출구", "추구",
              "해군", "육군", "공군"}
_LOCAL_CATEGORIES = {"fiscal", "policy", "esg", "hr"}

def major_count(item: NewsItem) -> int:
    names = [item.source, *item.also]
    return sum(1 for n in names if n and any(o in n for o in MAJOR_OUTLETS))


def is_local(item: NewsItem, cat_key: str | None) -> bool:
    if cat_key not in _LOCAL_CATEGORIES:
        return False
    subject, _ = _subject_and_tokens(item.title)
    return bool(subject) and subject not in _NOT_LOCAL and bool(_LOCAL.match(subject))


# 경제 전체에 영향을 주는 주체·지표가 제목에 나오면 그날의 큰 이슈일 가능성이 크다.
BIG_KEYWORDS = (
    "대통령", "정부", "국회", "한은", "한국은행", "기준금리", "연준", "FOMC", "재정경제부", "기획예산처", "금융위",
    "금감원", "공정위", "국세청", "트럼프", "관세", "수출", "물가", "성장률", "GDP", "코스피", "나스닥", "S&P",
    "반도체", "삼성전자", "SK하이닉스", "현대차", "엔비디아", "애플", "테슬라", "예산안", "세법", "상법",
    "부동산", "가계부채", "고용", "실업",
)
# 기업 홍보성 기사(수상·인증·협약·행사)는 여러 매체가 받아써도 그날의 이슈로 보지 않는다.
_PR = re.compile(r"(수상|등급\s?획득|[A-Z]\+?등급|인증\s?획득|인증을 획득|에 선정|선정돼|선정됐|업무협약|MOU|협약 체결|"
                 r"기부|봉사|후원|성금|기탁|나눔|발대식|캠페인|개최|개막|간담회|설명회|세미나|포럼|박람회|데모데이|시상식)")
# 매일 같은 형식으로 나오는 시세 기사(환율·채권 마감 등)
_ROUTINE = re.compile(r"^\s*\[(외환|채권|마감시황|시황|오늘의 증시|코스피|코스닥|국고채|환율|증시|장중시황|개장시황)\]|"
                      r"기준가\)|장 초반|(상승|하락) 출발|(상승|하락|보합) 마감|국고채 금리 .*\d년물")
_MEDIA = re.compile(r"^\s*\[(포토|영상|사진|카드뉴스|그래픽)\]")


def quality_adjust(item: NewsItem, cat_key: str | None) -> float:
    """그날의 주요 이슈인지에 따른 가감점: 큰 주체·지표 +3, 홍보성 -6, 시세 기사 -5, 사진·영상 -10, 지자체 -6."""
    title = item.title or ""
    adj = 0.0
    if any(k in title for k in BIG_KEYWORDS):
        adj += 3
    if _PR.search(title):
        adj -= 6
    if _ROUTINE.search(title):
        adj -= 5
    if _MEDIA.search(title):
        adj -= 10
    if is_local(item, cat_key):
        adj -= 6
    return adj


def categorize(items: list[NewsItem], categories: list[dict], per_category: int,
               counts: dict[str, dict] | None = None) -> dict[str, list[NewsItem]]:
    """기사를 분류하고 분류마다 점수 높은 순으로 per_category건만 남긴다.
    counts를 넘기면 자르기 전 분류별 기사 묶음 수(stories)와 보도 건수(articles)를 채운다(주간 이슈 지도용)."""
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
        direct = 1.0 if it.origin != "구글뉴스" else 0.0  # 주요 언론사 직접 피드를 조금 앞세운다
        it.score = score + recency + direct
        merged = next((k for k in buckets[key] if same_story(k, it)), None)
        if merged:
            merged.coverage += it.coverage
            if it.source and it.source != merged.source and it.source not in merged.also:
                merged.also.append(it.source)
            continue
        buckets[key].append(it)
    for key in buckets:
        for it in buckets[key]:
            # 여러 곳이 다룬 기사, 전국 단위 언론이 다룬 기사, 큰 주제를 앞세우고 홍보성·시세·지자체 기사는 뒤로
            it.score += min(it.coverage, 6) * 1.2 + min(major_count(it), 3) * 0.8 + quality_adjust(it, key)
    for key in buckets:
        if counts is not None:
            counts[key] = {"stories": len(buckets[key]), "articles": sum(it.coverage for it in buckets[key])}
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
