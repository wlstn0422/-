"""데이터를 모아 리포트(마크다운)와 기록(JSON)을 만든다."""

from __future__ import annotations

import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import ai as ai_mod
from . import theory as th_mod
from .dart import CorpIndex, DartClient, DartError, DartFatalError, viewer_url
from .events import (
    GROUP_LABELS,
    RULE_THEORIES,
    Event,
    attach_details,
    build_events,
    context_notes,
    pick_key_cases,
    related_for,
    score_event,
)
from .financials import (
    CompanyFinancials,
    cf_lifecycle,
    compute_ratios,
    fetch_snapshot,
    load_company_financials,
    quality_notes,
    tax_view,
)
from .knowledge import build_quiz, card_by_id, select_cards
from .news import categorize, collect_news, match_company_news
from .scale import build_scale, company_list, industry_of, industry_rows, load_scale, needs_refresh
from .settings import Settings
from .sizing import budget_drills, ladder_position, leader_compare, money_sense, size_checklist, size_class
from .util import (
    date_ko,
    filing_window,
    fmt_int,
    fmt_krw,
    fmt_pct,
    fmt_times,
    josa,
    latest_annual_year,
    first_paragraph,
    html_text,
    md_cell,
    md_link_text,
    md_paragraphs,
    now_kst,
    parse_ymd,
    pct,
    today_kst,
    ymd,
)

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

ALIASES = {
    "현대차": "005380", "현대자동차": "005380", "네이버": "035420", "삼전": "005930", "하이닉스": "000660",
    "엘지전자": "066570", "에스케이하이닉스": "000660", "삼바": "207940", "엔솔": "373220", "LG엔솔": "373220",
    "에쓰오일": "010950", "에스오일": "010950", "포스코홀딩스": "005490", "SKT": "017670", "카뱅": "323410",
}
SALARY_MIN_STAFF = 500  # 업종 규모 지도의 평균 급여 순위에 넣을 최소 직원 수


def jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(krw=fmt_krw, pct=fmt_pct, cell=md_cell, times=fmt_times, intf=fmt_int, linktext=md_link_text,
                       paras=md_paragraphs, first_para=first_paragraph, htmltext=html_text)
    env.globals.update(josa=josa)
    return env


def render(template: str, **ctx) -> str:
    return jinja_env().get_template(template).render(**ctx)


# --------------------------------------------------------------------- 기록(아카이브)
def archive_path(settings: Settings, day: date) -> Path:
    return settings.archive_dir / f"{day.isoformat()}.json"


def last_archive_date(settings: Settings, before: date) -> date | None:
    if not settings.archive_dir.exists():
        return None
    days = []
    for p in settings.archive_dir.glob("*.json"):
        d = parse_ymd(p.stem)
        if d and d < before:
            days.append(d)
    return max(days) if days else None


def daily_report_path(settings: Settings, day: date) -> Path:
    return settings.reports_dir / "daily" / str(day.year) / f"{day.isoformat()}.md"


# --------------------------------------------------------------------- DART 수집
def collect_filings(client: DartClient, start: date, end: date, warnings: list[str]) -> list[dict]:
    plans = [
        ("B", None, None, "주요사항보고서"),
        ("I", None, None, "거래소 수시공시"),
        ("C", "E", "C001", "증권신고서(IPO)"),
        ("D", None, "D004", "공개매수"),
    ]
    filings: list[dict] = []
    for ty, cls, detail, label in plans:
        try:
            filings.extend(client.list_filings(ymd(start), ymd(end), pblntf_ty=ty, corp_cls=cls, pblntf_detail_ty=detail))
        except DartFatalError:
            raise
        except DartError as exc:
            log.info("%s 목록 조회 실패: %s", label, exc)
            if ty in ("B", "I"):
                warnings.append(f"{label} 목록을 가져오지 못했습니다({exc.status}).")
    return filings


def corp_from_query(index: CorpIndex, settings: Settings, query: str):
    aliases = dict(ALIASES)
    for c in company_list(settings):
        aliases.setdefault(c["name"], c["code"])
    return index.find(query, aliases)


