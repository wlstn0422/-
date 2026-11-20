"""기업 규모 진단과 '돈 감각' 환산."""

from __future__ import annotations

from .util import fmt_krw, fmt_pct, josa, pct, safe_div


def size_class(revenue: float | None, assets: float | None, th: dict) -> str:
    """한 줄 규모 판정. 업종별 기준이 달라 경계 구간은 범위로 말한다."""
    if assets is not None:
        if assets >= th["cross_holding_group_assets"]:
            return "회사 하나만으로 상호출자제한기업집단 기준(자산 약 12조원대)을 넘는 초대형"
        if assets >= th["disclosure_group_assets"]:
            return "회사 하나만으로 공시대상기업집단 기준(자산 5조원)을 넘는 대형"
        if assets >= th["large_listed_assets"]:
            return "자산 2조원 이상 대규모 상장회사급"
        if assets >= th["sme_asset_cap"]:
            return "중견기업 이상(자산 5,000억원 이상이면 중소기업이 아님)"
    if revenue is not None:
        if revenue > th["sme_revenue_high"]:
            return "중견기업 이상(매출이 모든 업종의 중소기업 상한 1,500억원 초과)"
        if revenue > th["sme_revenue_low"]:
            return "업종에 따라 중소·중견 경계(중소기업 매출 상한 400억~1,500억원 구간)"
        return "중소기업 규모(독립성 기준 등은 별도 확인)"
    return "규모 판단 자료 부족"


def size_checklist(revenue: float | None, assets: float | None, listed: bool, th: dict) -> list[tuple[str, str, str]]:
    """법·제도 기준별 해당 여부 표. (기준, 해당 여부, 의미)"""
    rows = []

    def yes(flag: bool | None) -> str:
        if flag is None:
            return "자료 없음"
        return "해당" if flag else "아님"

    big = None if assets is None and revenue is None else (
        (assets or 0) >= th["external_audit_single"] or (revenue or 0) >= th["external_audit_single"]
    )
    rows.append(("외부감사 대상", "해당" if listed else yes(big), "상장사이거나 자산 또는 매출 500억원 이상"))
    not_sme = None
    if assets is not None and assets >= th["sme_asset_cap"]:
        not_sme = True
    elif revenue is not None:
        not_sme = True if revenue > th["sme_revenue_high"] else (False if revenue <= th["sme_revenue_low"] else None)
    rows.append(("중소기업 범위 초과", "업종별 확인" if not_sme is None else yes(not_sme), "자산 5,000억원 이상이거나 업종별 매출 상한(400억~1,500억원) 초과"))
    rows.append(("대규모 상장회사(자산 2조원)", yes(None if assets is None else (listed and assets >= th["large_listed_assets"])), "감사위원회·사외이사 과반·집중투표제 의무, 실적변동 공시 15% 기준"))
    rows.append(("자산 5조원(공시대상기업집단 기준선)", yes(None if assets is None else assets >= th["disclosure_group_assets"]), "기업집단은 그룹 전체 합산으로 판단한다"))
    return rows


def ladder_position(amount: float | None, ladder: list[dict]) -> tuple[dict | None, dict | None]:
    """사다리에서 바로 아래 칸과 다음 칸."""
    if amount is None:
        return None, None
    below = None
    above = None
    for rung in sorted(ladder, key=lambda r: r["amount"]):
        if amount >= rung["amount"]:
            below = rung
        elif above is None:
            above = rung
    return below, above


