from datetime import date

from casenote.util import filing_window, fmt_krw, josa, latest_annual_year, latest_periodic_reports, parse_amount


def test_parse_amount_variants():
    assert parse_amount("1,234,567") == 1234567
    assert parse_amount("-1,000") == -1000
    assert parse_amount("(2,500)") == -2500
    assert parse_amount("-") is None
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount("12.5") == 12.5
    assert parse_amount("△300") == -300


def test_fmt_krw_units():
    assert fmt_krw(None) == "-"
    assert fmt_krw(300_870_900_000_000) == "300.9조원"
    assert fmt_krw(727_900_000_000_000) == "727.9조원"
    assert fmt_krw(10_320) == "10,320원"
    assert fmt_krw(2_156_880) == "216만원"
    assert fmt_krw(12_345_000_000_000) == "12.3조원"
    assert fmt_krw(12_000_000_000_000) == "12조원"
    assert fmt_krw(1_234_500_000_000) == "1조 2,345억원"
    assert fmt_krw(1_000_000_000_000) == "1조원"
    assert fmt_krw(45_600_000_000) == "456억원"
    assert fmt_krw(350_000_000) == "3.5억원"
    assert fmt_krw(120_000) == "12만원"
    assert fmt_krw(-2_000_000_000_000) == "-2조원"


def test_window_and_years():
    fri = date(2026, 11, 20)
    assert filing_window(fri, None) == (date(2026, 11, 19), date(2026, 11, 19))
    mon = date(2026, 11, 23)
    assert filing_window(mon, None) == (date(2026, 11, 20), date(2026, 11, 22))
    # 지난 리포트가 금요일이면 월요일 리포트는 금~일을 본다
    assert filing_window(mon, fri) == (fri, date(2026, 11, 22))
    # 오래 건너뛰면 최대 일수로 자른다
    assert filing_window(mon, date(2026, 10, 1), max_days=7) == (date(2026, 11, 16), date(2026, 11, 22))
    assert latest_annual_year(date(2026, 11, 20)) == 2025
    assert latest_annual_year(date(2026, 3, 2)) == 2024
    assert latest_periodic_reports(date(2026, 11, 20))[0] == (2026, "11014", "3분기")


def test_josa():
    assert josa("삼성전자", "이", "가") == "가"
    assert josa("삼성물산", "이", "가") == "이"
    assert josa("NAVER", "이", "가") == "이"
    assert josa("KT", "이", "가") == "가"