# --------------------------------------------------------------------- 기업 분석 묶음
def company_context(cf: CompanyFinancials, settings: Settings, scale: dict, listed: bool = True) -> dict:
    th = settings.benchmarks["thresholds"]
    cur = cf.cur
    prev = cf.prev
    ratios = compute_ratios(cur, prev)
    trend = []
    for y in sorted(cf.years.keys())[-6:]:
        v = cf.years[y]
        trend.append({
            "year": y,
            "revenue": v.get("revenue"),
            "operating_income": v.get("operating_income"),
            "op_margin": pct(v.get("operating_income"), v.get("revenue")),
            "net_income": v.get("net_income"),
            "assets": v.get("assets"),
            "debt_ratio": pct(v.get("liabilities"), v.get("equity")) if (v.get("equity") or 0) > 0 else None,
        })
    below_a, above_a = ladder_position(cur.get("assets"), settings.benchmarks.get("asset_ladder", []))
    below_r, above_r = ladder_position(cur.get("revenue"), settings.benchmarks.get("revenue_ladder", []))
    industry = industry_of(scale, cf.corp_code) or industry_of_code(settings, cf.stock_code)
    ind_cfg = next((i for i in settings.industries if i.get("name") == industry), {}) if industry else {}
    by_tid = th_mod.theory_by_id(settings.theories)
    industry_theories = th_mod.theories_for(list(ind_cfg.get("theories", [])), by_tid, limit=3)
    comp_row = {"corp_code": cf.corp_code, "revenue": cur.get("revenue"), "operating_income": cur.get("operating_income")}
    leader = leader_compare(comp_row, industry_rows(scale, industry)) if industry else []
    tv = tax_view(cur, cf.year, settings.benchmarks)
    life = cf_lifecycle(cur.get("ocf"), cur.get("icf"), cur.get("fin_cf"))
    separate = cf.separate.get(cf.year, {})
    dupont = None
    if ratios.get("roe") is not None and ratios.get("asset_turnover") and ratios.get("leverage"):
        dupont = {
            "net_margin": ratios.get("net_margin"),
            "asset_turnover": ratios.get("asset_turnover"),
            "leverage": ratios.get("leverage"),
            "roe": ratios.get("roe"),
        }
    return {
        "name": cf.corp_name,
        "corp_code": cf.corp_code,
        "year": cf.year,
        "fs_label": "연결" if cf.fs_div == "CFS" else "별도",
        "company": cf.company,
        "industry": industry,
        "industry_profile": ind_cfg.get("profile"),
        "industry_theories": industry_theories,
        "cur": cur,
        "ratios": ratios,
        "trend": trend,
        "size_class": size_class(cur.get("revenue"), cur.get("assets"), th),
        "checklist": size_checklist(cur.get("revenue"), cur.get("assets"), listed, th),
        "ladder": {"asset_below": below_a, "asset_above": above_a, "rev_below": below_r, "rev_above": above_r},
        "leader": leader,
        "industry_table": sorted(industry_rows(scale, industry), key=lambda r: r.get("revenue") or 0, reverse=True) if industry else [],
        "tax": tv,
        "lifecycle": life,
        "quality": quality_notes(ratios, cur),
        "dupont": dupont,
        "employees": cf.employees,
        "money": money_sense(cur, cf.employees, separate, settings.benchmarks.get("anchors", [])),
        "drills": budget_drills(cur, cf.corp_name),
    }


def industry_of_code(settings: Settings, stock_code: str | None) -> str | None:
    """규모 지도가 아직 없을 때 업종 목록(industries.yaml)에서 업종을 찾는다."""
    if not stock_code:
        return None
    for c in company_list(settings):
        if c["code"] == stock_code:
            return c["industry"]
    return None


def pick_company_of_day(settings: Settings, index: CorpIndex, day: date) -> tuple[str, str, str] | None:
    """(고유번호, 이름, 종목코드). 금융업을 뺀 업종 대표 기업을 날짜 순서로 돌린다."""
    pool = [c for c in company_list(settings) if not c["financial"]]
    if not pool:
        return None
    for i in range(len(pool)):
        c = pool[(day.toordinal() + i) % len(pool)]
        corp = index.by_stock.get(c["code"])
        if corp:
            return corp.corp_code, c["name"], c["code"]
    return None


