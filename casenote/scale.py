"""업종별 규모 지도: 대표 기업들의 매출·이익·자산·직원을 DART에서 모아 비교한다."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .dart import CorpIndex, DartClient, DartError, DartFatalError
from .financials import parse_employees, parse_major_accounts, snapshot
from .settings import Settings
from .util import pct

log = logging.getLogger(__name__)

SCALE_FILE = "scale.json"


def scale_path(settings: Settings) -> Path:
    return settings.generated_dir / SCALE_FILE


def load_scale(settings: Settings) -> dict:
    p = scale_path(settings)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def needs_refresh(settings: Settings, year: int) -> bool:
    data = load_scale(settings)
    if not data or data.get("year") != year:
        return True
    age_days = (time.time() - float(data.get("built_at", 0))) / 86400
    return age_days >= float(settings.config["dart"].get("scale_refresh_days", 30))


def company_list(settings: Settings) -> list[dict]:
    out = []
    for ind in settings.industries:
        for c in ind.get("companies", []):
            out.append({"industry": ind["name"], "name": c["name"], "code": str(c["code"]).zfill(6), "financial": bool(ind.get("financial"))})
    return out


def build_scale(client: DartClient, settings: Settings, corp_index: CorpIndex, year: int) -> dict:
    companies = company_list(settings)
    for c in companies:
        corp = corp_index.by_stock.get(c["code"])
        c["corp_code"] = corp.corp_code if corp else None
        if corp is None:
            log.warning("종목코드 %s(%s)를 DART 고유번호에서 찾지 못함", c["code"], c["name"])
    codes = [c["corp_code"] for c in companies if c["corp_code"]]
    parsed: dict = {}
    for y in (year, year - 1):
        missing = [code for code in codes if code not in parsed]
        if not missing:
            break
        try:
            rows = client.multi_accounts(missing, y)
        except DartFatalError:
            raise
        except DartError as exc:
            log.warning("다중회사 주요계정 실패(%s): %s", y, exc)
            continue
        for corp_code, by_fs in parse_major_accounts(rows).items():
            if corp_code not in parsed:
                snap = snapshot(by_fs, y)
                if snap:
                    parsed[corp_code] = snap
    include_emp = bool(settings.config["dart"].get("include_employees", True))
    rows_out = []
    for c in companies:
        snap = parsed.get(c["corp_code"] or "")
        row = {**c, **(snap or {})}
        if snap:
            row["op_margin"] = pct(snap.get("operating_income"), snap.get("revenue"))
            row["debt_ratio"] = pct(snap.get("liabilities"), snap.get("equity")) if (snap.get("equity") or 0) > 0 else None
        if include_emp and c["corp_code"] and snap:
            try:
                emp = parse_employees(client.employees(c["corp_code"], snap["year"]))
            except DartFatalError:
                raise
            except DartError as exc:
                log.info("직원 현황 실패 %s: %s", c["name"], exc)
                emp = None
            if emp:
                row["employees"] = emp["count"]
                row["avg_salary"] = emp["avg_salary"]
        rows_out.append(row)
    data = {"year": year, "built_at": time.time(), "rows": rows_out}
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    scale_path(settings).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def industry_rows(scale: dict, industry: str) -> list[dict]:
    return [r for r in scale.get("rows", []) if r.get("industry") == industry]


def industry_of(scale: dict, corp_code: str | None, stock_code: str | None = None) -> str | None:
    for r in scale.get("rows", []):
        if (corp_code and r.get("corp_code") == corp_code) or (stock_code and r.get("code") == stock_code):
            return r.get("industry")
    return None
