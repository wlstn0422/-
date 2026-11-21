"""공시·뉴스 사례를 경영학·경제학 교과서 문체로 설명하고, 이론에 실제 숫자를 넣어 적용한다.

AI를 부르지 않고 규칙과 미리 써 둔 설명으로만 만들어 추가 비용이 없다. 숫자는 공시 원문과 사업보고서에서
가져오고, 가정을 쓰는 곳(본전 계산의 금리)은 문장 안에 가정이라고 밝힌다.
"""

from __future__ import annotations

import re

from .util import clean_text, fmt_krw, josa, parse_amount, parse_percent, safe_div

ASSUMED_RATE = 0.05  # 본전 계산에 쓰는 연 금리 가정(빌린 돈의 이자, 내 돈이면 다른 데 넣었을 때의 수익)

# 한국표준산업분류 코드 앞자리 → '○○ 회사'에 넣을 쉬운 업종 이름. 길게 맞는 코드를 먼저 쓴다.
KSIC_NAMES = {
    "01": "농업", "02": "임업", "03": "어업", "05": "석탄·원유 채굴", "06": "금속 광업", "07": "광물 채굴",
    "08": "광업 지원", "10": "식품 제조", "11": "음료 제조", "12": "담배 제조", "13": "섬유 제조", "14": "의류 제조",
    "15": "가죽·신발 제조", "16": "목재 가공", "17": "종이 제조", "18": "인쇄", "19": "석유 정제", "20": "화학제품 제조",
    "20423": "화장품 제조", "21": "의약품 제조", "22": "고무·플라스틱 제조", "23": "유리·시멘트 등 소재 제조",
    "24": "철강·금속 소재 제조", "25": "금속 가공품 제조", "26": "전자부품·통신장비 제조", "261": "반도체 제조",
    "262": "전자부품 제조", "263": "컴퓨터 제조", "264": "통신·방송장비 제조", "265": "영상·음향기기 제조",
    "27": "의료·정밀기기 제조", "28": "전기장비 제조", "282": "배터리 제조", "29": "기계·장비 제조",
    "30": "자동차·부품 제조", "303": "자동차 부품 제조", "31": "선박·운송장비 제조", "311": "조선", "32": "가구 제조",
    "33": "기타 제품 제조", "34": "산업장비 수리", "35": "전기·가스 공급", "36": "수도", "37": "하수 처리",
    "38": "폐기물 처리", "39": "환경 정화", "41": "종합 건설", "42": "전문 공사", "45": "자동차 판매",
    "46": "도매·유통", "47": "소매", "49": "육상 운송", "50": "해운", "51": "항공 운송", "52": "창고·물류",
    "55": "숙박", "56": "음식점", "58": "출판·소프트웨어", "582": "소프트웨어 개발", "59": "영상·음악 제작",
    "60": "방송", "61": "통신", "62": "IT 서비스", "63": "정보서비스", "64": "금융", "649": "투자·금융", "65": "보험",
    "66": "금융 서비스", "68": "부동산", "70": "연구개발", "71": "전문 서비스", "713": "광고",
    "715": "지주·경영컨설팅", "72": "엔지니어링", "73": "과학기술 서비스", "74": "시설 관리", "75": "사업 지원 서비스",
    "76": "임대", "85": "교육", "86": "의료(병원)", "87": "사회복지", "90": "예술·창작", "91": "스포츠·오락",
    "95": "수리", "96": "개인 서비스",
}

# 업종이 서로 가까운지 보려고 묶은 계열: (이름, 표준산업분류 앞자리, 사업 설명에 나오는 단어)
FAMILIES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("제약·바이오·의료", ("21", "27", "86", "701"),
     ("의약", "제약", "바이오", "신약", "진단", "의료", "병원", "헬스케어", "세포", "항체", "백신", "동물약품")),
    ("반도체·전자", ("26",), ("반도체", "디스플레이", "전자부품", "인쇄회로", "PCB", "카메라모듈", "웨이퍼", "전자")),
    ("배터리·전기장비", ("28",), ("이차전지", "2차전지", "배터리", "양극재", "음극재", "전해질", "변압기", "전력기기", "전선")),
    ("자동차·운송장비", ("30", "31", "45"), ("자동차", "차량", "조선", "선박", "항공기", "모빌리티")),
    ("화학·소재", ("19", "20", "22", "23", "24", "25"), ("화학", "소재", "플라스틱", "철강", "금속", "정유", "석유화학")),
    ("소비재·식품", ("10", "11", "12", "13", "14", "15", "20423"),
     ("식품", "음료", "외식", "화장품", "의류", "패션", "생활용품", "주류")),
    ("기계·장비", ("29", "34"), ("기계", "장비", "로봇", "설비", "공작기계")),
    ("건설·부동산", ("41", "42", "68"), ("건설", "건축", "부동산", "토목", "시행", "인테리어", "주택")),
    ("유통·물류", ("46", "47", "49", "50", "51", "52"), ("유통", "도매", "소매", "커머스", "쇼핑", "물류", "운송", "택배", "해운", "무역")),
    ("IT·소프트웨어", ("58", "61", "62", "63"),
     ("소프트웨어", "플랫폼", "정보통신", "데이터", "클라우드", "인공지능", "AI", "게임", "솔루션", "IT")),
    ("미디어·광고·콘텐츠", ("59", "60", "90", "713"),
     ("광고", "마케팅", "미디어", "콘텐츠", "방송", "영화", "엔터", "음악", "드라마", "매니지먼트")),
    ("금융", ("64", "65", "66"), ("금융", "투자조합", "자산운용", "캐피탈", "증권", "보험", "은행", "벤처캐피탈", "신기술사업")),
    ("에너지·환경", ("05", "06", "07", "08", "35", "36", "37", "38", "39"),
     ("에너지", "발전", "태양광", "풍력", "수소", "가스", "환경", "폐기물", "재활용")),
]