# --------------------------------------------------------------------- 일일 리포트
def run_daily(settings: Settings, day: date | None = None, *, use_news: bool = True, use_dart: bool = True,
              use_ai: bool = True, out_dir: Path | None = None, client: DartClient | None = None,
              news_fetcher=None) -> Path:
    day = day or today_kst()
    rc = settings.report_cfg
    warnings: list[str] = []
    last = last_archive_date(settings, before=day)
    start, end = filing_window(day, last, int(rc.get("max_window_days", 7)))

    # 뉴스
    news_items, buckets, news_errors = [], {}, []
    news_counts: dict[str, dict] = {}
    categories = settings.news_sources.get("categories", [])
    if use_news:
        fetcher = news_fetcher or (lambda: collect_news(
            settings.news_sources,
            lookback_hours=float(settings.config["news"].get("lookback_hours", 30)),
            timeout=float(settings.config["news"].get("timeout_sec", 15)),
        ))
        news_items, news_errors = fetcher()
        buckets = categorize(news_items, categories, int(rc.get("news_per_category", 5)), counts=news_counts)
        if news_errors:
            log.info("뉴스 피드 실패 %d건: %s", len(news_errors), "; ".join(news_errors[:5]))
        if not news_items:
            warnings.append("뉴스를 한 건도 가져오지 못했습니다(네트워크 또는 피드 주소 확인).")

    # DART
    events: list[Event] = []
    key_cases: list[Event] = []
    company_ctx = None
    scale = load_scale(settings)
    dart_status = "off"
    year = latest_annual_year(day)
    watch = set(settings.config.get("watchlist") or [])
    if use_dart and (client or settings.dart_api_key):
        client = client or DartClient(
            settings.dart_api_key, cache_dir=settings.cache_dir,
            interval=float(settings.config["dart"].get("request_interval_sec", 0.2)),
        )
        dart_status = "ok"
        try:
            index = client.corp_index()
            filings = collect_filings(client, start, end, warnings)
            events = build_events(filings, list(rc.get("markets", ["Y", "K"])))
            attach_details(client, events, ymd(start), ymd(end))
            for ev in events:
                score_event(ev, watch)
            th = settings.benchmarks["thresholds"]
            candidates = sorted(events, key=lambda e: e.score, reverse=True)[:15]
            for ev in candidates:
                if ev.corp_cls in ("Y", "K"):
                    ev.fin = fetch_snapshot(client, ev.corp_code, year)
                    if ev.fin:
                        ev.size_class = size_class(ev.fin.get("revenue"), ev.fin.get("assets"), th)
            for ev in events:
                score_event(ev, watch)
            key_cases = pick_key_cases(events, int(rc.get("key_cases", 3)))
            if needs_refresh(settings, year):
                log.info("업종 규모 지도를 새로 만든다(%s년)", year)
                scale = build_scale(client, settings, index, year)
            pick = pick_company_of_day(settings, index, day)
            if pick:
                cf = load_company_financials(client, pick[0], pick[1], year)
                if cf:
                    cf.stock_code = pick[2]
                    cf.company = client.company(pick[0])
                    company_ctx = company_context(cf, settings, scale)
        except DartFatalError as exc:
            dart_status = "error"
            warnings.append(f"DART 사용 중단: {exc.message}. 키 설정이나 하루 호출 한도를 확인하세요.")
        except DartError as exc:
            dart_status = "error"
            warnings.append(f"DART 조회 중 오류: {exc}")
    elif use_dart:
        dart_status = "nokey"
        warnings.append("DART_API_KEY가 없어 공시·재무 분석을 건너뛰었습니다. README의 'DART 키 발급' 순서대로 등록하면 채워집니다.")

    # 사례별 관련 기사와 숫자 문장
    if news_items and key_cases:
        related = match_company_news([e.corp_name for e in key_cases], news_items, limit=10)
        for ev in key_cases:
            ev.related_news = related_for(ev, related.get(ev.corp_name, []))[:3]
    by_tid = th_mod.theory_by_id(settings.theories)
    biz_theories, subject_cards = th_mod.split_library(settings.theories)
    case_blocks = []
    cards_map = card_by_id(settings.cards)
    for ev in key_cases:
        card = cards_map.get(ev.rule.card or "", {})
        case_blocks.append({
            "ev": ev,
            "numbers": context_notes(ev),
            "card": card,
            "accounting": (card.get("accounting") or [])[:2],
            "tax": (card.get("tax") or [])[:2],
            "law": (card.get("law") or [])[:1],
            "questions": (card.get("questions") or [])[:2],
            "theories": th_mod.theories_for(RULE_THEORIES.get(ev.rule.key, []), by_tid, limit=2),
            "subjects": th_mod.subject_cards_for_rule(ev.rule.key, subject_cards, limit=3),
        })

    # 뉴스로 보는 사례(재무·경영·경제·제도 분야에서 하나씩)
    repeat_days = int(rc.get("theory_repeat_days", 21))
    recent = th_mod.recent_lessons(settings.archive_dir, day, repeat_days)
    subject_recent = th_mod.recent_lessons(settings.archive_dir, day, repeat_days, key="subject_lessons")
    news_cases = th_mod.pick_news_cases(buckets, categories, by_tid, recent + subject_recent,
                                        int(rc.get("news_cases", 4))) if buckets else []
    ranked_cats = sorted((c for c in categories if buckets.get(c["key"])),
                         key=lambda c: buckets[c["key"]][0].score, reverse=True)
    links_ctx = (case_blocks, news_cases, company_ctx, buckets, categories)

    # 오늘의 이론 수업(경영·경제)
    candidates: list[str] = []
    for b in case_blocks:
        candidates += [t["id"] for t in b["theories"]] * 2
    for nc in news_cases:
        candidates += [nc["theory"]["id"]] * 2 + [t["id"] for t in nc["others"]]
    if company_ctx:
        candidates += [t["id"] for t in company_ctx.get("industry_theories", [])]
    # 오늘 사례 이론이 이번 바퀴에서 다 나왔을 때 쓸 2순위: 오늘 기사가 있는 분야의 이론, 사례 이론과 이어진 이론
    pool: list[str] = []
    for cat in ranked_cats:
        pool += cat.get("theories") or []
    for tid in candidates:
        pool += by_tid.get(tid, {}).get("related") or []
    lesson_blocks = _lesson_blocks(biz_theories, candidates, pool, recent, day, int(rc.get("theory_lessons", 1)),
                                   th_mod.lesson_history(settings.archive_dir, day), by_tid, links_ctx)

    # 오늘의 전공 수업(요일별 재무회계·원가관리회계·세법·상법·재정학)
    subject = th_mod.subject_of_day(day, list(rc.get("subject_rotation") or th_mod.DEFAULT_SUBJECT_ROTATION))
    today_cards = [t for t in subject_cards if t["field"] == subject]
    s_candidates = th_mod.subject_candidates(
        today_cards, [b["ev"].rule.key for b in case_blocks],
        [nc["category"]["key"] for nc in news_cases] + [c["key"] for c in ranked_cats])
    s_pool: list[str] = []
    for tid in s_candidates:
        s_pool += by_tid.get(tid, {}).get("related") or []
    subject_blocks = _lesson_blocks(
        today_cards, s_candidates, s_pool, subject_recent, day, int(rc.get("subject_lessons", 1)),
        th_mod.lesson_history(settings.archive_dir, day, key="subject_lessons"), by_tid, links_ctx)

    # AI 해설
    ai_notes = {"cases": {}, "news": {}}
    if use_ai and (key_cases or news_cases):
        ai_notes = ai_mod.commentary(key_cases, news_cases, settings)

    # 공시 목록(유형 묶음별)
    groups = []
    per_type = int(rc.get("filings_per_type", 12))
    for gkey, glabel in GROUP_LABELS.items():
        evs = [e for e in events if e.rule.group == gkey]
        if not evs:
            continue
        evs.sort(key=lambda e: (e.score, e.rcept_no), reverse=True)
        groups.append({"label": glabel, "count": len(evs), "events": evs[:per_type], "more": max(0, len(evs) - per_type)})

    # 퀴즈: 전공 수업 1문제, 이론 수업·뉴스 사례 2문제, 회계·세무 카드와 돈 감각 문제
    news_cards = []
    for cat in categories:
        if buckets.get(cat["key"]):
            news_cards.extend(cat.get("cards", [])[:1])
    case_cards = [e.rule.card for e in key_cases if e.rule.card]
    cards = select_cards(settings.cards, case_cards, news_cards, day, limit=int(rc.get("accounting_cards", 2)))
    company_for_quiz = (company_ctx["name"], company_ctx["cur"], company_ctx["year"]) if company_ctx else None
    rng = random.Random(int(day.strftime("%Y%m%d")) + 7)
    biz_lessons = [b["theory"] for b in lesson_blocks]
    quiz = th_mod.theory_quiz([b["theory"] for b in subject_blocks], rng, n=1)
    quiz += th_mod.theory_quiz(biz_lessons + [nc["theory"] for nc in news_cases if nc["theory"] not in biz_lessons],
                               rng, n=2)
    quiz += build_quiz(day, cards, settings.benchmarks, company_for_quiz, scale.get("rows", []))
    quiz = quiz[:6]
    for q in quiz:
        q["answer_label"] = "ABCD"[q["answer"]] if q["answer"] < 4 else str(q["answer"] + 1)

    # 뉴스 헤드라인(분야별 대표 기사와 보도량)
    news_sections = []
    for cat in categories:
        items = buckets.get(cat["key"]) or []
        if items:
            cnt = news_counts.get(cat["key"], {})
            news_sections.append({"key": cat["key"], "label": cat["label"], "entries": items,
                                  "stories": cnt.get("stories", len(items)), "articles": cnt.get("articles", len(items))})
    busiest = sorted(news_sections, key=lambda x: x["articles"], reverse=True)[:3]

    lesson_where = {b["theory"]["id"]: "3장 '오늘의 이론 수업'" for b in lesson_blocks}
    lesson_where.update({b["theory"]["id"]: "4장 '오늘의 전공 수업'" for b in subject_blocks})
    ctx = {
        "title": rc.get("title", "매일 경영·경제 케이스 노트"),
        "day": day,
        "date_ko": date_ko(day),
        "window": (start, end),
        "generated_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        "warnings": warnings,
        "dart_status": dart_status,
        "events_total": len(events),
        "case_blocks": case_blocks,
        "news_cases": news_cases,
        "lessons": lesson_blocks,
        "subject": subject,
        "weekday_ko": "월화수목금토일"[day.weekday()],
        "subject_lessons": subject_blocks,
        "lesson_where": lesson_where,
        "subject_fields": th_mod.SUBJECT_FIELDS,
        "story_labels": th_mod.STORY_LABELS,
        "ai_notes": ai_notes,
        "groups": groups,
        "company": company_ctx,
        "news_sections": news_sections,
        "busiest": busiest,
        "news_total": len(news_items),
        "cards": cards,
        "quiz": quiz,
        "viewer_url": viewer_url,
        "theory_book": "../../theories.md",
    }
    md = render("daily.md.j2", **ctx)
    out = Path(out_dir) / f"{day.isoformat()}.md" if out_dir else daily_report_path(settings, day)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    if not out_dir:
        settings.archive_dir.mkdir(parents=True, exist_ok=True)
        archive = {
            "date": day.isoformat(),
            "window": [start.isoformat(), end.isoformat()],
            "dart_status": dart_status,
            "key_cases": [e.to_dict() for e in key_cases],
            "event_counts": {g["label"]: g["count"] for g in groups},
            "news": {s["label"]: [n.to_dict() for n in s["entries"]] for s in news_sections},
            "news_counts": news_counts,
            "cards": [c["id"] for c in cards],
            "lessons": [b["theory"]["id"] for b in lesson_blocks],
            "subject": subject,
            "subject_lessons": [b["theory"]["id"] for b in subject_blocks],
            "news_cases": [{"title": nc["item"].title, "link": nc["item"].link, "category": nc["category"]["label"],
                            "theory": nc["theory"]["id"]} for nc in news_cases],
            "quiz": quiz,
            "company": company_ctx["name"] if company_ctx else None,
        }
        archive_path(settings, day).write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
        write_reports_index(settings)
    return out


