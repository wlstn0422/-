import pytest

from casenote.financials import (
    cf_lifecycle,
    compute_ratios,
    corporate_tax,
    parse_employees,
    parse_full_statements,
    parse_major_accounts,
    snapshot,
    tax_view,
)
from casenote.settings import load_yaml

from fake_data import EMPLOYEES, full_rows, major_rows


def test_parse_major_accounts_three_years():
    parsed = parse_major_accounts(major_rows(1.0))
    by_fs = parsed["_"]
    assert set(by_fs) == {"CFS", "OFS"}
    assert set(by_fs["CFS"]) == {2025, 2024, 2023}
    snap = snapshot(by_fs, 2025)
    assert snap["fs_div"] == "CFS"
    assert snap["revenue"] == pytest.approx(1200e8)
    assert snap["pretax_income"] == pytest.approx(140e8)  # '법인세차감전 순이익'(띄어쓰기) 인식
    assert snap["revenue_prev"] == pytest.approx(1000e8)


def test_multi_accounts_grouped_by_corp():
    rows = major_rows(1.0, corp_code="A") + major_rows(2.0, corp_code="B")
    parsed = parse_major_accounts(rows)
    assert parsed["B"]["CFS"][2025]["assets"] == pytest.approx(2000e8)


def test_full_statements_and_ratios():
    years = parse_full_statements(full_rows(1.0))
    cur, prev = years[2025], years[2024]
    assert cur["capex"] == pytest.approx(100e8)  # 유출은 양수로
    assert cur["taxes_paid"] == pytest.approx(25e8)
    r = compute_ratios(cur, prev)
    assert r["op_margin"] == pytest.approx(12.5)
    assert r["gross_margin"] == pytest.approx(400 / 1200 * 100)
    assert r["fcf"] == pytest.approx(80e8)
    assert r["etr"] == pytest.approx(30 / 140 * 100)
    assert r["ebitda"] == pytest.approx(210e8)
    assert cf_lifecycle(cur["ocf"], cur["icf"], cur["fin_cf"])[0] == "성숙기"


def test_lifecycle_patterns():
    assert cf_lifecycle(-1, -1, 1)[0] == "도입기"
    assert cf_lifecycle(1, -1, 1)[0] == "성장기"
    assert cf_lifecycle(-1, 1, -1)[0] == "쇠퇴기"
    assert cf_lifecycle(None, 1, 1) is None


def test_corporate_tax_brackets():
    from pathlib import Path
    bm = load_yaml(Path(__file__).resolve().parent.parent / "data" / "benchmarks.yaml")
    br = bm["corporate_tax"]
    # 2026년 과세표준 1,000억: 2억×10% + 198억×20% + 800억×22%
    assert corporate_tax(1000e8, 2026, br) == pytest.approx(2e8 * 0.10 + 198e8 * 0.20 + 800e8 * 0.22)
    # 2025년(9/19/21/24) 과세표준 5,000억
    expected = 2e8 * 0.09 + 198e8 * 0.19 + 2800e8 * 0.21 + 2000e8 * 0.24
    assert corporate_tax(5000e8, 2025, br) == pytest.approx(expected)
    view = tax_view({"pretax_income": 140e8, "income_tax": 10e8, "taxes_paid": 25e8}, 2025, bm)
    assert view["etr"] == pytest.approx(10 / 140 * 100)
    assert any("낮다" in n for n in view["notes"])
    assert any("납부액" in n for n in view["notes"])


def test_parse_employees_avoids_double_count():
    emp = parse_employees(EMPLOYEES)
    assert emp["count"] == 8000
    assert emp["avg_salary"] == pytest.approx(924e9 / 8000)
    assert emp["avg_tenure"] == pytest.approx((12.5 * 6200 + 9.5 * 1800) / 8000)


def test_parse_employees_hidden_subtotals():
    def row(div, sex, sm, pay):
        return {"fo_bbm": div, "sexdstn": sex, "sm": f"{sm:,}", "fyer_salary_totamt": f"{pay:,}"}

    # 부문별 소계와 전사 합계가 이름 없이(또는 낯선 이름으로) 섞여 있어도 한 번만 센다
    rows = [
        row("DX", "남", 40_000, 4_800_000_000_000), row("DX", "여", 20_000, 2_000_000_000_000),
        row("DX", "소 계", 60_000, 6_800_000_000_000),
        row("DS", "남", 50_000, 7_500_000_000_000), row("DS", "여", 15_000, 1_800_000_000_000),
        row("DS", "부문계", 65_000, 9_300_000_000_000),
        row("전사", "총원", 125_000, 16_100_000_000_000),
    ]
    emp = parse_employees(rows)
    assert emp["count"] == 125_000
    assert round(emp["avg_salary"] / 1e4) == round(16_100_000_000_000 / 125_000 / 1e4)
    # 남·여 두 줄뿐이면 그대로 더한다
    assert parse_employees([row("전사", "남", 100, 1), row("전사", "여", 50, 1)])["count"] == 150


def test_parse_employees_pay_only_on_total_rows():
    # 삼성전자처럼 부문×성별 행에는 인원만, '성별합계' 행에만 급여가 적힌 표
    def row(div, sex, sm, pay=None, each=None, tenure=None):
        r = {"fo_bbm": div, "sexdstn": sex, "sm": f"{sm:,}", "fyer_salary_totamt": "-", "jan_salary_am": "-",
             "avrg_cnwk_sdytrn": "-"}
        if pay:
            r["fyer_salary_totamt"] = f"{pay:,}"
        if each:
            r["jan_salary_am"] = f"{each:,}"
        if tenure:
            r["avrg_cnwk_sdytrn"] = str(tenure)
        return r

    rows = [
        row("DX", "남", 40_000), row("DX", "여", 20_000), row("DS", "남", 50_000), row("DS", "여", 15_000),
        row("성별합계", "남", 90_000, pay=13_500_000_000_000, tenure=14),
        row("성별합계", "여", 35_000, each=120_000_000, tenure=11),
    ]
    emp = parse_employees(rows)
    assert emp["count"] == 125_000
    assert emp["avg_salary"] == pytest.approx((13_500_000_000_000 + 120_000_000 * 35_000) / 125_000)
    assert emp["avg_tenure"] == pytest.approx((14 * 90_000 + 11 * 35_000) / 125_000)
    assert sorted(emp["excluded"]) == ["성별합계/남", "성별합계/여"]


def test_parse_employees_keeps_coincidental_rows():
    def row(div, sex, sm):
        return {"fo_bbm": div, "sexdstn": sex, "sm": f"{sm:,}", "fyer_salary_totamt": f"{sm * 100_000_000:,}"}

    # 건축 부문 여직원 수가 다른 두 부문 여직원 합과 우연히 같아도 진짜 행이므로 빼지 않는다
    rows = [row("건축", "남", 2_000), row("건축", "여", 300), row("플랜트", "남", 900), row("플랜트", "여", 120),
            row("인프라", "남", 700), row("인프라", "여", 180)]
    assert parse_employees(rows)["count"] == 4_200
    # 부문별 '전체'와 전사 '전체/전체'가 함께 있는 표
    rows = [row("A", "남", 100), row("A", "여", 50), row("A", "전체", 150),
            row("B", "남", 80), row("B", "여", 20), row("B", "전체", 100), row("전체", "전체", 250)]
    assert parse_employees(rows)["count"] == 250
    # 이름이 모두 합계류여도(합계/남, 합계/여) 두 줄을 더한다
    assert parse_employees([row("합계", "남", 70), row("합계", "여", 30)])["count"] == 100
