"""날짜, 금액 파싱·표기 같은 공통 도구."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

_AMOUNT_JUNK = re.compile(r"[,\s원]")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_ymd(s: str) -> date | None:
    s = (s or "").strip().replace("-", "").replace(".", "")
    if len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def parse_amount(value) -> float | None:
    """DART 금액 문자열을 숫자로 바꾼다. '-', 빈칸, 괄호 음수, 쉼표를 처리한다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = str(value).strip()
    if s in {"", "-", "－", "N/A", "해당없음", "해당사항없음"}:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.replace("−", "-").replace("△", "-").replace("▲", "-")
    s = _AMOUNT_JUNK.sub("", s)
    if s.startswith("-"):
        negative = not negative
        s = s[1:]
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def parse_percent(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("%", "")
    return parse_amount(s)


def fmt_krw(amount: float | None, *, precise: bool = False) -> str:
    """금액을 사람이 읽기 쉬운 단위(조·억·만원)로 바꾼다."""
    if amount is None:
        return "-"
    sign = "-" if amount < 0 else ""
    a = abs(amount)
    if a >= 1e12:
        jo = a / 1e12
        if jo >= 10 and not precise:  # 100조 이상도 소수 한 자리(예산 727.9조원처럼 반올림이 크게 틀리지 않게)
            text = f"{jo:,.1f}"
            if text.endswith(".0"):
                text = text[:-2]
            return f"{sign}{text}조원"
        whole = int(jo)
        eok = round((a - whole * 1e12) / 1e8)
        if eok >= 10000:
            whole += 1
            eok = 0
        if eok == 0:
            return f"{sign}{whole}조원"
        return f"{sign}{whole}조 {eok:,}억원"
    if a >= 1e8:
        eok = a / 1e8
        if eok >= 10:
            return f"{sign}{eok:,.0f}억원"
        text = f"{eok:,.1f}"
        return f"{sign}{text[:-2] if text.endswith('.0') else text}억원"  # 4.0억원 → 4억원
    if a >= 1e4:
        if a < 1e6 and a % 1e4:  # 100만원 미만에서 만원 단위로 안 떨어지면 원 단위 그대로(최저임금 10,320원)
            return f"{sign}{a:,.0f}원"
        return f"{sign}{a / 1e4:,.0f}만원"
    return f"{sign}{a:,.0f}원"


def fmt_pct(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if signed:
        return f"{value:+.{digits}f}%"
    if digits == 0 and 0 < abs(value) < 1:  # 1% 미만이 0%로 보이지 않게(업계 1위 대비 0.4% 등)
        return f"{value:.1f}%"
    return f"{value:.{digits}f}%"


def fmt_times(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f}배"


def fmt_int(value: float | None, unit: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}{unit}"


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct(a: float | None, b: float | None) -> float | None:
    r = safe_div(a, b)
    return None if r is None else r * 100


def growth(cur: float | None, prev: float | None) -> float | None:
    """전년 대비 증감률(%). 기준값이 0 이하면 계산하지 않는다."""
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def latest_annual_year(d: date) -> int:
    """사업보고서는 3월 말까지 나오므로 4월부터는 직전 연도가 최신이다."""
    return d.year - 1 if d.month >= 4 else d.year - 2


def latest_periodic_reports(d: date) -> list[tuple[int, str, str]]:
    """그 시점에 나와 있을 가능성이 높은 정기보고서를 최신순으로 돌려준다.
    (사업연도, 보고서코드, 이름). 11011 사업, 11012 반기, 11013 1분기, 11014 3분기."""
    md = (d.month, d.day)
    y = d.year
    candidates: list[tuple[int, str, str]] = []
    if md >= (11, 15):
        candidates.append((y, "11014", "3분기"))
    if md >= (8, 15):
        candidates.append((y, "11012", "반기"))
    if md >= (5, 16):
        candidates.append((y, "11013", "1분기"))
    if md >= (4, 1):
        candidates.append((y - 1, "11011", "사업"))
    else:
        candidates.append((y - 1, "11014", "3분기"))
        candidates.append((y - 2, "11011", "사업"))
    return candidates


def filing_window(report_date: date, last_report_date: date | None, max_days: int = 7) -> tuple[date, date]:
    """이번 리포트가 다룰 공시 접수일 구간. 지난 리포트 다음 날부터 어제까지.
    지난 리포트 기록이 없으면 어제(월요일이면 금~일)만 본다."""
    end = report_date - timedelta(days=1)
    if last_report_date and last_report_date < report_date:
        # 지난 리포트는 (그날 - 1일)까지 다뤘으므로 지난 리포트 날짜부터 이어서 본다
        start = min(last_report_date, end)
    else:
        start = end - timedelta(days=2) if report_date.weekday() == 0 else end
    if (end - start).days + 1 > max_days:
        start = end - timedelta(days=max_days - 1)
    return start, end


def date_ko(d: date) -> str:
    weekdays = "월화수목금토일"
    return f"{d.year}년 {d.month}월 {d.day}일({weekdays[d.weekday()]})"


def clean_text(s: str | None, limit: int | None = None) -> str:
    if not s:
        return ""
    t = re.sub(r"<[^>]+>", " ", str(s))
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    t = re.sub(r"\s+", " ", t).strip()
    if limit and len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """받침 유무에 맞는 조사(이/가, 은/는, 을/를)를 고른다."""
    w = (word or "").strip()
    if not w:
        return without_batchim
    ch = w[-1]
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
    elif ch.isdigit():
        has = ch in "013678"
    elif ch.isalpha():
        has = ch.lower() in "lmnr"
    else:
        has = False
    return with_batchim if has else without_batchim


def md_cell(s) -> str:
    """마크다운 표 칸에 넣을 수 있게 줄바꿈과 | 를 정리한다."""
    if s is None:
        return "-"
    t = str(s).replace("\r", " ").replace("\n", " ").replace("|", "/")
    t = re.sub(r"\s+", " ", t).strip()
    return t or "-"


def md_paragraphs(text) -> str:
    """줄마다 한 문단으로 보고 사이에 빈 줄을 넣는다(YAML 블록 문자열 → 마크다운 문단)."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return "\n\n".join(lines)


def first_paragraph(text) -> str:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def md_link_text(s) -> str:
    """마크다운 링크 글자 안의 대괄호가 링크를 깨지 않게 바꾼다."""
    return md_cell(s).replace("[", "(").replace("]", ")")


def html_text(s, limit: int = 0) -> str:
    """HTML 태그(details 요약 줄 등) 안에 넣을 글자. 특수문자를 바꾸고, limit이 있으면 그 길이에서 자른다."""
    text = " ".join(str(s or "").split())
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