def _applied_for(t: dict, links_ctx) -> list[dict]:
    """이 카드를 대입해 볼 오늘의 사례: 공시 사례, 뉴스 사례, 오늘의 기업, 그리고 브리핑 기사."""
    case_blocks, news_cases, company_ctx, buckets, categories = links_ctx
    filings = th_mod.applies(t, "filings")
    news_keys = th_mod.applies(t, "news")
    applied = []
    for b in case_blocks:
        if t["id"] in [x["id"] for x in b["theories"]] or b["ev"].rule.key in filings:
            applied.append({"kind": "공시", "title": f"{b['ev'].corp_name} {b['ev'].rule.label}", "link": b["ev"].url})
    for nc in news_cases:
        if (t["id"] == nc["theory"]["id"] or t["id"] in [x["id"] for x in nc["others"]]
                or nc["category"]["key"] in news_keys):
            applied.append({"kind": "뉴스", "title": nc["item"].title, "link": nc["item"].link})
    if company_ctx and t["id"] in [x["id"] for x in company_ctx.get("industry_theories", [])]:
        applied.append({"kind": "오늘의 기업", "title": f"{company_ctx['name']}({company_ctx['industry']})", "link": None})
    links = {a["link"] for a in applied if a["link"]}
    for it in th_mod.briefing_articles(t, buckets, categories, limit=4, extra_keys=news_keys):
        if len(applied) >= 3:
            break
        if it.link not in links:
            applied.append({"kind": "기사", "title": it.title, "link": it.link})
            links.add(it.link)
    return applied[:4]


