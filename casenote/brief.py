"""노트 맨 위 '오늘 아침 이것만은'.

바쁜 날에도 1분 안에 그날의 핵심 경영·경제 이슈를 파악하도록, 전날 기사 가운데
여러 언론이 함께 다룬 이슈를 분야가 겹치지 않게 몇 개만 골라 한 줄씩 보여 준다.
비용이 들지 않도록 규칙으로만 고른다.
"""

from __future__ import annotations

import re

from . import explain as ex
from .news import NewsItem, _subject_and_tokens, major_count, quality_adjust
from .util import fmt_krw

# 경제 전체에 영향을 주는 분야일수록 앞세운다. 목록에 없는 분야는 0.
CATEGORY_WEIGHT = {
    "macro": 4, "global": 3, "trade": 3, "fiscal": 2, "tax": 2, "policy": 2, "earnings": 2, "ma": 2,
    "governance": 2, "capital": 1, "ipo": 1, "split": 1, "competition": 1, "supply": 1,
}

_LEAD_TAGS = re.compile(r"^(\s*[\[\(【<][^\]\)】>]{0,20}[\]\)】>]\s*)+")
_TRAIL_TAGS = re.compile(r"(\s*[\[\(【<][^\]\)】>]{0,20}[\]\)】>]\s*)+$")
_TRAIL_SHOW = re.compile(r"\s*[|｜]\s*[^|｜]{1,20}$")  # '…｜빽투빽' 같은 프로그램·코너 이름
_MAGNITUDE = re.compile(r"\d[\d,.]*\s*(?:%p|%|％|조|억|만|원|달러|엔|위안|유로|배|명|건|곳|개|척|대|톤|bp|포인트)")


def importance(item: NewsItem, cat_key: str | None) -> float:
    """보도량(8곳까지) + 전국 단위 언론 수 + 분야 가중치 + 주제 가감점(큰 주제 +, 홍보성·시세·지자체 -)."""
    return (min(item.coverage, 8) + 2.0 * min(major_count(item), 4) + CATEGORY_WEIGHT.get(cat_key or "", 0)
            + quality_adjust(item, cat_key))


def clean_headline(title: str) -> str:
    """'[다음주 경제] 숨 고르기 한 기준금리…' → '숨 고르기 한 기준금리…'.
    앞뒤 말머리([단독], [월가월부], (종합) 등)와 코너 이름만 뗀다."""
    t = _TRAIL_TAGS.sub("", _TRAIL_SHOW.sub("", _LEAD_TAGS.sub("", title or ""))).strip()
    return re.sub(r"\s*(\.\.\.|…)\s*", "…", t).strip()  # 따옴표는 짝이 깨지지 않게 그대로 둔다


def drop_question(head: str) -> str:
    """'…엔비디아 급등, 한국 증시에 가져온 건?' → '…엔비디아 급등'. 물음으로 끝나는 마지막 토막만 덜어 낸다."""
    if not head.endswith("?"):
        return head
    parts = head.split("…")
    last = parts[-1]
    if "," in last and len(last.rsplit(",", 1)[0].strip()) >= 2:
        parts[-1] = last.rsplit(",", 1)[0].strip()
        return "…".join(parts)
    if len(parts) > 1 and len("…".join(parts[:-1])) >= 8:
        return "…".join(parts[:-1])
    return head


def has_magnitude(text: str) -> bool:
    return bool(_MAGNITUDE.search(text or ""))


def story_text(item: NewsItem) -> str:
    """한 줄 요약. 기사 첫 문장이 있으면 그것을 쓰되, 핵심 숫자는 제목에만 있으면 제목을 쓴다."""
    head = clean_headline(item.title)
    lead = ex.lead_sentence(getattr(item, "summary", ""), item.title)
    if len(lead) > 110:
        lead = ""
    if lead and (has_magnitude(lead) or not has_magnitude(head) or head.endswith("?")):
        return lead
    return drop_question(head)


def _overlaps(a: NewsItem, b: NewsItem) -> bool:
    sa, ta = _subject_and_tokens(a.title)
    sb, tb = _subject_and_tokens(b.title)
    if sa and sa == sb:
        return True
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.35


def notable_case(block: dict, th: dict) -> bool:
    """대형 공시만 아침 요약에 올린다(거래 1,000억원 이상 또는 자산 5조원 이상 회사)."""
    ev = block["ev"]
    assets = (ev.fin or {}).get("assets") or 0
    return (ev.amount or 0) >= 1e11 or assets >= th.get("disclosure_group_assets", 5e12)


def case_text(block: dict) -> str:
    """공시 사례의 첫 문장(예: '배터리 제조 기업 ○○가 △△과 합병한다.'). 해설이 없으면 '회사 유형(금액)'."""
    what = re.sub(r"\s*\(앞서 제출한 공시를 정정한 공시이다\.\)", "", (block.get("easy") or {}).get("what") or "").strip()
    first = re.match(r"(.+?다\.)(\s|$)", what)
    if first:
        return first.group(1)
    ev = block["ev"]
    size = f"({ev.amount_label or '금액'} {fmt_krw(ev.amount)})" if ev.amount else ""
    return f"{ev.corp_name} {ev.rule.label}{size}"


def pick_brief(buckets: dict[str, list[NewsItem]], categories: list[dict], news_cases: list[dict],
               case_blocks: list[dict], th: dict, limit: int = 3) -> list[dict]:
    """아침 요약 항목. 뉴스 limit개(분야마다 하나, 같은 이슈 중복 없이)와 대형 공시 1건까지.
    항목: text(한 줄), tag(분야), link(기사 주소), anchor(노트 안 자세한 설명 위치, 없으면 빈 값)."""
    labels = {c["key"]: c["label"] for c in categories}
    case_anchor = {id(nc["item"]): f"n{i}" for i, nc in enumerate(news_cases, 1)}
    case_link = {nc["item"].link: f"n{i}" for i, nc in enumerate(news_cases, 1)}
    pool = []
    for key, items in (buckets or {}).items():
        for it in items:
            if it.coverage >= 2 or major_count(it) >= 1:
                pool.append((importance(it, key), key, it))
    pool.sort(key=lambda x: x[0], reverse=True)
    picked: list[tuple[str, NewsItem]] = []
    used_cats: set[str] = set()
    for _, key, it in pool:
        if len(picked) >= limit:
            break
        if key in used_cats or any(_overlaps(it, p) for _, p in picked):
            continue
        picked.append((key, it))
        used_cats.add(key)
    out = [{
        "text": story_text(it),
        "tag": labels.get(key, ""),
        "link": it.link,
        "anchor": case_anchor.get(id(it)) or case_link.get(it.link, ""),
    } for key, it in picked]
    for i, b in enumerate(case_blocks, 1):
        if notable_case(b, th):
            out.append({"text": case_text(b), "tag": "공시", "link": b["ev"].url, "anchor": f"c{i}"})
            break
    return out
