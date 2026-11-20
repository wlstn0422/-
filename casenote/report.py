"""데이터를 모아 리포트(마크다운)와 기록(JSON)을 만든다."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import ai as ai_mod
from .dart import CorpIndex, DartClient, DartError, DartFatalError, viewer_url
from .events import GROUP_LABELS, Event, attach_details, build_events, context_notes, pick_key_cases, related_for, score_event
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
    md_cell,
    md_link_text,
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


def jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(krw=fmt_krw, pct=fmt_pct, cell=md_cell, times=fmt_times, intf=fmt_int, linktext=md_link_text)
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
    industry = industry_of(scale, cf.corp_code)
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


def pick_company_of_day(settings: Settings, index: CorpIndex, day: date) -> tuple[str, str] | None:
    pool = [c for c in company_list(settings) if not c["financial"]]
    if not pool:
        return None
    for i in range(len(pool)):
        c = pool[(day.toordinal() + i) % len(pool)]
        corp = index.by_stock.get(c["code"])
        if corp:
            return corp.corp_code, c["name"]
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
    categories = settings.news_sources.get("categories", [])
    if use_news:
        fetcher = news_fetcher or (lambda: collect_news(
            settings.news_sources,
            lookback_hours=float(settings.config["news"].get("lookback_hours", 30)),
            timeout=float(settings.config["news"].get("timeout_sec", 15)),
        ))
        news_items, news_errors = fetcher()
        buckets = categorize(news_items, categories, int(rc.get("news_per_category", 5)))
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
    th = settings.benchmarks["thresholds"]
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
            "questions": (card.get("questions") or [])[:2],
        })

    # AI 해설
    ai_notes = {}
    if use_ai and key_cases:
        ai_notes = ai_mod.commentary(key_cases, settings)

    # 공시 목록(유형 묶음별)
    groups = []
    per_type = int(rc.get("filings_per_type", 12))
    for gkey, glabel in GROUP_LABELS.items():
        evs = [e for e in events if e.rule.group == gkey]
        if not evs:
            continue
        evs.sort(key=lambda e: (e.score, e.rcept_no), reverse=True)
        groups.append({"label": glabel, "count": len(evs), "events": evs[:per_type], "more": max(0, len(evs) - per_type)})

    # 카드와 퀴즈
    news_cards = []
    for cat in categories:
        if buckets.get(cat["key"]):
            news_cards.extend(cat.get("cards", [])[:1])
    case_cards = [e.rule.card for e in key_cases if e.rule.card]
    cards = select_cards(settings.cards, case_cards, news_cards, day, limit=3)
    company_for_quiz = (company_ctx["name"], company_ctx["cur"], company_ctx["year"]) if company_ctx else None
    quiz = build_quiz(day, cards, settings.benchmarks, company_for_quiz, scale.get("rows", []))

    news_sections = []
    for cat in categories:
        items = buckets.get(cat["key"]) or []
        if items:
            news_sections.append({"label": cat["label"], "entries": items})

    ctx = {
        "title": rc.get("title", "매일 기업 케이스 노트"),
        "day": day,
        "date_ko": date_ko(day),
        "window": (start, end),
        "generated_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        "warnings": warnings,
        "dart_status": dart_status,
        "events_total": len(events),
        "case_blocks": case_blocks,
        "ai_notes": ai_notes,
        "groups": groups,
        "company": company_ctx,
        "news_sections": news_sections,
        "news_total": len(news_items),
        "cards": cards,
        "quiz": quiz,
        "viewer_url": viewer_url,
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
            "cards": [c["id"] for c in cards],
            "quiz": quiz,
            "company": company_ctx["name"] if company_ctx else None,
        }
        archive_path(settings, day).write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
        write_reports_index(settings)
    return out


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
    salary = sorted([x for x in rows if x.get("avg_salary")], key=lambda x: x["avg_salary"], reverse=True)[:15]
    md = render(
        "scale.md.j2",
        year=scale.get("year", year),
        industries=industries,
        top=top,
        salary=salary,
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
    for d in days:
        for k, v in (d.get("event_counts") or {}).items():
            counts[k] = counts.get(k, 0) + int(v)
        for c in d.get("key_cases") or []:
            cases.append({**c, "day": d["date"]})
        quiz.extend(d.get("quiz") or [])
        if d.get("company"):
            companies.append({"day": d["date"], "name": d["company"]})
    iso = day.isocalendar()
    md = render(
        "weekly.md.j2",
        day=day,
        start=start,
        week=f"{iso[0]}년 {iso[1]}주차",
        counts=sorted(counts.items(), key=lambda kv: kv[1], reverse=True),
        cases=cases,
        quiz=quiz[:8],
        companies=companies,
        cards=[card_by_id(settings.cards).get(cid) for d in days for cid in (d.get("cards") or []) if card_by_id(settings.cards).get(cid)],
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M"),
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
    entries = []
    for p in dailies:
        d = parse_ymd(p.stem)
        arch = archive_path(settings, d) if d else None
        cases = []
        if arch and arch.exists():
            try:
                cases = [f"{c['corp_name']} {c['label']}" for c in json.loads(arch.read_text(encoding="utf-8")).get("key_cases", [])]
            except (ValueError, KeyError):
                cases = []
        entries.append({"path": p.relative_to(rd).as_posix(), "date_ko": date_ko(d) if d else p.stem, "cases": cases})
    md = render(
        "index.md.j2",
        title=settings.report_cfg.get("title", "매일 기업 케이스 노트"),
        dailies=entries,
        weeklies=[{"path": p.relative_to(rd).as_posix(), "name": p.stem} for p in weeklies],
        companies=[{"path": p.relative_to(rd).as_posix(), "name": p.stem.split("_", 1)[-1]} for p in companies],
        has_scale=(rd / "scale.md").exists(),
    )
    out = rd / "README.md"
    rd.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out