def _lesson_blocks(library: list[dict], candidates: list[str], pool: list[str], recent: list[str], day: date,
                   n: int, history: list[str], by_tid: dict[str, dict], links_ctx) -> list[dict]:
    """수업 고르기(한 바퀴 다 돌기 전에는 반복 없음)와 노트에 넣을 정보 묶기."""
    if not library or n <= 0:
        return []
    ids = {t["id"] for t in library}
    done = th_mod.taught_this_round(history, ids)
    picked = th_mod.pick_lessons(library, candidates, recent, day, n, done=done, pool=pool)
    blocks = []
    round_done = set(done)
    for t in picked:
        round_done.add(t["id"])
        progress = len(round_done)
        if round_done >= ids:
            round_done = set()
        blocks.append({
            "theory": t,
            "applied": _applied_for(t, links_ctx),
            "progress": progress,
            "total": len(ids),
            "story": th_mod.story_labels(t["field"]) if t.get("law") else None,
            "related": th_mod.theories_for(list(t.get("related", [])), by_tid, limit=4),
        })
    return blocks


# --------------------------------------------------------------------- 기업 분석 리포트
def run_company(settings: Settings, query: str, year: int | None = None, client: DartClient | None = None) -> Path:
    if not (client or settings.dart_api_key):
        raise SystemExit("기업 분석에는 DART_API_KEY가 필요합니다. README의 'DART 키 발급'을 참고하세요.")
    client = client or DartClient(settings.dart_api_key, cache_dir=settings.cache_dir,
                                  interval=float(settings.config["dart"].get("request_interval_sec", 0.2)))
    index = client.corp_index()
    corp = corp_from_query(index, settings, query)
    if not corp:
        raise SystemExit(f"'{query}'에 해당하는 상장사를 찾지 못했습니다. 종목코드 6자리로도 시도해 보세요.")
    day = today_kst()
    year = year or latest_annual_year(day)
    cf = load_company_financials(client, corp.corp_code, corp.corp_name, year, history_years=6)
    if not cf:
        raise SystemExit(f"{corp.corp_name}의 재무 자료를 DART에서 찾지 못했습니다(금융업은 재무 API 범위 밖일 수 있음).")
    cf.stock_code = corp.stock_code
    cf.company = client.company(corp.corp_code)
    scale = load_scale(settings)
    ctx = company_context(cf, settings, scale)
    extra = {"audit": [], "dividends": [], "holders": []}
    for key, fn in (("audit", client.auditor_opinion), ("dividends", client.dividends), ("holders", client.major_shareholders)):
        try:
            extra[key] = fn(corp.corp_code, cf.year)
        except DartFatalError:
            raise
        except DartError as exc:
            log.info("%s 조회 실패: %s", key, exc)
    md = render(
        "company.md.j2",
        c=ctx,
        corp=corp,
        extra=extra,
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M"),
        cards=[card_by_id(settings.cards).get(k) for k in ("earnings", "shareholder_return") if card_by_id(settings.cards).get(k)],
        theory_book="../theories.md",
    )
    safe = "".join(ch for ch in corp.corp_name if ch.isalnum() or ch in "-_")
    out = settings.reports_dir / "company" / f"{corp.stock_code}_{safe}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    write_reports_index(settings)
    return out


