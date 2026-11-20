"""재무제표 파싱과 회계사·세무사 관점의 지표 계산."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .dart import DartClient, DartError, DartFatalError
from .util import growth, parse_amount, pct, safe_div

log = logging.getLogger(__name__)

_NUMBERING = re.compile(r"^[\(\[]?[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVXivx0-9]{1,4}[\.\)\]]")


def norm_account(name: str) -> str:
    s = re.sub(r"\s+", "", str(name or ""))
    s = _NUMBERING.sub("", s)
    return s


# 주요계정 API(fnlttSinglAcnt / fnlttMultiAcnt) 계정명
MAJOR_NAMES: dict[str, list[str]] = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출", "수익"],
    "operating_income": ["영업이익", "영업이익(손실)", "영업손실"],
    "pretax_income": ["법인세차감전순이익", "법인세비용차감전순이익", "법인세차감전순이익(손실)", "법인세비용차감전순이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "연결당기순이익", "당기순손실"],
    "assets": ["자산총계"],
    "current_assets": ["유동자산"],
    "liabilities": ["부채총계"],
    "current_liabilities": ["유동부채"],
    "equity": ["자본총계"],
    "capital_stock": ["자본금"],
    "retained_earnings": ["이익잉여금", "이익잉여금(결손금)"],
}

# 전체 재무제표 API(fnlttSinglAcntAll): (재무제표 구분, 표준계정 ID, 계정명 후보)
FULL_MAP: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (("IS", "CIS"), ("ifrs-full_Revenue", "ifrs_Revenue"), ("매출액", "수익(매출액)", "영업수익", "매출")),
    "cost_of_sales": (("IS", "CIS"), ("ifrs-full_CostOfSales", "ifrs_CostOfSales"), ("매출원가",)),
    "gross_profit": (("IS", "CIS"), ("ifrs-full_GrossProfit", "ifrs_GrossProfit"), ("매출총이익", "매출총이익(손실)")),
    "sga": (("IS", "CIS"), ("dart_TotalSellingGeneralAdministrativeExpenses",), ("판매비와관리비", "판매비와일반관리비", "판매비및관리비")),
    "operating_income": (("IS", "CIS"), ("dart_OperatingIncomeLoss",), ("영업이익", "영업이익(손실)")),
    "finance_costs": (("IS", "CIS"), ("ifrs-full_FinanceCosts", "ifrs_FinanceCosts"), ("금융비용", "금융원가")),
    "pretax_income": (("IS", "CIS"), ("ifrs-full_ProfitLossBeforeTax", "ifrs_ProfitLossBeforeTax"), ("법인세비용차감전순이익", "법인세비용차감전순이익(손실)", "법인세차감전순이익")),
    "income_tax": (("IS", "CIS"), ("ifrs-full_IncomeTaxExpenseContinuingOperations", "ifrs_IncomeTaxExpenseContinuingOperations"), ("법인세비용", "법인세비용(수익)", "법인세수익(비용)")),
    "net_income": (("IS", "CIS"), ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"), ("당기순이익", "당기순이익(손실)", "연결당기순이익")),
    "net_income_parent": (("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs_ProfitLossAttributableToOwnersOfParent"), ("지배기업의소유주에게귀속되는당기순이익", "지배기업소유주지분")),
    "assets": (("BS",), ("ifrs-full_Assets", "ifrs_Assets"), ("자산총계",)),
    "current_assets": (("BS",), ("ifrs-full_CurrentAssets", "ifrs_CurrentAssets"), ("유동자산",)),
    "cash": (("BS",), ("ifrs-full_CashAndCashEquivalents", "ifrs_CashAndCashEquivalents"), ("현금및현금성자산",)),
    "receivables": (("BS",), ("ifrs-full_TradeAndOtherCurrentReceivables", "dart_ShortTermTradeReceivable", "ifrs-full_CurrentTradeReceivables"), ("매출채권", "매출채권및기타채권", "매출채권및기타유동채권")),
    "inventories": (("BS",), ("ifrs-full_Inventories", "ifrs_Inventories"), ("재고자산",)),
    "liabilities": (("BS",), ("ifrs-full_Liabilities", "ifrs_Liabilities"), ("부채총계",)),
    "current_liabilities": (("BS",), ("ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"), ("유동부채",)),
    "equity": (("BS",), ("ifrs-full_Equity", "ifrs_Equity"), ("자본총계",)),
    "ocf": (("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"), ("영업활동현금흐름", "영업활동으로인한현금흐름")),
    "icf": (("CF",), ("ifrs-full_CashFlowsFromUsedInInvestingActivities", "ifrs_CashFlowsFromUsedInInvestingActivities"), ("투자활동현금흐름", "투자활동으로인한현금흐름")),
    "fin_cf": (("CF",), ("ifrs-full_CashFlowsFromUsedInFinancingActivities", "ifrs_CashFlowsFromUsedInFinancingActivities"), ("재무활동현금흐름", "재무활동으로인한현금흐름")),
    "capex": (("CF",), ("ifrs-full_PurchaseOfPropertyPlantAndEquipment", "ifrs_PurchaseOfPropertyPlantAndEquipment"), ("유형자산의취득",)),
    "dividends_paid": (("CF",), ("ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "ifrs_DividendsPaidClassifiedAsFinancingActivities"), ("배당금지급", "배당금의지급")),
    "taxes_paid": (("CF",), ("ifrs-full_IncomeTaxesPaidRefundClassifiedAsOperatingActivities", "ifrs_IncomeTaxesPaidRefundClassifiedAsOperatingActivities"), ("법인세납부", "법인세의납부", "법인세납부액", "법인세의환급(납부)")),
    "depreciation": (("CF",), ("ifrs-full_AdjustmentsForDepreciationExpense", "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense"), ("감가상각비",)),
}

ABS_KEYS = {"capex", "dividends_paid", "taxes_paid", "depreciation", "cost_of_sales", "sga", "finance_costs"}

PERIODS = (("thstrm_amount", 0), ("frmtrm_amount", 1), ("bfefrmtrm_amount", 2))


def parse_major_accounts(rows: list[dict]) -> dict[str, dict[str, dict[int, dict]]]:
    """주요계정 → {corp_code: {fs_div: {연도: {항목: 금액}}}}. 단일회사 응답도 corp_code 없이 처리."""
    lookup = {norm_account(n): key for key, names in MAJOR_NAMES.items() for n in names}
    out: dict[str, dict[str, dict[int, dict]]] = {}
    for r in rows:
        key = lookup.get(norm_account(r.get("account_nm")))
        if not key:
            continue
        corp = str(r.get("corp_code") or "_")
        fs = str(r.get("fs_div") or "CFS")
        try:
            base_year = int(str(r.get("bsns_year")))
        except ValueError:
            continue
        for col, back in PERIODS:
            val = parse_amount(r.get(col))
            if val is None:
                continue
            slot = out.setdefault(corp, {}).setdefault(fs, {}).setdefault(base_year - back, {})
            slot.setdefault(key, val)
    return out


def pick_fs(by_fs: dict[str, dict[int, dict]]) -> tuple[str, dict[int, dict]]:
    for fs in ("CFS", "OFS"):
        if by_fs.get(fs):
            return fs, by_fs[fs]
    return "", {}


def snapshot(by_fs: dict[str, dict[int, dict]], year: int | None = None) -> dict | None:
    """연결 우선으로 한 해의 핵심 숫자와 전년 숫자를 묶는다."""
    fs, years = pick_fs(by_fs)
    if not years:
        return None
    y = year if year in years else max(years)
    cur = years.get(y, {})
    if not cur.get("assets") and not cur.get("revenue"):
        return None
    prev = years.get(y - 1, {})
    snap = {"year": y, "fs_div": fs, **cur}
    for k in ("revenue", "operating_income", "net_income", "assets", "equity", "liabilities"):
        if k in prev:
            snap[f"{k}_prev"] = prev[k]
    return snap


def fetch_snapshot(client: DartClient, corp_code: str, year: int) -> dict | None:
    """사업보고서 주요계정으로 스냅숏을 만든다. 그해 자료가 없으면 한 해 전으로."""
    for y in (year, year - 1):
        try:
            rows = client.single_accounts(corp_code, y)
        except DartFatalError:
            raise
        except DartError as exc:
            log.info("주요계정 조회 실패 %s %s: %s", corp_code, y, exc)
            continue
        if not rows:
            continue
        parsed = parse_major_accounts(rows)
        by_fs = next(iter(parsed.values()), {})
        snap = snapshot(by_fs, y)
        if snap:
            return snap
    return None


def parse_full_statements(rows: list[dict]) -> dict[int, dict]:
    """전체 재무제표 → {연도: {항목: 금액}}. 표준계정 ID를 먼저, 없으면 계정명으로 찾는다."""
    out: dict[int, dict] = {}
    if not rows:
        return out
    try:
        base_year = int(str(rows[0].get("bsns_year")))
    except ValueError:
        return out
    by_id: dict[tuple[str, str], dict] = {}
    by_name: dict[tuple[str, str], dict] = {}
    for r in rows:
        sj = str(r.get("sj_div") or "")
        aid = str(r.get("account_id") or "")
        name = norm_account(r.get("account_nm"))
        by_id.setdefault((sj, aid), r)
        by_name.setdefault((sj, name), r)
    for key, (sjs, ids, names) in FULL_MAP.items():
        row = None
        for sj in sjs:
            row = next((by_id[(sj, i)] for i in ids if (sj, i) in by_id), None)
            if row:
                break
        if row is None:
            for sj in sjs:
                row = next((by_name[(sj, norm_account(n))] for n in names if (sj, norm_account(n)) in by_name), None)
                if row:
                    break
        if row is None:
            continue
        for col, back in PERIODS:
            val = parse_amount(row.get(col))
            if val is None:
                continue
            if key in ABS_KEYS:
                val = abs(val)
            out.setdefault(base_year - back, {})[key] = val
    return out


def _avg(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2


def compute_ratios(cur: dict, prev: dict | None = None) -> dict:
    prev = prev or {}
    rev = cur.get("revenue")
    op = cur.get("operating_income")
    ni = cur.get("net_income")
    assets = cur.get("assets")
    equity = cur.get("equity")
    avg_assets = _avg(assets, prev.get("assets"))
    avg_equity = _avg(equity, prev.get("equity"))
    cogs = cur.get("cost_of_sales")
    gp = cur.get("gross_profit")
    if gp is None and rev is not None and cogs is not None:
        gp = rev - cogs
    r = {
        "op_margin": pct(op, rev),
        "net_margin": pct(ni, rev),
        "gross_margin": pct(gp, rev),
        "cogs_ratio": pct(cogs, rev),
        "sga_ratio": pct(cur.get("sga"), rev),
        "roe": pct(ni, avg_equity) if avg_equity and avg_equity > 0 else None,
        "roa": pct(ni, avg_assets),
        "debt_ratio": pct(cur.get("liabilities"), equity) if equity and equity > 0 else None,
        "equity_ratio": pct(equity, assets),
        "current_ratio": pct(cur.get("current_assets"), cur.get("current_liabilities")),
        "asset_turnover": safe_div(rev, avg_assets),
        "leverage": safe_div(avg_assets, avg_equity) if avg_equity and avg_equity > 0 else None,
        "interest_coverage": safe_div(op, cur.get("finance_costs")),
        "rev_growth": growth(rev, prev.get("revenue")),
        "op_growth": growth(op, prev.get("operating_income")),
        "ni_growth": growth(ni, prev.get("net_income")),
        "inventory_days": (safe_div(cur.get("inventories"), cogs) or 0) * 365 if cogs and cur.get("inventories") else None,
        "receivable_days": (safe_div(cur.get("receivables"), rev) or 0) * 365 if rev and cur.get("receivables") else None,
        "ocf_to_ni": safe_div(cur.get("ocf"), ni) if ni and ni > 0 else None,
        "accrual_ratio": pct((ni - cur["ocf"]) if ni is not None and cur.get("ocf") is not None else None, avg_assets),
        "fcf": (cur["ocf"] - cur.get("capex", 0)) if cur.get("ocf") is not None else None,
        "etr": pct(cur.get("income_tax"), cur.get("pretax_income")) if (cur.get("pretax_income") or 0) > 0 else None,
    }
    if op is not None and cur.get("depreciation") is not None:
        r["ebitda"] = op + cur["depreciation"]
    return r


LIFECYCLE = {
    (False, False, True): ("도입기", "영업으로 아직 현금을 못 벌고, 투자 자금을 외부 조달로 메우는 단계"),
    (True, False, True): ("성장기", "영업으로 돈을 벌지만 투자가 더 커서 외부 조달도 함께 하는 단계"),
    (True, False, False): ("성숙기", "영업현금으로 투자도 하고 차입 상환·배당까지 하는 단계"),
    (False, False, False): ("정체기", "영업현금이 적자인데 투자와 상환이 함께 나가는 단계(보유 현금 소진)"),
    (True, True, True): ("정체기", "세 흐름이 모두 들어오는 드문 형태(자산 매각과 조달을 함께 하는 구조조정 가능성)"),
    (True, True, False): ("정체기", "영업현금과 자산 매각 자금으로 빚을 갚거나 주주에게 돌려주는 단계"),
    (False, True, True): ("쇠퇴기", "영업현금 적자를 자산 매각과 외부 조달로 메우는 단계"),
    (False, True, False): ("쇠퇴기", "영업현금 적자에 자산을 팔아 빚을 갚는 단계"),
}


def cf_lifecycle(ocf: float | None, icf: float | None, fin: float | None) -> tuple[str, str] | None:
    """현금흐름 부호로 본 기업 생애주기(Dickinson, 2011)."""
    if ocf is None or icf is None or fin is None:
        return None
    return LIFECYCLE.get((ocf >= 0, icf >= 0, fin >= 0))


def corporate_tax(base: float, year: int, brackets_by_year: list[dict]) -> float:
    """누진세율로 계산한 법인세(지방소득세 제외)."""
    table = None
    for entry in sorted(brackets_by_year, key=lambda e: e["from_year"]):
        if year >= entry["from_year"]:
            table = entry["brackets"]
    if not table or base <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in table:
        top = float("inf") if upper is None else float(upper)
        if base > lower:
            tax += (min(base, top) - lower) * rate
        lower = top
        if base <= top:
            break
    return tax


def top_rate(year: int, brackets_by_year: list[dict]) -> float:
    table = None
    for entry in sorted(brackets_by_year, key=lambda e: e["from_year"]):
        if year >= entry["from_year"]:
            table = entry["brackets"]
    return float(table[-1][1]) if table else 0.0


def tax_view(cur: dict, year: int, benchmarks: dict) -> dict | None:
    """유효세율을 법정세율과 비교하고 차이가 나는 이유 후보를 정리한다(세무사 관점)."""
    pretax = cur.get("pretax_income")
    tax = cur.get("income_tax")
    if pretax is None or tax is None:
        return None
    local = float(benchmarks.get("local_income_tax_rate", 0.1))
    brackets = benchmarks.get("corporate_tax", [])
    top = top_rate(year, brackets) * (1 + local) * 100
    view = {"pretax": pretax, "tax": tax, "statutory_top": top, "notes": []}
    if pretax <= 0:
        view["etr"] = None
        view["notes"].append("세전손실이라 유효세율로 해석하기 어렵다. 결손에 대한 이연법인세자산을 인식했는지(미래 과세소득 실현 가능성 판단)를 주석에서 확인.")
        return view
    etr = tax / pretax * 100
    expected = corporate_tax(pretax, year, brackets) * (1 + local) / pretax * 100
    view.update({"etr": etr, "expected": expected})
    gap = etr - expected
    if gap <= -5:
        view["notes"].append(
            "법정세율보다 낮다. 후보: 연구개발·통합투자 세액공제, 수입배당금 익금불산입, 저세율 국가 자회사 이익, 이월결손금 활용, 이연법인세자산 추가 인식."
        )
    elif gap >= 5:
        view["notes"].append(
            "법정세율보다 높다. 후보: 손금불산입 항목(기업업무추진비 한도 초과, 벌과금 등), 결손 자회사의 이연법인세자산 미인식, 고세율 국가 이익, 과거 연도 추가 납부."
        )
    else:
        view["notes"].append("법정세율과 비슷한 수준이다. 세무조정 효과가 크지 않거나 서로 상쇄된 경우.")
    paid = cur.get("taxes_paid")
    if paid:
        view["paid"] = paid
        ratio = paid / tax if tax else None
        if ratio and ratio > 1.3:
            view["notes"].append("실제 납부액이 법인세비용보다 꽤 많다. 전년도 이익에 대한 납부 시차나 이연법인세자산 증가 가능성.")
        elif ratio is not None and ratio < 0.7:
            view["notes"].append("실제 납부액이 법인세비용보다 꽤 적다. 이연법인세부채 증가, 세액공제·감면, 납부 시차 가능성.")
    return view


def quality_notes(r: dict, cur: dict) -> list[str]:
    """이익의 질과 재무 안정성을 짧게 짚는다."""
    notes = []
    o2n = r.get("ocf_to_ni")
    if o2n is not None:
        if o2n >= 1.2:
            notes.append(f"영업현금흐름이 순이익의 {o2n:.1f}배: 이익보다 현금이 잘 들어온다(감가상각 등 비현금비용이 큰 구조일 수 있다).")
        elif o2n < 0.7:
            notes.append(f"영업현금흐름이 순이익의 {o2n:.1f}배에 그친다: 매출채권·재고가 늘었거나 비현금 이익이 섞였는지 확인.")
    ic = r.get("interest_coverage")
    if ic is not None and cur.get("operating_income") is not None:
        if ic < 1:
            notes.append(f"영업이익이 금융비용의 {ic:.1f}배: 영업으로 이자도 감당이 안 되는 수준(금융비용에는 이자 외 항목도 섞여 있으니 주석 확인).")
        elif ic < 3:
            notes.append(f"영업이익이 금융비용의 {ic:.1f}배: 금리 변화에 민감한 편.")
    dr = r.get("debt_ratio")
    if dr is not None and dr >= 200:
        notes.append(f"부채비율 {dr:.0f}%: 업종 특성(금융·건설·항공 등)인지 재무 위험인지 구분해서 볼 것.")
    return notes


def parse_employees(rows: list[dict]) -> dict | None:
    """직원 현황 → 총원, 1인 평균 급여, 평균 근속. 합계 행과 세부 행이 섞여 있어 이중 집계를 피한다."""
    if not rows:
        return None
    totals_kw = {"합계", "총계", "계", "전체", "총합계"}

    def is_total(r: dict) -> bool:
        a = re.sub(r"\s+", "", str(r.get("fo_bbm") or ""))
        b = re.sub(r"\s+", "", str(r.get("sexdstn") or ""))
        return a in totals_kw or b in totals_kw

    detail = [r for r in rows if not is_total(r)]
    use = detail or rows
    count = sum(parse_amount(r.get("sm")) or 0 for r in use)
    salary_total = sum(parse_amount(r.get("fyer_salary_totamt")) or 0 for r in use)
    if count <= 0:
        return None
    avg_salary = salary_total / count if salary_total else None
    if avg_salary is None:
        weighted = [(parse_amount(r.get("jan_salary_am")), parse_amount(r.get("sm"))) for r in use]
        weighted = [(s, c) for s, c in weighted if s and c]
        if weighted:
            avg_salary = sum(s * c for s, c in weighted) / sum(c for _, c in weighted)
    tenure = [(parse_amount(r.get("avrg_cnwk_sdytrn")), parse_amount(r.get("sm"))) for r in use]
    tenure = [(t, c) for t, c in tenure if t and c]
    avg_tenure = sum(t * c for t, c in tenure) / sum(c for _, c in tenure) if tenure else None
    return {"count": count, "avg_salary": avg_salary, "salary_total": salary_total or None, "avg_tenure": avg_tenure}


@dataclass
class CompanyFinancials:
    """오늘의 기업·기업 분석 리포트에 쓰는 묶음."""

    corp_code: str
    corp_name: str
    year: int
    fs_div: str = ""
    stock_code: str = ""
    years: dict[int, dict] = field(default_factory=dict)  # 주요계정 여러 해
    full: dict[int, dict] = field(default_factory=dict)  # 전체 재무제표(연결 우선)
    separate: dict[int, dict] = field(default_factory=dict)  # 별도 주요계정(직원 1인당 지표용)
    employees: dict | None = None
    company: dict = field(default_factory=dict)

    @property
    def cur(self) -> dict:
        merged = dict(self.years.get(self.year, {}))
        merged.update({k: v for k, v in self.full.get(self.year, {}).items() if v is not None})
        return merged

    @property
    def prev(self) -> dict:
        merged = dict(self.years.get(self.year - 1, {}))
        merged.update({k: v for k, v in self.full.get(self.year - 1, {}).items() if v is not None})
        return merged


def load_company_financials(
    client: DartClient, corp_code: str, corp_name: str, year: int, history_years: int = 3, with_full: bool = True
) -> CompanyFinancials | None:
    """주요계정(여러 해) + 전체 재무제표(최근 연도) + 직원 현황을 모은다."""
    years_cfs: dict[int, dict] = {}
    years_ofs: dict[int, dict] = {}
    fs_used = ""
    actual_year = None
    base = year
    calls = max(1, (history_years + 2) // 3)
    for i in range(calls):
        y = base - 3 * i
        try:
            rows = client.single_accounts(corp_code, y)
        except DartFatalError:
            raise
        except DartError as exc:
            log.info("주요계정 실패 %s %s: %s", corp_name, y, exc)
            rows = []
        if not rows and i == 0:
            # 최신 사업보고서가 아직 없으면 한 해 당겨서 다시
            base -= 1
            y = base
            try:
                rows = client.single_accounts(corp_code, y)
            except DartFatalError:
                raise
            except DartError:
                rows = []
        parsed = parse_major_accounts(rows)
        by_fs = next(iter(parsed.values()), {})
        for yy, vals in by_fs.get("CFS", {}).items():
            years_cfs.setdefault(yy, vals)
        for yy, vals in by_fs.get("OFS", {}).items():
            years_ofs.setdefault(yy, vals)
        if actual_year is None and (by_fs.get("CFS") or by_fs.get("OFS")):
            actual_year = y
    if actual_year is None:
        return None
    if years_cfs:
        fs_used, years = "CFS", years_cfs
    else:
        fs_used, years = "OFS", years_ofs
    cf = CompanyFinancials(corp_code=corp_code, corp_name=corp_name, year=actual_year, fs_div=fs_used, years=years, separate=years_ofs)
    if with_full:
        for fs in ("CFS", "OFS"):
            try:
                rows = client.full_statements(corp_code, actual_year, fs_div=fs)
            except DartFatalError:
                raise
            except DartError as exc:
                log.info("전체 재무제표 실패 %s %s: %s", corp_name, fs, exc)
                rows = []
            if rows:
                cf.full = parse_full_statements(rows)
                if fs != fs_used and fs == "OFS":
                    log.info("%s: 연결 전체 재무제표가 없어 별도 기준 사용", corp_name)
                break
    try:
        cf.employees = parse_employees(client.employees(corp_code, actual_year))
    except DartFatalError:
        raise
    except DartError as exc:
        log.info("직원 현황 실패 %s: %s", corp_name, exc)
    return cf