def money_sense(cur: dict, employees: dict | None, separate: dict | None, anchors: list[dict]) -> list[tuple[str, str]]:
    """큰 숫자를 체감 단위로 바꾼다."""
    out: list[tuple[str, str]] = []
    rev = cur.get("revenue")
    op = cur.get("operating_income")
    ni = cur.get("net_income")
    if rev:
        out.append(("하루 평균 매출", fmt_krw(rev / 365)))
        out.append(("한 시간 평균 매출(24시간 기준)", fmt_krw(rev / 365 / 24)))
    if op and op > 0 and rev:
        out.append(("영업이익 1억원을 남기려면 필요한 매출", fmt_krw(1e8 / (op / rev))))
    if cur.get("sga"):
        out.append(("판매관리비 하루치", fmt_krw(cur["sga"] / 365)))
    if employees and employees.get("count"):
        sep_rev = (separate or {}).get("revenue")
        if sep_rev:
            out.append(("직원 1인당 매출(별도 기준)", fmt_krw(sep_rev / employees["count"])))
        if employees.get("avg_salary"):
            out.append(("직원 1인 평균 급여(별도 기준)", fmt_krw(employees["avg_salary"])))
        if employees.get("salary_total") and sep_rev:
            out.append(("급여 총액 ÷ 매출(별도)", fmt_pct(pct(employees["salary_total"], sep_rev))))
    budget = next((a for a in anchors if a.get("key") == "national_budget_2026"), None)
    if budget and rev:
        out.append((f"{budget['label']} 대비 매출", fmt_pct(pct(rev, budget["amount"]), 2)))
    wage = next((a for a in anchors if a.get("key") == "min_wage_month_2026"), None)
    if wage and ni and ni > 0:
        years = ni / (wage["amount"] * 12)
        out.append(("순이익을 최저임금 연봉으로 나누면", f"약 {years:,.0f}명의 1년치 최저임금"))
    return out


def budget_drills(cur: dict, name: str) -> list[dict]:
    """예산 감각 연습문제(답 포함). 회사 실제 숫자로 만든다."""
    drills = []
    rev = cur.get("revenue")
    op = cur.get("operating_income")
    sga = cur.get("sga")
    if rev:
        mk = rev * 0.01
        drills.append({
            "q": f"{name}{josa(name, '이', '가')} 매출의 1%를 마케팅 예산으로 잡는다면 연간, 월간 얼마일까?",
            "a": f"연 {fmt_krw(mk)}, 월 {fmt_krw(mk / 12)}. 실제 광고선전비는 사업보고서 판매관리비 주석에서 확인할 수 있다.",
        })
    if sga and op and op > 0:
        gain = sga * 0.05
        drills.append({
            "q": f"판매관리비를 5% 줄이면 영업이익은 몇 % 늘어날까?",
            "a": f"판관비 5% = {fmt_krw(gain)}. 영업이익 {fmt_krw(op)} 대비 {gain / op * 100:.1f}% 증가. 비용 절감 효과가 이익에서는 몇 배로 커지는지 보는 연습이다.",
        })
    if rev and op and op > 0:
        margin = op / rev
        drills.append({
            "q": f"새 사업에 영업이익 기준 100억원을 더 벌려면 지금 이익률({margin * 100:.1f}%)로 매출이 얼마나 늘어야 할까?",
            "a": f"100억 ÷ {margin * 100:.1f}% = 매출 {fmt_krw(1e10 / margin)}. 이익률이 낮을수록 같은 이익에 훨씬 큰 매출이 필요하다.",
        })
    return drills


def leader_compare(company: dict, industry_rows: list[dict]) -> list[str]:
    """업종 1위(매출 기준)와 비교한 문장."""
    rows = [r for r in industry_rows if r.get("revenue")]
    if not rows or not company.get("revenue"):
        return []
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    leader = rows[0]
    rank = next((i + 1 for i, r in enumerate(rows) if r.get("corp_code") == company.get("corp_code")), None)
    out = []
    if leader.get("corp_code") == company.get("corp_code"):
        out.append(f"이 목록 기준 업종 매출 1위. 2위({rows[1]['name']}) 대비 {company['revenue'] / rows[1]['revenue']:.1f}배." if len(rows) > 1 else "이 목록 기준 업종 매출 1위.")
    else:
        ratio = safe_div(company["revenue"], leader["revenue"])
        out.append(
            f"업종 1위 {leader['name']}(매출 {fmt_krw(leader['revenue'])})의 {ratio * 100:.1f}% 규모"
            + (f", 목록 내 {rank}위." if rank else ".")
        )
    lm = pct(leader.get("operating_income"), leader.get("revenue"))
    cm = pct(company.get("operating_income"), company.get("revenue"))
    if lm is not None and cm is not None and leader.get("corp_code") != company.get("corp_code"):
        out.append(f"영업이익률은 1위 {lm:.1f}%, 이 회사 {cm:.1f}%.")
    return out