# --------------------------------------------------------------------- 규모 지도
def run_scale(settings: Settings, year: int | None = None, client: DartClient | None = None, rebuild: bool = True) -> Path:
    year = year or latest_annual_year(today_kst())
    scale = load_scale(settings)
    if rebuild or not scale:
        if not (client or settings.dart_api_key):
            raise SystemExit("규모 지도를 만들려면 DART_API_KEY가 필요합니다.")
        client = client or DartClient(settings.dart_api_key, cache_dir=settings.cache_dir,
                                      interval=float(settings.config["dart"].get("request_interval_sec", 0.2)))
        scale = build_scale(client, settings, client.corp_index(), year)
    rows = scale.get("rows", [])
    industries = []
    for ind in settings.industries:
        r = sorted([x for x in rows if x.get("industry") == ind["name"]], key=lambda x: x.get("revenue") or 0, reverse=True)
        leader_rev = r[0].get("revenue") if r and r[0].get("revenue") else None
        for x in r:
            x["vs_leader"] = pct(x.get("revenue"), leader_rev) if leader_rev else None
        industries.append({"name": ind["name"], "rows": r, "financial": bool(ind.get("financial"))})
    top = sorted([x for x in rows if x.get("revenue") and not x.get("financial")], key=lambda x: x["revenue"], reverse=True)[:20]
    # 직원 수십 명인 지주회사는 임원급 소수라 평균이 튄다. 순위는 직원 SALARY_MIN_STAFF명 이상만 매기고 따로 보여 준다.
    paid = sorted([x for x in rows if x.get("avg_salary")], key=lambda x: x["avg_salary"], reverse=True)
    salary = [x for x in paid if (x.get("employees") or 0) >= SALARY_MIN_STAFF][:15]
    small_staff = [x for x in paid if (x.get("employees") or 0) < SALARY_MIN_STAFF]
    md = render(
        "scale.md.j2",
        year=scale.get("year", year),
        industries=industries,
        top=top,
        salary=salary,
        small_staff=small_staff,
        salary_min_staff=SALARY_MIN_STAFF,
        bm=settings.benchmarks,
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M"),
    )
    out = settings.reports_dir / "scale.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    write_reports_index(settings)
    return out