# 공시 유형마다 '거래의 성격' 첫 문장(교과서 문체)
TYPE_PLAIN = {
    "merger": "합병은 둘 이상의 회사가 하나의 회사로 결합하는 것이다. 흡수합병에서는 한 회사(존속회사)만 남고 다른 회사(소멸회사)는 해산하며, 소멸회사의 주주는 그 대가로 존속회사의 주식을 받는다.",
    "split_merger": "분할합병은 한 회사의 사업 일부를 분리하여 다른 회사에 곧바로 합병시키는 것이다.",
    "split": "회사분할은 한 회사의 사업 일부를 떼어 내어 새로운 회사를 설립하는 것이다.",
    "share_exchange": "주식의 포괄적 교환·이전은 상대 회사 주주가 보유한 주식을 자사 주식과 교환하여 상대 회사를 완전자회사(지분 100%)로 만드는 방법이다.",
    "tender_offer": "공개매수는 매수 기간·가격·수량을 공개하고 증권시장 밖에서 불특정 다수의 주주로부터 주식을 사들이는 것이다. 통상 시가보다 높은 가격을 제시하며, 경영권 확보나 상장폐지를 목적으로 하는 경우가 많다.",
    "control_change": "최대주주의 변경은 회사의 지배권이 이전된다는 의미이므로, 경영진 교체와 경영 전략의 변화가 뒤따르는 경우가 많다.",
    "stock_acq": "타법인 주식 취득은 다른 회사의 주식을 매입하여 그 회사의 지분을 보유하는 거래이다.",
    "stock_trf": "타법인 주식 처분은 보유하던 다른 회사의 주식을 매각하여 현금화하는 거래이다.",
    "business_acq": "영업양수는 회사 전체가 아니라 특정 사업 부문(인력·설비·거래처 등)을 일괄하여 인수하는 것이다. 주식 인수와 달리 필요한 사업만 선택하여 취득할 수 있다.",
    "business_trf": "영업양도는 회사의 특정 사업 부문을 인력·설비·거래처와 함께 일괄하여 매각하는 것이다.",
    "asset_acq": "유형자산은 토지·건물·기계장치처럼 물리적 형태가 있고 장기간 사용하는 자산이다. 이를 취득하면 현금이 설비로 바뀌고, 취득원가는 내용연수에 걸쳐 감가상각비로 배분된다.",
    "asset_trf": "유형자산 양도는 보유한 토지·건물·설비를 매각하여 현금으로 전환하는 거래이다.",
    "ipo": "기업공개(IPO)는 회사가 처음으로 불특정 다수의 투자자에게 주식을 매각하고 증권시장에 상장하는 것이다. 상장 이후에는 누구나 증권시장에서 그 회사의 주식을 매매할 수 있다.",
    "rights_offering": "유상증자는 신주를 발행하여 투자자로부터 자금을 조달하는 것이다. 상환 의무가 없는 자기자본이 늘어나지만, 발행주식 수가 증가하여 기존 주주의 지분율과 주당 가치가 낮아지는 희석 효과가 발생한다.",
    "rights_bonus": "유무상증자는 신주를 발행하여 자금을 조달하는 유상증자와, 대가 없이 기존 주주에게 신주를 배정하는 무상증자를 함께 실시하는 것이다.",
    "bonus_issue": "무상증자는 대가를 받지 않고 기존 주주에게 보유 주식 수에 비례하여 신주를 배정하는 것이다. 잉여금이 자본금으로 대체될 뿐 회사의 가치는 변하지 않으며, 주가는 늘어난 주식 수만큼 조정된다(권리락).",
    "capital_reduction": "감자는 자본금을 감소시키는 것이다. 주주에게 대가를 지급하지 않고 누적 결손을 보전하는 무상감자와, 주주에게 자금을 반환하는 유상감자로 나뉜다.",
    "treasury_trust": "자기주식 취득 신탁계약은 증권회사 등에 자금을 맡겨 정해진 기간 동안 회사 주식을 대신 매입하게 하는 방식이다.",
    "treasury_buy": "자기주식 취득은 회사가 시장에서 자사 주식을 매입하는 것이다. 유통 주식 수가 줄어 남은 주주의 지분 가치가 높아지며, 매입한 주식을 소각하면 그 효과가 확정된다.",
    "treasury_sell": "자기주식 처분은 회사가 보유하던 자사 주식을 다시 매각하는 것이다. 자금 조달, 임직원 보상, 우호 세력 확보 등의 목적으로 이루어진다.",
    "treasury_cancel": "자기주식 소각은 회사가 보유한 자사 주식을 없애 발행주식 수를 줄이는 것이다. 이익이 같더라도 주식 수가 줄어 주당순이익(EPS)이 증가한다.",
    "cb": "전환사채(CB)는 발행 시점에는 회사채이지만, 투자자가 원하면 미리 정한 가격(전환가액)에 주식으로 전환할 수 있는 채권이다. 회사는 낮은 이자로 자금을 조달하고, 투자자는 주가가 상승하면 주식으로 전환하여 시세차익을 얻는다.",
    "bw": "신주인수권부사채(BW)는 회사채에 '정해진 가격으로 신주를 인수할 권리'가 결합된 채권이다. 투자자는 낮은 이자를 받는 대신 주가가 오르면 시가보다 낮은 가격에 신주를 취득할 수 있다.",
    "eb": "교환사채(EB)는 발행회사가 보유한 다른 주식(자기주식이나 계열회사 주식)으로 교환할 수 있는 채권이다. 신주를 발행하지 않고 보유 주식을 교부한다는 점에서 전환사채와 다르다.",
    "valueup": "기업가치 제고(밸류업) 계획은 주가가 내재가치보다 낮게 평가되는 문제를 해소하기 위해 회사가 제시하는 배당·자기주식·수익성 목표이다.",
    "dividend": "배당은 회사가 창출한 이익의 일부를 주주에게 현금 등으로 분배하는 것이다.",
    "earnings": "잠정실적 공시는 외부감사를 받기 전에 영업실적을 먼저 알리는 것이다. 실적이 크게 변동하면 투자자가 신속히 알 수 있도록 사전에 공시하게 되어 있다.",
    "contract": "단일판매·공급계약 공시는 매출액에 비해 규모가 큰 계약을 체결하였음을 알리는 것이다. 계약 금액이 일정 비율을 넘으면 공시 의무가 생긴다.",
    "insolvency": "부도·회생절차·영업정지 공시는 회사가 채무를 상환하기 어렵거나 사업을 계속하기 어려운 상황에 처했다는 신호이다.",
}

# 거래 목적 문장에서 어떤 효과를 노리는지 가늠하는 단어
PURPOSE_KINDS: list[tuple[str, tuple[str, ...]]] = [
    ("revenue", ("유통", "판매", "판로", "마케팅", "고객", "시장 진출", "시장진출", "해외", "매출", "영업망", "브랜드")),
    ("cost", ("원가", "효율", "비용 절감", "비용절감", "통합", "구매", "수직계열")),
    ("capability", ("기술", "연구", "개발", "R&D", "역량", "인력", "노하우", "특허")),
    ("financial", ("투자수익", "투자 수익", "단순투자", "단순 투자", "재무적", "자산운용", "수익 창출", "투자목적")),
    ("liquidity", ("재무구조", "유동성", "차입금 상환", "차입금상환", "부채", "운영자금", "자금 확보", "자금확보")),
    ("control", ("경영권", "지배력", "지배구조", "경영 참여", "경영참여")),
    ("diversify", ("다각화", "신규 사업", "신규사업", "신사업", "사업 확장", "사업확장", "포트폴리오")),
    ("focus", ("핵심", "선택과 집중", "집중", "본업")),
]