# --------------------------------------------------------------------- 주간 복습
def run_weekly(settings: Settings, day: date | None = None) -> Path | None:
    day = day or today_kst()
    start = day - timedelta(days=7)
    days = []
    for i in range(7, 0, -1):
        d = day - timedelta(days=i)
        p = archive_path(settings, d)
        if p.exists():
            days.append(json.loads(p.read_text(encoding="utf-8")))
    if not days:
        log.info("지난 7일 기록이 없어 주간 복습을 만들지 않음")
        return None
    counts: dict[str, int] = {}
    cases = []
    quiz = []
    companies = []
    news_cases = []
    lesson_ids: list[str] = []
    by_tid = th_mod.theory_by_id(settings.theories)
    cat_label = {c["key"]: c["label"] for c in settings.news_sources.get("categories", [])}
    subject_rows = []
    issue: dict[str, dict] = {}
    stories: dict[str, dict] = {}
    for d in days:
        for tid in d.get("subject_lessons") or []:
            if tid in by_tid:
                subject_rows.append({"day": d["date"], "subject": d.get("subject") or by_tid[tid]["field"],
                                     "theory": by_tid[tid]})
        for key, c in (d.get("news_counts") or {}).items():
            n = int((c or {}).get("articles", 0))
            if n:
                row = issue.setdefault(key, {"label": cat_label.get(key, key), "by_day": {}, "total": 0})
                row["by_day"][d["date"]] = n
                row["total"] += n
        for label, entries in (d.get("news") or {}).items():
            for n in entries:
                prev = stories.get(n.get("title", ""))
                if not prev or n.get("coverage", 1) > prev.get("coverage", 1):
                    stories[n.get("title", "")] = {**n, "day": d["date"], "label": label}
        for k, v in (d.get("event_counts") or {}).items():
            counts[k] = counts.get(k, 0) + int(v)
        for c in d.get("key_cases") or []:
            cases.append({**c, "day": d["date"]})
        for n in d.get("news_cases") or []:
            news_cases.append({**n, "day": d["date"]})
        for tid in d.get("lessons") or []:
            if tid not in lesson_ids:
                lesson_ids.append(tid)
        quiz.extend(d.get("quiz") or [])
        if d.get("company"):
            companies.append({"day": d["date"], "name": d["company"]})
    rng = random.Random(int(day.strftime("%Y%m%d")))
    issue_days = [d["date"] for d in days if d.get("news_counts")]
    issue_rows = sorted(issue.values(), key=lambda r: r["total"], reverse=True)[:8]
    top_stories = sorted(stories.values(), key=lambda n: n.get("coverage", 1), reverse=True)[:5]
    if len(quiz) > 8:
        quiz = rng.sample(quiz, 8)
    iso = day.isocalendar()
    md = render(
        "weekly.md.j2",
        day=day,
        start=start,
        week=f"{iso[0]}년 {iso[1]}주차",
        counts=sorted(counts.items(), key=lambda kv: kv[1], reverse=True),
        cases=cases,
        news_cases=news_cases,
        lessons=th_mod.theories_for(lesson_ids, by_tid, limit=10),
        subject_rows=subject_rows,
        issue_days=issue_days,
        issue_rows=issue_rows,
        top_stories=top_stories,
        theory_titles={t["id"]: t["title"] for t in settings.theories},
        quiz=quiz,
        companies=companies,
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M"),
        theory_book="../theories.md",
    )
    out = settings.reports_dir / "weekly" / f"{iso[0]}-W{iso[1]:02d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    write_reports_index(settings)
    return out


# --------------------------------------------------------------------- 목차
def write_reports_index(settings: Settings) -> Path:
    rd = settings.reports_dir
    dailies = sorted(rd.glob("daily/*/*.md"), reverse=True)
    weeklies = sorted(rd.glob("weekly/*.md"), reverse=True)
    companies = sorted(rd.glob("company/*.md"))
    titles = {t["id"]: t["title"] for t in settings.theories}
    entries = []
    for p in dailies:
        d = parse_ymd(p.stem)
        arch = archive_path(settings, d) if d else None
        cases: list[str] = []
        lesson = subject_lesson = ""
        if arch and arch.exists():
            try:
                data = json.loads(arch.read_text(encoding="utf-8"))
                cases = [f"{c['corp_name']} {c['label']}" for c in data.get("key_cases", [])]
                lesson = ", ".join(titles.get(t, t) for t in data.get("lessons") or [])
                subject_lesson = ", ".join(titles.get(t, t) for t in data.get("subject_lessons") or [])
                if subject_lesson and data.get("subject"):
                    subject_lesson = f"{data['subject']} {subject_lesson}"
            except (ValueError, KeyError):
                cases = []
        entries.append({"path": p.relative_to(rd).as_posix(), "date_ko": date_ko(d) if d else p.stem,
                        "cases": cases, "lesson": lesson, "subject_lesson": subject_lesson})
    has_theories = write_theory_book(settings) is not None
    md = render(
        "index.md.j2",
        title=settings.report_cfg.get("title", "매일 경영·경제 케이스 노트"),
        dailies=entries,
        weeklies=[{"path": p.relative_to(rd).as_posix(), "name": p.stem} for p in weeklies],
        companies=[{"path": p.relative_to(rd).as_posix(), "name": p.stem.split("_", 1)[-1]} for p in companies],
        has_scale=(rd / "scale.md").exists(),
        has_theories=has_theories,
        theory_count=len(th_mod.split_library(settings.theories)[0]),
        subject_count=len(th_mod.split_library(settings.theories)[1]),
    )
    out = rd / "README.md"
    rd.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out


def write_theory_book(settings: Settings) -> Path | None:
    """이론·제도 사전(reports/theories.md). 1부 경영·경제 이론, 2부 회계·세법·상법·재정학 카드를 분야별로 모은다."""
    if not settings.theories:
        return None
    by_tid = th_mod.theory_by_id(settings.theories)
    biz, subjects = th_mod.split_library(settings.theories)
    md = render(
        "theories.md.j2",
        parts=[{"title": "1부. 경영·경제 이론", "fields": th_mod.library_by_field(biz), "count": len(biz)},
               {"title": "2부. 회계·세법·상법·재정학", "fields": th_mod.library_by_field(subjects), "count": len(subjects)}],
        by_tid=by_tid,
        story_labels=th_mod.STORY_LABELS,
        count=len(settings.theories),
    )
    out = settings.reports_dir / "theories.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out