# ------------------------------------------------------------------ 작은 도구들
def clean_name(s) -> str:
    """'주식회사 드림인사이트 ( DREAMINSIGHT Co,.Ltd).' → '드림인사이트'. 공시 원문은 줄바꿈이 섞여 있어 먼저 한 줄로 편다."""
    t = re.sub(r"\s+", " ", str(s or ""))
    t = re.sub(r"\(.*?\)|（.*?）", " ", t)
    t = re.sub(r"주식회사|㈜|\(주\)|유한책임회사|유한회사", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,·")
    return t


def _prefix_lookup(code, table: dict):
    digits = re.sub(r"\D", "", str(code or ""))
    for n in range(len(digits), 1, -1):
        if digits[:n] in table:
            return table[digits[:n]]
    return None


def industry_name(induty_code) -> str | None:
    return _prefix_lookup(induty_code, KSIC_NAMES)


def family_of_code(induty_code) -> str | None:
    table = {p: name for name, prefixes, _ in FAMILIES for p in prefixes}
    return _prefix_lookup(induty_code, table)


def family_of_text(text) -> str | None:
    t = str(text or "")
    best, hits = None, 0
    for name, _, words in FAMILIES:
        n = sum(1 for w in words if w in t)
        if n > hits:
            best, hits = name, n
    return best


def share_words(part, whole) -> str | None:
    """비율을 '약 6분의 1(16.5%)', '절반 정도(51%)', '1.8배'처럼 감으로 읽히게."""
    r = safe_div(part, whole)
    if r is None or r <= 0:
        return None
    p = r * 100
    if r >= 1.05:
        return f"{r:.1f}배"
    if r >= 0.9:
        return f"거의 맞먹는 크기({p:.0f}%)"
    if 0.45 <= r < 0.55:
        return f"절반 정도({p:.0f}%)"
    if 0.04 <= r < 0.45:
        n = round(1 / r)
        if n >= 2 and abs(1 / n - r) / r <= 0.12:
            return f"약 {n}분의 1({p:.1f}%)"
    if p < 1:
        return f"{p:.2f}%"
    return f"{p:.0f}%" if p >= 10 else f"{p:.1f}%"


def pct_text(p: float) -> str:
    """지분율 같은 비율을 소수 둘째 자리까지, 끝의 0은 떼고 적는다(18.55%, 18.6%, 20%)."""
    return f"{p:.2f}".rstrip("0").rstrip(".") + "%"


def _base_word(word: str) -> str:
    """조사는 괄호 앞 낱말에 맞춘다('약 6분의 1(16.5%)' → '약 6분의 1')."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(word or "")) or str(word or "")


def _eul(word: str) -> str:
    return josa(_base_word(word), "을", "를")


def _i(word: str) -> str:
    return josa(_base_word(word), "이", "가")


def _eun(word: str) -> str:
    return josa(_base_word(word), "은", "는")


def _euro(word: str) -> str:
    """'으로/로': 받침이 없거나 ㄹ 받침이면 '로'."""
    w = _base_word(word).strip()
    ch = w[-1] if w else ""
    if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8:  # ㄹ 받침
        return "로"
    return josa(w, "으로", "로")


def _raw(ev, key) -> str:
    v = str((ev.detail or {}).get(key) or "").strip()
    return "" if v in {"-", "해당사항없음", "해당없음"} else v


def _raw_num(ev, key) -> float | None:
    v = _raw(ev, key)
    return parse_amount(v) if v else None


def _raw_pct(ev, key) -> float | None:
    v = _raw(ev, key)
    return parse_percent(v) if v else None


def _fact(ev, *labels) -> str | None:
    for label, val in list(ev.facts) + list(ev.long_facts):
        if label in labels:
            return val
    return None


def _fact_pct(ev, *labels) -> float | None:
    v = _fact(ev, *labels)
    return parse_percent(v) if v else None


def _short(text, limit: int = 60) -> str:
    t = clean_text(text)
    t = re.sub(r"^\s*\d+[\.\)]\s*", "", t).rstrip(" .")
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def purpose_kinds(text) -> list[str]:
    t = str(text or "")
    return [kind for kind, words in PURPOSE_KINDS if any(w in t for w in words)]


def funding(ev) -> str | None:
    """대금 조달 방법을 '차입금으로' 같은 부사구로."""
    t = " ".join(filter(None, [_raw(ev, "dl_pym"), _fact(ev, "대금 지급 방식") or ""]))
    if not t:
        return None
    own = any(w in t for w in ("자기자금", "자체자금", "자체 자금", "자기 자금", "보유자금", "보유 자금", "보유현금", "보유 현금", "자기자본"))
    loan = "차입" in t or "대출" in t
    if own and loan:
        return "자체 자금과 차입금으로"
    if loan:
        return "차입금으로"
    if "증자" in t:
        return "유상증자 자금으로"
    if "사채" in t:
        return "사채 발행 자금으로"
    if own:
        return "자체 자금으로"
    return None


def subject(ev) -> str:
    """'의약품 제조 기업 애드바이오텍'처럼 회사 앞에 업종을 붙인다."""
    name = industry_name(getattr(ev, "induty_code", ""))
    if name and "지주" not in name:
        return f"{name} 기업 {ev.corp_name}"
    return ev.corp_name


def _year(ev) -> str:
    y = (ev.fin or {}).get("year")
    return f"{y}년 " if y else ""


def size_line(ev, amount: float | None = None, what: str | None = None, income_years: bool = True) -> str | None:
    """거래 금액을 총자산·매출액·영업이익과 비교해 거래의 상대적 규모를 한 문장으로.
    income_years: 자금을 지출하는 거래면 '연간 영업이익의 몇 년분'을 덧붙인다(매각 거래에는 붙이지 않는다)."""
    amt = amount if amount is not None else ev.amount
    if not amt:
        return None
    fin = ev.fin or {}
    parts: list[str] = []
    assets, revenue, oi = fin.get("assets"), fin.get("revenue"), fin.get("operating_income")
    official = _fact_pct(ev, "총자산 대비", "자산총액 대비")
    if official:
        parts.append(f"회사 총자산의 {share_words(official, 100)}")
    elif assets:
        parts.append(f"회사 총자산({fmt_krw(assets)})의 {share_words(amt, assets)}")
    if revenue:
        parts.append(f"{_year(ev)}매출액({fmt_krw(revenue)})의 {share_words(amt, revenue)}")
    if not parts:
        return None
    head = what or fmt_krw(amt)
    line = f"{head}{_eun(head)} " + ", ".join(parts) + "에 해당한다."
    if oi is not None and oi <= 0:
        line += f" {_year(ev)}에는 영업손실({fmt_krw(-oi)})을 기록하였다."
    elif income_years and oi and amt / oi >= 1.5:
        line += f" 이는 연간 영업이익({fmt_krw(oi)})의 {amt / oi:.1f}년분에 해당한다."
    return line


def breakeven_line(ev, amt: float, source: str = "이 투자에서") -> str:
    cost = amt * ASSUMED_RATE
    line = (f"투자의 손익분기: {fmt_krw(amt)}의 자금을 연 5%의 비용(차입 이자 또는 기회비용)으로 조달한다고 가정하면 "
            f"연간 자본비용은 {fmt_krw(cost)}이다. 따라서 {source} 매년 그 이상의 추가 이익이 발생해야 기업가치가 증가한다.")
    oi = (ev.fin or {}).get("operating_income")
    if oi and oi > 0:
        line += f" 이는 연간 영업이익({fmt_krw(oi)})의 {share_words(cost, oi)}에 해당하는 부담이다."
    elif oi is not None and oi <= 0:
        line += " 본업이 영업손실 상태이므로 이 부담은 더욱 크다."
    return line


def stake_text(p: float | None) -> tuple[str, str] | None:
    """지분율 → (지배구조상 의미, 회계상 의미)."""
    if p is None:
        return None
    if p > 50:
        return ("과반 지분(50% 초과)으로 대상 회사를 지배하게 되므로 대상 회사는 종속회사(자회사)가 된다",
                "회계상으로는 대상 회사를 연결재무제표에 합산하며, 순자산 공정가치를 초과하여 지급한 금액은 영업권으로 인식한다")
    if p >= 20:
        return ("경영에 유의적인 영향력을 행사할 수 있는 지분(20~50%)이다",
                "회계상으로는 통상 관계기업으로 분류하여, 대상 회사 순이익 중 지분율에 해당하는 금액을 투자이익으로 인식한다(지분법)")
    return ("지배력(통상 50% 초과)이나 유의적 영향력(통상 20% 이상)에 미치지 못하는 투자 목적의 지분이다",
            "회계상으로는 통상 금융자산으로 분류하여 공정가치로 측정하고, 가치 변동을 평가손익으로 반영한다")


def relatedness(ev, target_text) -> str | None:
    mine = family_of_code(getattr(ev, "induty_code", ""))
    theirs = family_of_text(target_text)
    if not mine or not theirs:
        return None
    if mine == theirs:
        return (f"사업 관련성: 두 회사 모두 {mine} 업종에 속하므로 판매망 공유나 원가 절감 등의 시너지를 비교적 정량화하기 쉽다"
                "(관련 다각화 또는 수평적 결합).")
    return (f"사업 관련성: 인수 회사는 {mine}, 대상 회사는 {theirs} 업종으로 서로 달라 기존 사업의 역량을 그대로 활용하기 어렵다. "
            "앤소프 매트릭스에 따르면 신제품으로 신시장에 진출하는 '다각화'에 가까워 위험이 가장 큰 성장 경로에 해당한다.")


def synergy_kind_line(purpose: str | None, what: str = "취득") -> str | None:
    if not purpose:
        return None
    kinds = purpose_kinds(purpose)
    q = _short(purpose, 50)
    if "revenue" in kinds:
        return (f"시너지의 유형: 공시된 {what} 목적('{q}')은 판매 확대를 통한 매출 시너지를 겨냥한다. "
                "매출 시너지는 비용 시너지에 비해 실현 여부가 불확실한 것으로 알려져 있다.")
    if "cost" in kinds:
        return (f"시너지의 유형: 공시된 {what} 목적('{q}')은 중복 비용 제거를 통한 비용 시너지를 겨냥한다. "
                "비용 시너지는 측정이 비교적 쉽고 실현 가능성도 높은 편이다.")
    if "capability" in kinds:
        return (f"시너지의 유형: 공시된 {what} 목적('{q}')은 기술·인력 등 핵심 역량의 확보에 있다. "
                "이러한 시너지는 성과가 재무 수치로 나타나기까지 시간이 걸린다.")
    if "financial" in kinds:
        return f"거래의 목적: 공시된 {what} 목적('{q}')으로 볼 때 사업 시너지보다 재무적 투자수익이 목적이다. 이 경우 취득 가격의 적정성이 투자 성과를 좌우한다."
    if "diversify" in kinds:
        return f"거래의 목적: 공시된 {what} 목적('{q}')으로 볼 때 신규 사업에 진출하는 다각화이다. 기존 사업과의 관련성이 낮을수록 실패 위험이 커진다."
    if "control" in kinds:
        return f"거래의 목적: 공시된 {what} 목적('{q}')으로 볼 때 경영권 또는 지배력 확보를 위한 거래이다."
    return f"거래의 목적: '{q}'."


# ------------------------------------------------------------------ 공시 유형별 풀이
SALE_KEYS = {"stock_trf", "business_trf", "asset_trf", "treasury_sell"}


def _base(ev) -> dict:
    size = size_line(ev, income_years=ev.rule.key not in SALE_KEYS)
    return {"what": "", "plain": TYPE_PLAIN.get(ev.rule.key, ""), "size": size, "steps": [], "takeaway": ""}


def _num(text) -> float | None:
    """'1,400,000주', '18,000원', '12.5%'처럼 단위가 붙은 숫자를 읽는다."""
    if text is None:
        return None
    return parse_amount(re.sub(r"[^\d.,\-()]", "", str(text)))


def _stock_acq(ev, out: dict) -> None:
    tgt = clean_name(_raw(ev, "iscmp_cmpnm")) or "대상 회사"
    biz = _raw(ev, "iscmp_mbsn")
    after = _raw_pct(ev, "atinh_eqrt")
    amt = ev.amount
    me = subject(ev)
    who = f"{tgt}({biz})" if biz else tgt
    out["what"] = f"{me}{_i(me)} {who}의 주식을 {fmt_krw(amt)}에 취득한다." if amt else f"{me}{_i(me)} {who}의 주식을 취득한다."
    if after is not None:
        out["what"] += f" 취득 후 지분율은 {pct_text(after)}이다."
    st = stake_text(after)
    if st:
        out["plain"] += f" 취득 후 지분율 {pct_text(after)}는 {st[0]}. {st[1]}."
    fund = funding(ev)
    if out["size"] and fund:
        out["size"] += f" 취득 대금은 {fund} 조달한다."
    steps = []
    shares, after_sh, total_sh = _raw_num(ev, "inhdtl_stkcnt"), _raw_num(ev, "atinh_owstkcnt"), _raw_num(ev, "iscmp_tisstk")
    bought = None
    if after and shares and after_sh:
        bought = after * shares / after_sh
    elif shares and total_sh:
        bought = shares / total_sh * 100
    elif after:
        bought = after
    if amt and bought and bought > 0.5:
        whole = amt / (bought / 100)
        steps.append(f"기업가치 환산: 지분 {pct_text(bought)}에 {fmt_krw(amt)}{_eul(fmt_krw(amt))} 지급하므로, 이 가격은 {tgt}의 지분 전체 가치를 "
                     f"약 {fmt_krw(whole)}{_euro(fmt_krw(whole))} 평가한 것이다. 이 금액을 대상 회사의 연간 순이익과 비교한 배수(PER)가 "
                     "취득 가격의 적정성을 판단하는 기준이 된다.")
    if amt:
        steps.append(breakeven_line(ev, amt))
    line = synergy_kind_line(_fact(ev, "취득 목적"))
    if line:
        steps.append(line)
    rel = relatedness(ev, biz)
    if rel:
        steps.append(rel)
    if after is not None:
        if after > 50:
            steps.append("지배력: 과반 지분을 확보하므로 시너지를 직접 실현할 수 있다. 다만 인수가 실패할 경우 그 손실도 전부 부담하게 된다.")
        elif after >= 20:
            steps.append("지배력: 이사회에 영향력을 행사할 수는 있으나 경영을 단독으로 결정하기는 어렵다. 시너지 실현에는 대상 회사 경영진의 협력이 필요하다.")
        else:
            steps.append("지배력: 지분율이 20%에 미치지 못하여 경영에 직접 관여하기 어렵다. 따라서 시너지 실현 여부는 별도의 협력 계약이나 이사 파견 여부에 달려 있다.")
    out["steps"] = steps
    ta = (ev.fin or {}).get("assets")
    portion = share_words(_fact_pct(ev, "총자산 대비"), 100) if _fact_pct(ev, "총자산 대비") else share_words(amt, ta)
    head = f"회사 총자산의 {portion}에 해당하는 자금을 " if portion else ""
    fund_part = f"{fund} 조달하여 " if fund and portion else ""
    stake = f"지분 {pct_text(after)}" if after is not None else "지분"
    key = ("지배력 없이 시너지를 실현할 수 있는지" if (after is not None and after <= 50)
           else "지급한 프리미엄 이상의 시너지를 창출할 수 있는지")
    out["takeaway"] = f"{head}{fund_part}{biz or tgt} 기업의 {stake}{_eul(stake)} 취득한 결정이다. {key}가 핵심 쟁점이다."


def _stock_trf(ev, out: dict) -> None:
    tgt = clean_name(_raw(ev, "iscmp_cmpnm")) or "보유 회사"
    biz = _raw(ev, "iscmp_mbsn")
    after = _raw_pct(ev, "attrf_eqrt")
    me = subject(ev)
    amt = ev.amount
    who = f"{tgt}({biz})" if biz else tgt
    out["what"] = f"{me}{_i(me)} 보유하던 {who}의 주식을 {fmt_krw(amt) + '에 ' if amt else ''}매각한다."
    if after is not None:
        out["what"] += f" 매각 후 지분율은 {pct_text(after)}이다."
        if after == 0:
            out["plain"] += " 보유 지분을 전량 매각하므로 해당 회사에 대한 투자를 완전히 회수한다."
    liab = (ev.fin or {}).get("liabilities")
    if out["size"] and amt and liab:
        out["size"] += f" 매각 대금은 회사 부채총계({fmt_krw(liab)})의 {share_words(amt, liab)}에 해당한다."
    steps = ["BCG 매트릭스의 관점: BCG 매트릭스는 사업을 시장성장률과 상대적 시장점유율에 따라 별, 현금 젖소, 물음표, 개로 분류하고 "
             "자원 배분의 우선순위를 정한다. 지분 매각은 해당 투자를 회수 또는 철수 대상으로 판단했음을 의미한다."]
    purpose = _fact(ev, "처분 목적")
    kinds = purpose_kinds(purpose)
    if "liquidity" in kinds:
        steps.append(f"처분 목적('{_short(purpose, 50)}')으로 볼 때 사업 포트폴리오 판단보다 유동성 확보가 우선된 경우로 해석된다.")
    elif "focus" in kinds:
        steps.append(f"처분 목적('{_short(purpose, 50)}')으로 볼 때 핵심 사업에 자원을 집중하기 위한 포트폴리오 조정이다.")
    elif purpose:
        steps.append(f"처분 목적: '{_short(purpose, 60)}'.")
    steps.append("회계적 영향: 매각 가격이 장부금액을 초과하면 처분이익이, 미달하면 처분손실이 당기손익에 반영된다. "
                 "이후 매각 대금의 사용처(부채 상환 또는 신규 투자)가 후속 분석의 대상이다.")
    out["steps"] = steps
    cash = fmt_krw(amt) if amt else "현금"
    out["takeaway"] = f"{tgt} 지분을 매각하여 {cash}{'의 현금' if amt else ''}을 확보하는 결정이다. 매각 대금의 활용 방안이 핵심 쟁점이다."


def _business_acq(ev, out: dict) -> None:
    me = subject(ev)
    bsn = _raw(ev, "inh_bsn") or "사업 부문"
    who = clean_name(_raw(ev, "dlptn_cmpnm"))
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {who + '의 ' if who else ''}{bsn}{_eul(bsn)} {fmt_krw(amt) + '에 ' if amt else ''}일괄 양수한다."
    sl = _raw_pct(ev, "sl_rt")
    if sl:
        out["what"] += f" 양수 대상 사업의 매출액은 당사 매출액의 {sl:.1f}%에 해당한다."
    steps = []
    if amt:
        steps.append(breakeven_line(ev, amt, "양수한 사업에서"))
    line = synergy_kind_line(_fact(ev, "양수 목적"), "양수")
    if line:
        steps.append(line)
    rel = relatedness(ev, bsn + " " + (_fact(ev, "양수 영업의 주요 내용") or ""))
    if rel:
        steps.append(rel)
    rl = _raw(ev, "dlptn_rl_cmpn")
    if any(w in rl for w in ("계열", "특수관계", "최대주주", "자회사", "종속")):
        steps.append(f"거래의 공정성: 거래상대방이 특수관계인({_short(rl, 20)})이므로 양수가액의 공정성(외부평가)이 특히 중요하다. "
                     "계열회사 간 거래에서 가격이 과대 산정되면 한쪽 회사의 주주가 손실을 입는다.")
    out["steps"] = steps
    out["takeaway"] = f"{bsn}{_eul(bsn)} 인수하여 성장을 도모하는 결정이다. 지급한 대가 이상의 시너지를 창출할 수 있는지가 핵심 쟁점이다."


def _business_trf(ev, out: dict) -> None:
    me = subject(ev)
    bsn = _raw(ev, "trf_bsn") or "사업 부문"
    who = clean_name(_raw(ev, "dlptn_cmpnm"))
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {bsn}{_eul(bsn)} {who + '에 ' if who else ''}{fmt_krw(amt) + '에 ' if amt else ''}일괄 양도한다."
    sl = _raw_pct(ev, "sl_rt")
    steps = ["BCG 매트릭스의 관점: 사업 양도는 해당 사업을 더 이상 육성하지 않을 사업으로 판단했음을 의미한다. "
             "성장성이 낮거나 시장 지위가 약한 사업을 정리하여 그 자금을 유망 사업에 재배분하는 전략이다."]
    if sl:
        steps.append(f"양도 사업은 회사 매출액의 {sl:.1f}%를 차지한다. 이 매출이 제외된 뒤 잔존 사업만으로 성장할 수 있는지를 검토해야 한다.")
    purpose = _fact(ev, "양도 목적")
    if purpose:
        steps.append(f"양도 목적: '{_short(purpose, 60)}'.")
    steps.append("회계적 영향: 양도가액이 해당 사업의 장부금액을 초과하면 처분이익이 발생하며, 요건을 충족하면 그 사업의 손익은 중단영업으로 구분하여 표시된다.")
    out["steps"] = steps
    cash = fmt_krw(amt) if amt else "현금"
    out["takeaway"] = f"{bsn}{_eul(bsn)} 정리하여 {cash}{'의 현금' if amt else ''}을 확보하는 결정이다. 잔존 사업의 성장성과 매각 대금의 활용이 핵심 쟁점이다."


def _asset_acq(ev, out: dict) -> None:
    me = subject(ev)
    name = _short(_raw(ev, "ast_nm") or _raw(ev, "ast_sen") or "설비", 40)
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {name}{_eul(name)} {fmt_krw(amt) + '에 ' if amt else ''}취득한다."
    purpose = " ".join(filter(None, [_fact(ev, "양수 목적"), _fact(ev, "양수 영향")]))
    q = _short(_fact(ev, "양수 목적") or purpose, 40)
    production = any(w in purpose for w in ("생산", "증설", "캐파", "CAPA", "생산능력", "공장", "라인"))
    office = any(w in purpose for w in ("사옥", "본사", "사무", "업무용"))
    if production:
        first = ("규모의 경제: 생산 설비를 확충하여 생산량이 늘면 제품 단위당 고정비(설비 원가, 감가상각비)가 감소한다. "
                 f"공시된 목적('{q}')이 생산능력 확대이므로 이 논리가 적용된다.")
    elif office:
        first = f"취득의 성격: 사옥 등 업무용 자산의 취득은 규모의 경제보다는 임차료 절감이나 자산 보유 목적으로 해석된다(공시된 목적: '{q}')."
    else:
        first = "규모의 경제: 생산 설비를 확충하여 생산량이 늘면 제품 단위당 고정비(설비 원가, 감가상각비)가 감소한다."
    steps = [first]
    if amt:
        steps.append(breakeven_line(ev, amt, "신규 설비에서"))
    steps.append("가동률의 중요성: 설비를 충분히 가동하지 못하면 고정비만 증가하여 오히려 이익이 감소한다. 따라서 새 설비를 채울 수요(수주)가 확보되어 있는지가 핵심이다.")
    out["steps"] = steps
    if office:
        out["takeaway"] = "현금을 부동산·설비로 전환하는 결정이다. 해당 자산이 비용 절감이나 가치 보전에 기여하는지가 핵심 쟁점이다."
    else:
        out["takeaway"] = "현금을 생산 설비로 전환하여 생산능력을 확대하는 결정이다. 늘어난 고정비를 감당할 만큼 판매량을 확보할 수 있는지가 핵심 쟁점이다."


def _asset_trf(ev, out: dict) -> None:
    me = subject(ev)
    name = _short(_raw(ev, "ast_nm") or _raw(ev, "ast_sen") or "자산", 40)
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {name}{_eul(name)} {fmt_krw(amt) + '에 ' if amt else ''}매각한다."
    purpose = _fact(ev, "양도 목적") or ""
    effect = _fact(ev, "양도 영향") or ""
    both = purpose + " " + effect
    if any(w in both for w in ("재임차", "임차", "리스백", "임대차")):
        out["plain"] += " 매각 후 다시 임차하여 사용하는 세일 앤 리스백(sale and leaseback)이라면, 자산을 계속 사용하면서 현금을 먼저 확보하는 효과가 있다."
    fin = ev.fin or {}
    liab, eq, oi = fin.get("liabilities"), fin.get("equity"), fin.get("operating_income")
    if out["size"] and amt and eq and eq > 0:
        out["size"] = out["size"].replace("에 해당한다.", f", 자기자본의 {share_words(amt, eq)}에 해당한다.", 1)
    steps = ["자본구조 이론의 관점: 자본구조 이론은 부채와 자기자본의 구성 비율이 기업의 위험과 가치에 영향을 미친다고 본다. "
             "부채 비중이 높을수록 이자 부담과 재무적 곤경의 위험이 커진다."]
    repay = any(w in both for w in ("차입금", "부채", "재무구조", "상환"))
    if amt and liab and eq and eq > 0 and repay:
        before = liab / eq * 100
        after = max(liab - amt, 0) / eq * 100
        steps.append(f"부채비율의 변화: 매각 대금을 전액 부채 상환에 사용하면 부채비율(부채÷자기자본)은 {before:.0f}%에서 약 {after:.0f}%로 하락한다"
                     "(처분손익은 제외한 단순 계산).")
    if amt and repay:
        saving = amt * ASSUMED_RATE
        line = f"이자비용 절감: {fmt_krw(amt)}의 부채를 상환하면 연 5%의 금리를 가정할 때 연간 이자비용이 약 {fmt_krw(saving)} 감소한다."
        if oi and oi > 0:
            line += f" 이는 연간 영업이익({fmt_krw(oi)})의 {share_words(saving, oi)}에 해당한다."
        steps.append(line)
    if effect:
        steps.append(f"기회비용: 매각으로 해당 자산에서 발생하던 수익(임대료 등)이나 사용 가치는 사라진다. 공시에는 그 영향이 '{_short(effect, 70)}'라고 기재되어 있다.")
    elif purpose:
        steps.append(f"양도 목적: '{_short(purpose, 60)}'.")
    out["steps"] = steps
    portion = share_words(_fact_pct(ev, "자산총액 대비"), 100) if _fact_pct(ev, "자산총액 대비") else None
    head = f"회사 총자산의 {portion}에 해당하는 자산을 " if portion else "자산을 "
    if repay:
        out["takeaway"] = f"{head}현금으로 전환하여 부채를 줄이는 결정이다. 절감되는 이자비용과 포기하는 자산의 효용을 비교하는 것이 분석의 핵심이다."
    else:
        out["takeaway"] = f"{head}현금으로 전환하는 결정이다. 매각 대금의 활용 방안이 핵심 쟁점이다."


def _merger(ev, out: dict) -> None:
    me = subject(ev)
    partner = clean_name(_raw(ev, "mgptncmp_cmpnm")) or "상대 회사"
    biz = _raw(ev, "mgptncmp_mbsn")
    form = _raw(ev, "mg_stn")
    who = f"{partner}({biz})" if biz else partner
    out["what"] = f"{me}{_i(me)} {who}{josa(partner, '과', '와')} 합병한다{f'({form})' if form else ''}."
    rl = _raw(ev, "mgptncmp_rl_cmpn")
    group = any(w in rl for w in ("계열", "자회사", "종속", "특수관계", "최대주주"))
    if group:
        out["plain"] += " 동일 기업집단 내의 합병은 시너지보다 지배구조 정리나 중복 비용 절감을 목적으로 하는 경우가 많다."
    fin = ev.fin or {}
    o_ast, o_rev, o_ni = _raw_num(ev, "rbsnfdtl_tast"), _raw_num(ev, "rbsnfdtl_sl"), _raw_num(ev, "rbsnfdtl_nic")
    parts = []
    if o_ast and fin.get("assets"):
        parts.append(f"총자산({fmt_krw(o_ast)})은 당사의 {share_words(o_ast, fin['assets'])}")
    if o_rev and fin.get("revenue"):
        parts.append(f"매출액({fmt_krw(o_rev)})은 당사의 {share_words(o_rev, fin['revenue'])}")
    out["size"] = ("합병 상대 회사의 " + ", ".join(parts) + "이다.") if parts else None
    if o_ni is not None and o_ni < 0 and out["size"]:
        out["size"] += f" 상대 회사는 직전 사업연도에 당기순손실({fmt_krw(-o_ni)})을 기록하였다."
    steps = []
    ratio = _raw(ev, "mg_rt")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", ratio.replace(",", ""))][:2] if ratio else []
    if len(nums) == 2 and nums[0] > 0:
        per = f"{nums[1] / nums[0]:.4f}".rstrip("0").rstrip(".")
        steps.append(f"합병비율({nums[0]:g} : {float(per):g}): 소멸회사 주식 1주당 존속회사 주식 {per}주를 교부한다는 의미이다. "
                     "합병비율이 어느 한쪽에 유리하게 정해지면 다른 쪽 주주가 손실을 입으므로, 두 회사의 가치평가 방법이 핵심이다.")
    elif ratio:
        steps.append(f"합병비율({_short(ratio, 30)}): 소멸회사 주식 1주당 존속회사 주식을 몇 주 교부하는지를 정한 것이다. "
                     "합병비율이 어느 한쪽에 유리하게 정해지면 다른 쪽 주주가 손실을 입는다.")
    line = synergy_kind_line(_fact(ev, "합병 목적"), "합병")
    if line:
        steps.append(line)
    if group:
        ev_name = _raw(ev, "exevl_intn")
        steps.append(f"공정성: 동일 기업집단 내 합병에서는 인수 프리미엄보다 합병비율의 공정성이 핵심 쟁점이다"
                     f"{f'(외부평가기관: {_short(ev_name, 20)})' if ev_name else ''}.")
    else:
        steps.append("시너지의 원천: 독립 기업 간 합병에서는 본사·영업망·구매 등 중복 비용의 제거가 시너지의 출발점이 된다.")
        rel = relatedness(ev, biz)
        if rel:
            steps.append(rel)
    out["steps"] = steps
    out["takeaway"] = (f"{partner}{josa(partner, '과', '와')}의 합병으로 두 회사를 하나로 통합하는 결정이다. "
                       + ("합병비율이 양측 주주에게 공정하게 산정되었는지가 핵심 쟁점이다." if group
                          else "결합으로 창출되는 시너지가 지급한 대가를 상회하는지가 핵심 쟁점이다."))


def _split(ev, out: dict) -> None:
    me = subject(ev)
    mth = _raw(ev, "dv_mth")
    new_co = clean_name(_raw(ev, "dvfcmp_cmpnm")) or "신설회사"
    biz = _raw(ev, "dvfcmp_mbsn")
    physical = "물적" in mth
    personal = "인적" in mth
    kind = "물적분할" if physical else "인적분할" if personal else "분할"
    out["what"] = f"{me}{_i(me)} {biz + ' ' if biz else ''}사업을 분리하여 {new_co}{_eul(new_co)} 신설한다({kind})."
    if physical:
        out["plain"] += (" 물적분할은 신설회사의 주식을 분할회사가 100% 보유하는 방식이다. 분할 직후 주주의 지위에는 변화가 없으나, "
                         "이후 신설회사가 별도로 상장되면 기존 주주의 지분 가치가 희석될 수 있다.")
    elif personal:
        out["plain"] += " 인적분할은 기존 주주가 지분율에 따라 신설회사의 주식을 배정받는 방식으로, 하나의 회사 주식이 두 회사의 주식으로 나뉜다."
    new_rev, rest_rev = _raw_num(ev, "dvfcmp_nbsn_rsl"), _raw_num(ev, "atdv_excmp_exbsn_rsl")
    total = (new_rev or 0) + (rest_rev or 0) if new_rev and rest_rev else (ev.fin or {}).get("revenue")
    if new_rev and total:
        out["size"] = f"분리되는 사업의 매출액({fmt_krw(new_rev)})은 분할 전 매출액의 {share_words(new_rev, total)}에 해당한다."
    steps = ["복합기업 할인: 성격이 다른 여러 사업을 한 회사가 영위하면 시장이 각 사업의 가치를 제대로 반영하지 못해, 기업가치가 사업별 가치의 합보다 "
             "낮게 평가되는 경향이 있다. 회사분할은 이러한 할인을 해소하기 위한 수단이다."]
    if physical:
        relist = _raw(ev, "dvfcmp_rlst_atn")
        steps.append("주주가치의 희석: 물적분할 후 신설회사를 상장하면 모회사 주주는 신설회사 주식을 직접 보유하지 못하므로, 신설회사의 가치가 새로 유입되는 주주와 "
                     "나뉜다(이른바 '쪼개기 상장' 논란)." + (f" 공시상 신설회사의 재상장 계획은 '{_short(relist, 20)}'이다." if relist else ""))
    elif personal:
        steps.append("지배구조의 변화: 인적분할은 지주회사 체제로 전환하는 첫 단계로 활용되는 경우가 많으며, 이 과정에서 지배주주의 지배력이 강화된다는 비판이 제기된다.")
    steps.append("주주 보호: 분할에 반대하는 주주가 회사에 공정한 가격으로 주식의 매수를 청구할 수 있는지(주식매수청구권)도 검토해야 한다.")
    out["steps"] = steps
    out["takeaway"] = f"{biz or '일부'} 사업을 분리하여 사업별로 가치를 평가받으려는 결정이다. 기존 주주의 이익이 보호되는지가 핵심 쟁점이다."


def _rights(ev, out: dict) -> None:
    me = subject(ev)
    prefix = "piic_" if ev.rule.key == "rights_bonus" else ""
    new = _raw_num(ev, f"{prefix}nstk_ostk_cnt")
    before = _raw_num(ev, f"{prefix}bfic_tisstk_ostk")
    method = _raw(ev, f"{prefix}ic_mthn")
    amt = ev.amount
    shares = f"신주 {new:,.0f}주를" if new else "신주를"
    money = f"{fmt_krw(amt)}{_eul(fmt_krw(amt))}" if amt else "자금을"
    out["what"] = f"{me}{_i(me)} {shares} 발행하여 {money} 조달한다{f'({method})' if method else ''}."
    steps = ["신호이론: 기업 내부 정보는 경영자가 외부 투자자보다 많이 보유한다(정보 비대칭). 따라서 신주 발행은 경영자가 현재 주가를 고평가 상태로 "
             "판단한다는 신호로 해석되어, 유상증자 발표 후 주가가 하락하는 경우가 많다."]
    if new and before:
        d = new / before
        out["size"] = (f"신주는 기존 발행주식 수의 {d * 100:.1f}%에 해당한다. 유상증자에 참여하지 않는 주주의 지분율은 1%에서 약 {1 / (1 + d):.2f}%로 낮아진다."
                       + (f" {out['size']}" if out["size"] else ""))
    if amt:
        d = ev.detail or {}
        use = {k: parse_amount(d.get(f"{prefix}{k}")) or 0 for k in ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc")}
        survive = use["fdpp_op"] + use["fdpp_dtrp"]
        grow = use["fdpp_fclt"] + use["fdpp_bsninh"] + use["fdpp_ocsa"]
        if survive / amt >= 0.5:
            steps.append(f"자금 용도: 조달 자금의 {survive / amt * 100:.0f}%가 운영자금과 채무상환자금이다. 이는 성장 투자보다 유동성 보강을 위한 증자로 해석될 여지가 크며, "
                         "시장에는 부정적 신호로 작용하기 쉽다.")
        elif grow / amt >= 0.5:
            steps.append(f"자금 용도: 조달 자금의 {grow / amt * 100:.0f}%가 시설투자와 타법인 취득 자금이다. 이는 성장 투자를 위한 증자로 해석될 여지가 있다.")
    if "제3자" in method:
        steps.append("발행 방식: 특정인에게 신주를 배정하는 제3자배정 방식이므로 인수자가 누구인지가 신호의 성격을 좌우한다. "
                     "기업 정보를 잘 아는 전략적 투자자의 참여는 긍정적 신호가 될 수 있다.")
    elif "주주배정" in method:
        steps.append("발행 방식: 기존 주주에게 지분율에 따라 신주 인수 기회를 부여하는 주주배정 방식이므로, 청약에 참여하는 주주는 지분율을 유지할 수 있다.")
    elif "공모" in method:
        steps.append("발행 방식: 불특정 다수를 대상으로 하는 일반공모 방식이므로, 청약을 유도하기 위해 발행가 할인 폭이 커질 수 있다.")
    out["steps"] = steps
    out["takeaway"] = "주주로부터 자금을 추가로 조달하는 결정이다. 조달 자금이 성장 투자에 쓰이는지 유동성 보강에 쓰이는지가 신호의 방향을 결정한다."


def _bonus(ev, out: dict) -> None:
    me = subject(ev)
    per = parse_amount(_raw(ev, "nstk_ascnt_ps_ostk"))
    out["what"] = f"{me}{_i(me)} 주주에게{f' 1주당 {per:g}주의' if per else ''} 신주를 무상으로 배정한다."
    if per:
        out["size"] = f"발행주식 수가 {1 + per:g}배가 되므로, 이론상 주가는 기존의 약 {100 / (1 + per):.0f}% 수준으로 조정된다(권리락)."
    out["steps"] = [
        "행동경제학: 투자자는 주식 수가 늘고 주가가 낮아지면 주식이 '저렴해졌다'고 인식하는 경향이 있다. 이 때문에 기업가치에 변화가 없음에도 "
        "무상증자 발표 후 주가가 상승하는 현상이 자주 관찰된다.",
        "회계적 실질: 무상증자는 자본잉여금 등을 자본금으로 대체하는 것에 불과하여 자본총계는 변하지 않는다.",
        "실질적 효과: 유통 주식 수가 증가하여 거래가 용이해지는 유동성 개선 효과에 그친다.",
    ]
    out["takeaway"] = "기업가치에는 변화가 없는 주식 분할 성격의 결정이다. 발표 후의 주가 상승은 투자자 심리에 기인한 부분일 수 있다."


def _reduction(ev, out: dict) -> None:
    me = subject(ev)
    ratio = _raw(ev, "cr_rt_ostk")
    mth = _raw(ev, "cr_mth") + " " + (_fact(ev, "감자 사유") or "")
    free = "무상" in mth or "결손" in mth
    out["what"] = f"{me}{_i(me)} 자본금을 감소시킨다{f'(감자비율 {_short(ratio, 20)})' if ratio else ''}."
    if free:
        out["steps"] = [
            "무상감자: 주식 수를 줄여 누적 결손금을 자본금으로 보전하는 것이다. 주주는 대가를 받지 못하고 보유 주식 수만 감소한다.",
            "자본구조의 관점: 누적 손실로 자본이 잠식된 상태를 정리하는 절차이며, 이후 신규 자금을 투입하는 유상증자가 뒤따르는 경우가 많다.",
        ]
        out["takeaway"] = "누적 결손을 장부상 정리하는 결정이다. 후속 자본 확충이 이루어지는지가 핵심 쟁점이다."
    else:
        out["steps"] = ["유상감자: 주식 수를 줄이면서 주주에게 자금을 반환하는 것이다. 잉여 현금을 주주에게 돌려주는 주주환원이 될 수도 있으나, "
                        "지배주주의 자금 회수 수단으로 활용될 수도 있다."]
        out["takeaway"] = "자본을 감소시켜 주주에게 자금을 반환하는 결정이다. 반환 자금이 누구에게 귀속되는지가 핵심 쟁점이다."


def _treasury(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    key = ev.rule.key
    fin = ev.fin or {}
    if key == "treasury_trust":
        out["what"] = f"{me}{_i(me)} 증권회사와 {fmt_krw(amt) + ' 규모의 ' if amt else ''}자기주식 취득 신탁계약을 체결한다."
    elif key == "treasury_buy":
        out["what"] = f"{me}{_i(me)} {fmt_krw(amt) + ' 규모의 ' if amt else ''}자기주식을 취득한다."
    elif key == "treasury_cancel":
        out["what"] = f"{me}{_i(me)} 보유한 자기주식을 소각한다."
    ni = fin.get("net_income")
    if amt and ni and ni > 0:
        extra = f"이는 {_year(ev)}당기순이익({fmt_krw(ni)})의 {share_words(amt, ni)}에 해당한다."
        out["size"] = (out["size"] + " " + extra) if out["size"] else extra
    purpose = _fact(ev, "취득 목적", "계약 목적") or ""
    steps = ["배당정책 이론의 관점: 이익을 주주에게 환원하는 방법은 배당과 자기주식 취득이다. 자기주식 취득은 매도를 원하는 주주에게만 현금을 지급하고, "
             "계속 보유하는 주주의 지분율을 높이는 방식이다."]
    if key == "treasury_cancel" or "소각" in purpose:
        steps.append("소각 여부: 취득한 주식을 소각하면 발행주식 수가 실제로 감소하여 주당순이익(EPS)이 증가하고, 이는 주가에 직접적인 영향을 미친다.")
    else:
        steps.append("소각 여부: 취득 목적에 소각이 명시되지 않으면 향후 재매각될 수 있어 주주환원 효과가 제한적이다. "
                     "2026년 3월부터는 취득한 자기주식을 원칙적으로 1년 이내에 소각해야 한다.")
    steps.append("신호 효과: 자기주식 취득은 경영진이 현재 주가를 저평가로 판단한다는 신호로 해석된다. 다만 다른 투자 대안보다 자기주식 취득을 택했다는 것은 "
                 "성장 기회가 제한적이라는 의미일 수도 있다.")
    out["steps"] = steps
    out["takeaway"] = "이익을 자기주식 취득으로 주주에게 환원하는 결정이다. 실제 소각으로 이어지는지가 핵심 쟁점이다."


def _treasury_sell(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} 보유한 자기주식을 {fmt_krw(amt) + ' 규모로 ' if amt else ''}처분한다."
    purpose = _fact(ev, "처분 목적") or ""
    steps = ["신호이론: 회사가 자기주식을 매각하는 것은 경영진이 현재 주가를 충분히 높다고 판단한다는 신호로 해석될 수 있다."]
    if any(w in purpose for w in ("임직원", "상여", "보상", "성과")):
        steps.append(f"처분 목적('{_short(purpose, 40)}')으로 볼 때 임직원 보상을 위한 처분이므로, 시장 매도 물량에 따른 부담은 크지 않을 수 있다.")
    elif any(w in purpose for w in ("교환사채", "EB")):
        steps.append("교환사채의 교환 대상으로 활용하는 처분이므로, 실질적으로는 자기주식을 담보로 자금을 조달하는 것과 유사하다.")
    elif purpose:
        steps.append(f"처분 목적: '{_short(purpose, 60)}'.")
    steps.append("희석 효과: 자기주식이 다시 유통되면 유통 주식 수가 증가하여 주당 가치가 희석되며, 우호 세력에 매각될 경우 경영권 방어 수단으로 기능하기도 한다.")
    out["steps"] = steps
    out["takeaway"] = "보유 자기주식을 현금화하거나 다른 목적에 활용하는 결정이다. 처분 상대방과 목적이 핵심 쟁점이다."


def _mezzanine(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    names = {"cb": "전환사채", "bw": "신주인수권부사채", "eb": "교환사채"}
    nm = names.get(ev.rule.key, "사채")
    out["what"] = f"{me}{_i(me)} {fmt_krw(amt) + ' 규모의 ' if amt else ''}{nm}{_eul(nm)} 발행한다."
    price = parse_amount(_raw(ev, "cv_prc") or _raw(ev, "ex_prc"))
    if price:
        label = {"cb": "전환가액", "bw": "행사가액", "eb": "교환가액"}.get(ev.rule.key, "전환가액")
        out["plain"] += f" 이번 발행의 {label}은 1주당 {price:,.0f}원이다."
    vs = _raw_pct(ev, "cvisstk_tisstk_vs") or _raw_pct(ev, "nstk_isstk_tisstk_vs") or _raw_pct(ev, "extg_tisstk_vs")
    if vs:
        out["size"] = (f"전부 주식으로 전환되면 현재 발행주식 수의 {vs:.1f}%에 해당하는 주식이 새로 발행되거나 이전된다(잠재적 희석)."
                       + (f" {out['size']}" if out["size"] else ""))
    coupon = parse_amount(_raw(ev, "bd_intr_ex"))
    steps = ["자본구조의 관점: 메자닌 증권은 부채(이자 부담)와 자기자본(지분 희석)의 중간적 성격을 지닌다. 주가가 상승하면 부채가 주식으로 전환되어 상환 부담이 "
             "사라지고, 주가가 오르지 않으면 만기에 부채로 상환해야 한다."]
    if coupon is not None:
        if coupon == 0:
            steps.append("표면이자율: 0%이므로 투자자는 이자 수익이 아니라 주가 상승에 따른 전환 차익을 기대하고 투자한다.")
        else:
            steps.append(f"표면이자율: {coupon:g}%로 일반 회사채보다 낮은 이자를 부담하는 대신, 투자자에게 주식으로 전환할 수 있는 권리를 부여한다.")
    floor = parse_amount(_raw(ev, "act_mktprcfl_cvprc_lwtrsprc"))
    if floor:
        steps.append(f"리픽싱(전환가액 조정): 주가가 하락하면 전환가액을 최저 {floor:,.0f}원까지 낮출 수 있어, 그만큼 발행될 주식 수가 늘고 희석 효과가 커질 수 있다.")
    if "사모" in _raw(ev, "bdis_mthn"):
        steps.append("발행 방식: 소수의 투자자를 대상으로 하는 사모 방식이다. 일반 회사채 발행이 어려운 기업이 주로 활용하므로, 시장은 이를 재무적 여력이 "
                     "부족하다는 신호로 받아들이기도 한다.")
    out["steps"] = steps
    out["takeaway"] = f"낮은 이자로 자금을 조달하는 대신 미래의 지분을 내주는 {nm} 발행 결정이다. 주가 하락 시 희석 규모가 얼마나 커지는지가 핵심 쟁점이다."


def _ipo(ev, out: dict) -> None:
    price = _num(_fact(ev, "공모가(모집가액)"))
    count = _num(_fact(ev, "공모 주식 수"))
    amt = ev.amount
    name = ev.corp_name
    bits = []
    if count:
        bits.append(f"주식 {count:,.0f}주를")
    if price:
        bits.append(f"1주당 {price:,.0f}원에 공모하여")
    elif bits:
        bits.append("공모하여")
    money = f"{fmt_krw(amt)}{_eul(fmt_krw(amt))} 조달하고" if amt else "자금을 조달하고"
    out["what"] = f"{name}{_i(name)} {' '.join(bits) + ' ' if bits else ''}{money} 증권시장에 상장할 예정이다."
    steps = ["IPO 저평가 현상: 신규 상장 주식의 공모가는 시장에서 형성될 가격보다 낮게 결정되는 경향이 있다. 이는 정보가 부족한 투자자의 참여를 유도하고 "
             "공모 실패 위험을 줄이기 위한 할인으로 설명된다."]
    if price:
        steps.append(f"이 때문에 상장 첫날 주가가 공모가를 상회하는 경우가 많으며, 상장일 종가와 공모가 {price:,.0f}원의 차이가 저평가의 크기를 나타낸다.")
    steps.append("공모가 결정 과정: 공모가는 기관투자자를 대상으로 한 수요예측을 통해 결정된다. 공모가가 희망 범위의 상단에서 결정될수록, 그리고 기관투자자의 "
                 "의무보유확약 비율이 높을수록 시장의 기대가 크다고 해석된다.")
    out["steps"] = steps
    out["takeaway"] = "기업이 처음으로 시장에서 가치를 평가받는 결정이다. 공모가가 내재가치에 비해 적정한지, 상장 후 출회될 유통 물량이 과도하지 않은지가 핵심 쟁점이다."


def _earnings(ev, out: dict) -> None:
    me = subject(ev)
    out["what"] = f"{me}{_i(me)} 영업실적(또는 실적 변동)을 공시하였다."
    fin = ev.fin or {}
    rev, rev_p, oi, oi_p = fin.get("revenue"), fin.get("revenue_prev"), fin.get("operating_income"), fin.get("operating_income_prev")
    steps = ["영업레버리지: 고정비(임차료·감가상각비·인건비 등)의 비중이 높은 기업은 매출액이 조금만 변해도 영업이익이 크게 변동한다."]
    if rev and rev_p and oi and oi_p and oi_p > 0 and rev_p > 0:
        g_rev = (rev / rev_p - 1) * 100
        g_oi = (oi / oi_p - 1) * 100
        line = f"이 회사의 {_year(ev)}실적을 보면 매출액이 {g_rev:+.1f}% 변할 때 영업이익은 {g_oi:+.1f}% 변하였다."
        if abs(g_rev) >= 1 and abs(g_oi) > abs(g_rev) * 1.5:
            line += f" 영업이익 변동률이 매출액 변동률의 {abs(g_oi / g_rev):.1f}배이므로 영업레버리지가 높은 구조로 판단된다."
        steps.append(line)
    steps.append("이번 공시의 매출액·영업이익 변동률을 같은 방식으로 비교하면, 실적 변화가 판매량에 기인한 것인지 비용 구조에 기인한 것인지 판단할 수 있다.")
    out["steps"] = steps
    out["takeaway"] = "실적의 큰 변동을 알리는 공시이다. 매출액 변동에 비해 이익 변동이 얼마나 큰지가 그 기업의 비용 구조를 보여 준다."


def _generic(ev, out: dict, lens: dict | None) -> None:
    me = subject(ev)
    out["what"] = f"{me}{_i(me)} '{ev.rule.label}' 공시를 제출하였다."
    if ev.amount:
        label = ev.amount_label or "금액"
        out["what"] += f" {label}{_eun(label)} {fmt_krw(ev.amount)}이다."
    if lens and lens.get("watch"):
        out["steps"] = [f"{lens['title']}의 관점: {lens['watch']}"]
    out["takeaway"] = ""


HANDLERS = {
    "stock_acq": _stock_acq, "stock_trf": _stock_trf, "business_acq": _business_acq, "business_trf": _business_trf,
    "asset_acq": _asset_acq, "asset_trf": _asset_trf, "merger": _merger, "split": _split,
    "rights_offering": _rights, "rights_bonus": _rights, "bonus_issue": _bonus, "capital_reduction": _reduction,
    "treasury_buy": _treasury, "treasury_trust": _treasury, "treasury_cancel": _treasury, "treasury_sell": _treasury_sell,
    "cb": _mezzanine, "bw": _mezzanine, "eb": _mezzanine, "ipo": _ipo, "earnings": _earnings,
}


def explain_filing(ev, lens: dict | None = None) -> dict:
    """공시 사례 하나 → {'what', 'plain', 'size', 'lens', 'steps', 'takeaway'}. 실패해도 노트 전체를 막지 않는다."""
    out = _base(ev)
    handler = HANDLERS.get(ev.rule.key)
    try:
        if handler:
            handler(ev, out)
        else:
            _generic(ev, out, lens)
    except (TypeError, ValueError, ZeroDivisionError, AttributeError):
        out = _base(ev)
        _generic(ev, out, lens)
    if not out.get("what"):
        _generic(ev, out, lens)
    if ev.is_correction:
        out["what"] += " (앞서 제출한 공시를 정정한 공시이다.)"
    out["lens"] = lens
    out["steps"] = [s for s in out.get("steps") or [] if s]
    return out


# ------------------------------------------------------------------ 뉴스
_LEAD_PATTERNS = [
    re.compile(r"^\s*[\(\[【〈<][^\)\]】〉>]{0,40}[\)\]】〉>]\s*"),
    re.compile(r"^[가-힣A-Za-z·\s]{2,20}?(기자|특파원|통신원|객원기자)\s*=\s*"),
    re.compile(r"^[가-힣]{2,4}\s*(기자|특파원)\s+"),
]

_NUM = re.compile(
    r"(\d[\d,]*(?:\.\d+)?\s?(?:조|억|만|천)?\s?(?:원|달러|유로|엔|위안|%|％|명|건|배|가구|톤|bp|포인트)(?:대|어치)?)"
    r"(?:\s?([가-힣A-Za-z]{2,8}))?"
)


def lead_sentence(summary, title: str = "") -> str:
    """기사 요약에서 '(평택=연합뉴스) 홍길동 기자 =' 같은 머리말을 떼고 첫 문장만."""
    s = clean_text(summary)
    for _ in range(3):
        for pat in _LEAD_PATTERNS:
            s = pat.sub("", s, count=1).strip()
    m = re.match(r"(.+?(?:다|요|음|함)\.)(\s|$)", s)
    if m:
        s = m.group(1)
    elif re.search(r"다$", s):
        s += "."
    else:
        s = _close_clause(s)  # 요약이 문장 중간에서 잘렸다
    if len(s) < 15 or re.sub(r"\W", "", s) == re.sub(r"\W", "", title or ""):
        return ""
    return s if len(s) <= 200 else s[:199].rstrip() + "…"


_CLAUSE_END = re.compile(r"(했|됐|였|었|았|있|없)(?:고|으며),|(하|되)(?:고|며),")


def _close_clause(s: str) -> str:
    """'…수요예측을 진행하고, 엠비디가...'처럼 잘린 요약에서 마지막으로 끝난 절을 찾아
    '…수요예측을 진행한다.'로 닫는다. 닫을 절이 없으면 빈 문자열."""
    last = None
    for m in _CLAUSE_END.finditer(s):
        last = m
    if last is None:
        return ""
    head = s[:last.start()]
    if last.group(1):
        return f"{head}{last.group(1)}다."
    return head + ("한다." if last.group(2) == "하" else "된다.")


_JOSA_TAIL = re.compile(r"(에서|으로|을|를|이|가|은|는|의|에|로|와|과|도|만)$")


def number_phrases(text, limit: int = 3) -> list[str]:
    """'4조원대 본예산안'처럼 숫자와 바로 뒤 낱말을 묶어 뽑는다. 같은 숫자는 한 번만."""
    out: list[str] = []
    nums: set[str] = set()
    for m in _NUM.finditer(clean_text(text)):
        num = m.group(1).replace(" ", "")
        if num in nums:
            continue
        nums.add(num)
        word = m.group(2) or ""
        if len(word) > 2:
            word = _JOSA_TAIL.sub("", word)
        out.append(f"{num} {word}".strip())
        if len(out) >= limit:
            break
    return out


def explain_news(nc: dict, why: str | None = None) -> dict:
    item = nc["item"]
    card = nc["theory"]
    what = lead_sentence(getattr(item, "summary", ""), item.title)
    return {
        "what": what,
        "why": why,
        "numbers": number_phrases(f"{getattr(item, 'summary', '') or ''} {item.title}"),
        "watch": card.get("watch"),
        "text": f"{item.title} {getattr(item, 'summary', '') or ''}",
    }


def apply_cues(text: str, cues, limit: int = 2) -> tuple[list[str], list[str]]:
    """이론 카드의 단서(정규식)를 기사 제목·요약에서 찾아, 그 기사에 이론을 대입한 문장을 만든다.
    돌려주는 값: (문장들, 찾은 말들)."""
    lines: list[str] = []
    words: list[str] = []
    for pair in cues or []:
        try:
            pat, say = pair
            m = re.search(pat, text or "")
        except (ValueError, re.error):
            continue
        if not m:
            continue
        w = m.group(0)
        b = _base_word(w)
        line = say.format(m=w, m_eun=josa(b, "은", "는"), m_i=josa(b, "이", "가"),
                          m_eul=josa(b, "을", "를"), m_gwa=josa(b, "과", "와"))
        if line in lines:
            continue
        lines.append(line)
        words.append(w)
        if len(lines) >= limit:
            break
    return lines, words


# ------------------------------------------------------------------ 용어 풀이
def _keys(entry: dict) -> list[str]:
    return [entry["term"]] + list(entry.get("also") or [])


def glossary_hits(text: str, glossary: list[dict], news: bool = False) -> list[dict]:
    """글에 나온 용어를 찾는다. 긴 표현을 먼저 맞추고 그 자리는 지워 '지분법' 안의 '지분'처럼 겹치지 않게 한다.
    news=True면 뉴스에서 다른 뜻으로 자주 쓰이는 말(채소 '감자', 쓰레기 '소각')은 건너뛴다."""
    t = str(text or "")
    found: list[tuple[int, dict]] = []
    entries = [e for e in glossary if not (news and e.get("news") is False)]
    pairs = sorted(((k, e) for e in entries for k in _keys(e)), key=lambda p: -len(p[0]))
    taken: set[str] = set()
    for key, entry in pairs:
        if entry["term"] in taken or not key:
            continue
        if re.fullmatch(r"[A-Za-z0-9&]+", key):
            m = re.search(rf"(?<![A-Za-z]){re.escape(key)}(?![A-Za-z])", t)
        else:
            m = re.search(re.escape(key), t)
        if not m:
            continue
        found.append((m.start(), entry))
        taken.add(entry["term"])
        t = t[: m.start()] + " " * len(key) + t[m.end():]
    return [e for _, e in sorted(found, key=lambda p: p[0])]


def pick_terms(text: str, glossary: list[dict], seen: set[str], limit: int = 4, news: bool = False) -> list[dict]:
    """노트에서 처음 나오는 용어만 골라 준다(같은 용어를 사례마다 반복하지 않게)."""
    out = []
    for e in glossary_hits(text, glossary, news=news):
        if e["term"] in seen:
            continue
        out.append(e)
        seen.add(e["term"])
        if len(out) >= limit:
            break
    return out


def pick_signals(text: str, glossary: list[dict], seen: set[str], limit: int = 2, skip_words=()) -> list[dict]:
    """뉴스 제목·요약에 나온 '신호' 용어. 앞에서 풀이했던 용어라도 기사 속 의미는 다시 보여 준다.
    skip_words: 이론 단서로 이미 짚은 말(같은 말을 두 번 풀지 않게)."""
    def overlaps(entry) -> bool:
        return any(k and (k in w or w in k) for k in _keys(entry) for w in skip_words)

    out = [e for e in glossary_hits(text, glossary, news=True) if e.get("signal") and not overlaps(e)][:max(limit, 0)]
    seen.update(e["term"] for e in out)
    return out
