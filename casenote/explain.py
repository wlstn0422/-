"""공시·뉴스 사례를 배경지식 없이도 읽히게 풀고, 이론에 실제 숫자를 넣어 대입한다.

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

# 공시 유형마다 '쉽게 말하면'의 첫 문장
TYPE_PLAIN = {
    "merger": "합병은 두 회사가 하나가 되는 것입니다. 흡수합병이면 한 회사만 남고, 없어지는 회사 주주는 남는 회사 주식을 받습니다.",
    "split_merger": "분할합병은 한 회사의 사업 일부를 떼어 내 다른 회사에 바로 붙이는 것입니다.",
    "split": "분할은 한 회사의 사업 일부를 떼어 새 회사를 만드는 것입니다.",
    "share_exchange": "주식교환·이전은 상대 회사 주주가 가진 주식을 우리 회사 주식과 바꿔, 상대 회사를 100% 자회사로 만드는 방법입니다.",
    "tender_offer": "공개매수는 '언제까지, 얼마에, 몇 주를 사겠다'고 공개하고 시장 밖에서 주식을 사 모으는 것입니다. 보통 시세보다 비싸게 사서 경영권을 확보하거나 상장을 폐지할 때 씁니다.",
    "control_change": "최대주주가 바뀐다는 건 회사의 주인이 바뀐다는 뜻이라, 경영진과 전략이 함께 바뀌는 경우가 많습니다.",
    "stock_acq": "다른 회사 주식을 사서 그 회사의 '공동 주인'이 되는 거래입니다.",
    "stock_trf": "갖고 있던 다른 회사 주식을 팔아 현금으로 바꾸는 거래입니다.",
    "business_acq": "영업양수는 회사 전체가 아니라 특정 사업 부문(사람·설비·거래처)을 통째로 사 오는 것입니다. 원하는 사업만 골라 올 수 있습니다.",
    "business_trf": "영업양도는 회사의 사업 부문 하나를 사람·설비·거래처째 통째로 파는 것입니다.",
    "asset_acq": "유형자산은 땅·건물·기계처럼 오래 쓰는 설비입니다. 사들이면 현금이 설비로 바뀌고, 그 값은 쓰는 동안 매년 감가상각비라는 비용으로 나눠 잡힙니다.",
    "asset_trf": "가진 땅·건물·설비를 팔아 현금으로 바꾸는 거래입니다.",
    "ipo": "IPO(기업공개)는 회사가 처음으로 일반 투자자에게 주식을 팔고 증권시장에 올라가는 것입니다. 그 뒤로는 누구나 이 회사 주식을 사고팔 수 있습니다.",
    "rights_offering": "유상증자는 새 주식을 팔아 돈을 모으는 것입니다. 갚을 필요가 없는 돈이지만, 주식 수가 늘어 기존 주주 한 사람의 몫은 줄어듭니다(희석).",
    "rights_bonus": "유무상증자는 새 주식을 팔아 돈을 모으면서(유상), 동시에 기존 주주에게 새 주식을 공짜로 나눠 주는(무상) 것입니다.",
    "bonus_issue": "무상증자는 돈을 받지 않고 기존 주주에게 새 주식을 나눠 주는 것입니다. 피자를 더 잘게 자른 것과 같아 회사 가치는 그대로이고, 주가는 그만큼 낮아집니다(권리락).",
    "capital_reduction": "감자는 자본금을 줄이는 것입니다. 주식 수를 줄여 장부에 쌓인 손실을 메우거나(무상감자), 주주에게 돈을 돌려줍니다(유상감자).",
    "treasury_trust": "자사주 신탁은 증권사에 돈을 맡겨 정해진 기간 동안 회사 주식을 대신 사들이게 하는 것입니다.",
    "treasury_buy": "자사주 매입은 회사가 시장에서 자기 회사 주식을 사들이는 것입니다. 시장에 도는 주식이 줄어 남은 주주의 몫이 커지고, 사서 없애면(소각) 그 효과가 확실해집니다.",
    "treasury_sell": "자사주 처분은 회사가 갖고 있던 자기 주식을 다시 파는 것입니다. 현금을 마련하거나 직원 보상, 우호 세력에게 넘기는 데 씁니다.",
    "treasury_cancel": "자사주 소각은 회사가 가진 자기 주식을 없애 주식 수를 줄이는 것입니다. 이익이 같아도 주식 수가 줄어 한 주당 몫이 커집니다.",
    "cb": "전환사채는 처음엔 빌린 돈이지만, 투자자가 원하면 정해진 가격에 주식으로 바꿀 수 있는 채권입니다. 회사는 낮은 이자로 돈을 빌리고, 투자자는 주가가 오르면 주식으로 바꿔 차익을 봅니다.",
    "bw": "신주인수권부사채는 빌린 돈(사채)에 '정해진 가격에 새 주식을 살 권리'가 붙은 채권입니다. 이자를 낮게 주는 대신 주가가 오르면 투자자가 싸게 주식을 살 수 있습니다.",
    "eb": "교환사채는 회사가 가진 다른 주식(자사주나 계열사 주식)으로 바꿀 수 있는 채권입니다. 새 주식을 찍지 않고 들고 있던 주식을 내준다는 점이 전환사채와 다릅니다.",
    "valueup": "기업가치 제고(밸류업) 계획은 주가가 회사 가치보다 낮게 평가되는 문제를 풀려고 회사가 내놓는 배당·자사주·수익성 목표입니다.",
    "dividend": "배당은 회사가 번 이익의 일부를 주주에게 현금으로 나눠 주는 것입니다.",
    "earnings": "잠정실적은 회계감사를 받기 전에 먼저 알리는 실적입니다. 실적이 크게 바뀌면 투자자가 빨리 알 수 있게 미리 공시합니다.",
    "contract": "단일판매·공급계약 공시는 매출에 비해 큰 주문을 따냈다는 뜻입니다. 계약 금액이 일정 비율을 넘으면 꼭 알려야 합니다.",
    "insolvency": "부도·회생·영업정지 같은 공시는 회사가 빚을 갚기 어렵거나 사업을 계속하기 어려운 상황이라는 신호입니다.",
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


def _base_word(word: str) -> str:
    """조사는 괄호 앞 낱말에 맞춘다('약 6분의 1(16.5%)' → '약 6분의 1')."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(word or "")) or str(word or "")


def _eul(word: str) -> str:
    return josa(_base_word(word), "을", "를")


def _i(word: str) -> str:
    return josa(_base_word(word), "이", "가")


def _eun(word: str) -> str:
    return josa(_base_word(word), "은", "는")


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
    t = re.sub(r"^\s*\d+[\.\)]\s*", "", t)
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def purpose_kinds(text) -> list[str]:
    t = str(text or "")
    return [kind for kind, words in PURPOSE_KINDS if any(w in t for w in words)]


def funding(ev) -> str | None:
    """대금을 어떻게 마련하는지 쉬운 말로('빚을 내서' 등)."""
    t = " ".join(filter(None, [_raw(ev, "dl_pym"), _fact(ev, "대금 지급 방식") or ""]))
    if not t:
        return None
    own = any(w in t for w in ("자기자금", "자체자금", "자체 자금", "자기 자금", "보유자금", "보유 자금", "보유현금", "보유 현금", "자기자본"))
    loan = "차입" in t or "대출" in t
    if own and loan:
        return "가진 돈과 빌린 돈을 섞어"
    if loan:
        return "빚을 내서"
    if "증자" in t:
        return "새 주식을 팔아 모은 돈으로"
    if "사채" in t:
        return "사채로 빌린 돈으로"
    if own:
        return "가진 돈으로"
    return None


def subject(ev) -> str:
    """'의약품 제조 회사 애드바이오텍'처럼 회사 앞에 업종을 붙인다."""
    name = industry_name(getattr(ev, "induty_code", ""))
    if name and "지주" not in name:
        return f"{name} 회사 {ev.corp_name}"
    return ev.corp_name


def _year(ev) -> str:
    y = (ev.fin or {}).get("year")
    return f"{y}년 " if y else ""


def size_line(ev, amount: float | None = None, what: str | None = None, income_years: bool = True) -> str | None:
    """거래 금액을 회사 재산·매출·이익과 견줘 '얼마나 큰 결정인가'를 한 문장으로.
    income_years: 돈을 쓰는 거래면 '본업 이익 몇 년치'를 붙인다(파는 거래에는 어색해서 뺀다)."""
    amt = amount if amount is not None else ev.amount
    if not amt:
        return None
    fin = ev.fin or {}
    parts: list[str] = []
    assets, revenue, oi = fin.get("assets"), fin.get("revenue"), fin.get("operating_income")
    official = _fact_pct(ev, "총자산 대비", "자산총액 대비")
    if official:
        sw = share_words(official, 100)
        parts.append(f"회사 재산 전부(총자산)의 {sw}")
    elif assets:
        parts.append(f"회사 재산 전부(총자산 {fmt_krw(assets)})의 {share_words(amt, assets)}")
    if revenue:
        parts.append(f"{_year(ev)}매출({fmt_krw(revenue)})의 {share_words(amt, revenue)}")
    if not parts:
        return None
    head = what or fmt_krw(amt)
    line = f"{head}{_eun(head)} " + ", ".join(parts) + "에 해당합니다."
    if oi is not None and oi <= 0:
        line += f" {_year(ev)}본업은 적자(영업손실 {fmt_krw(-oi)})였습니다."
    elif income_years and oi and amt / oi >= 1.5:
        line += f" 본업으로 1년에 버는 이익(영업이익 {fmt_krw(oi)})의 {amt / oi:.1f}년치입니다."
    return line


def breakeven_line(ev, amt: float, why: str = "이 투자로") -> str:
    cost = amt * ASSUMED_RATE
    line = (f"본전 조건: {fmt_krw(amt)}{_eul(fmt_krw(amt))} 연 5% 금리로 빌렸다고 치면(가정) 이자만 매년 {fmt_krw(cost)}입니다. "
            f"{why} 매년 그 이상을 더 벌어야 남는 장사입니다.")
    oi = (ev.fin or {}).get("operating_income")
    if oi and oi > 0:
        line += f" 회사가 본업으로 1년에 버는 이익({fmt_krw(oi)})의 {share_words(cost, oi)} 규모의 부담입니다."
    elif oi is not None and oi <= 0:
        line += " 본업이 적자라 이 부담은 더 무겁습니다."
    return line


def stake_text(p: float | None) -> tuple[str, str] | None:
    """지분율 → (경영상 의미, 회계상 의미)."""
    if p is None:
        return None
    if p > 50:
        return ("회사를 사실상 지배하는 지분(50% 초과)이라 자회사가 됩니다",
                "회계에서는 자회사로 보고 재무제표를 합칩니다(연결). 순자산보다 더 얹어 준 값은 영업권으로 남습니다")
    if p >= 20:
        return ("경영에 목소리를 낼 수 있는 지분(20~50%)입니다",
                "회계에서는 보통 관계회사로 보고, 그 회사 이익 중 내 몫만 내 이익에 더합니다(지분법)")
    return ("경영권(보통 50% 초과)이 없는, 투자에 가까운 지분입니다",
            "회계에서는 보통 투자 주식(금융자산)으로 적고, 값이 오르내리면 평가손익을 반영합니다")


def relatedness(ev, target_text) -> str | None:
    mine = family_of_code(getattr(ev, "induty_code", ""))
    theirs = family_of_text(target_text)
    if not mine or not theirs:
        return None
    if mine == theirs:
        return (f"업종을 견줘 보면 우리 회사와 상대 모두 {mine} 쪽이라, 판매망 공유나 원가 절감 같은 시너지를 "
                "비교적 계산하기 쉽습니다.")
    return (f"업종을 견줘 보면 우리 회사는 {mine}, 상대는 {theirs} 쪽으로 서로 달라 본업의 역량을 그대로 쓰기 어렵습니다. "
            "앤소프 매트릭스로 보면 새 제품·새 시장으로 가는 '다각화'에 가까워 위험이 큰 편입니다.")


def synergy_kind_line(purpose: str | None) -> str | None:
    if not purpose:
        return None
    kinds = purpose_kinds(purpose)
    quote = f"공시에 적힌 목적('{_short(purpose, 50)}')"
    if "revenue" in kinds:
        return f"노리는 시너지: {quote}을 보면 판매를 늘리는 매출 시너지를 노립니다. 매출 시너지는 비용을 줄이는 시너지보다 실현이 불확실한 편입니다."
    if "cost" in kinds:
        return f"노리는 시너지: {quote}을 보면 원가를 줄이는 비용 시너지를 노립니다. 중복 비용을 없애는 것이라 비교적 계산이 쉽고 실현 가능성도 높은 편입니다."
    if "capability" in kinds:
        return f"노리는 시너지: {quote}을 보면 기술이나 인력을 얻으려는 것입니다. 성과가 숫자로 나오기까지 시간이 걸립니다."
    if "financial" in kinds:
        return f"노리는 것: {quote}을 보면 사업 시너지보다 투자 수익이 목적입니다. 이 경우엔 산 값이 싼지 비싼지가 전부입니다."
    if "diversify" in kinds:
        return f"노리는 것: {quote}을 보면 새 사업에 들어가는 다각화입니다. 본업과 멀수록 실패 위험이 커집니다."
    if "control" in kinds:
        return f"노리는 것: {quote}을 보면 경영권이나 지배력을 얻으려는 거래입니다."
    return f"노리는 것: {quote}."


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
    tgt = clean_name(_raw(ev, "iscmp_cmpnm")) or "상대 회사"
    biz = _raw(ev, "iscmp_mbsn")
    after = _raw_pct(ev, "atinh_eqrt")
    amt = ev.amount
    me = subject(ev)
    out["what"] = f"{me}{_i(me)} {tgt}{f'({biz})' if biz else ''} 주식을 {fmt_krw(amt)}에 삽니다." if amt else \
        f"{me}{_i(me)} {tgt}{f'({biz})' if biz else ''} 주식을 삽니다."
    if after is not None:
        out["what"] += f" 사고 나면 지분이 {after:.2f}%가 됩니다."
    st = stake_text(after)
    if st:
        out["plain"] += f" {after:.1f}%는 {st[0]}. {st[1]}."
    fund = funding(ev)
    if out["size"] and fund:
        out["size"] += f" 돈은 {fund} 냅니다."
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
        steps.append(f"회사값으로 바꿔 보면: 이번에 사는 지분 {bought:.1f}%에 {fmt_krw(amt)}{_eul(fmt_krw(amt))} 내니, {tgt} 전체를 약 "
                     f"{fmt_krw(whole)}짜리로 본 가격입니다. 이 값이 그 회사가 1년에 버는 이익의 몇 배인지가 비싼지 싼지의 기준입니다.")
    if amt:
        steps.append(breakeven_line(ev, amt))
    purpose = _fact(ev, "취득 목적")
    line = synergy_kind_line(purpose)
    if line:
        steps.append(line)
    rel = relatedness(ev, biz)
    if rel:
        steps.append(rel)
    if after is not None:
        if after > 50:
            steps.append("경영권: 지분이 절반을 넘어 시너지를 직접 만들 수 있습니다. 대신 실패하면 손실도 그대로 떠안습니다.")
        elif after >= 20:
            steps.append("경영권: 이사회에 목소리를 낼 수는 있지만 마음대로 바꾸긴 어렵습니다. 시너지를 내려면 상대 경영진과의 협력이 필요합니다.")
        else:
            steps.append("경영권: 지분이 20%에 못 미쳐 경영을 직접 바꾸기 어렵습니다. 시너지를 내려면 별도 협력 계약이나 이사 파견이 있는지가 관건입니다.")
    out["steps"] = steps
    ta = (ev.fin or {}).get("assets")
    portion = share_words(_fact_pct(ev, "총자산 대비"), 100) if _fact_pct(ev, "총자산 대비") else share_words(amt, ta)
    head = f"회사 재산의 {portion}{_eul(portion)} " if portion else ""
    key = "경영권 없이 시너지를 낼 수 있느냐" if (after is not None and after <= 50) else "더 얹어 준 값만큼 시너지를 만들 수 있느냐"
    out["takeaway"] = f"{head}{(fund + ' ') if fund else ''}{biz or tgt} 회사 지분{f' {after:.1f}%' if after is not None else ''}에 쓴 결정입니다. {key}가 관건입니다."


def _stock_trf(ev, out: dict) -> None:
    tgt = clean_name(_raw(ev, "iscmp_cmpnm")) or "보유 회사"
    biz = _raw(ev, "iscmp_mbsn")
    after = _raw_pct(ev, "attrf_eqrt")
    me = subject(ev)
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} 갖고 있던 {tgt}{f'({biz})' if biz else ''} 주식을 {fmt_krw(amt) + '에 ' if amt else ''}팝니다."
    if after is not None:
        out["what"] += f" 팔고 나면 지분이 {after:.2f}%가 됩니다."
        if after == 0:
            out["plain"] += " 지분을 모두 팔아 그 회사에서 완전히 손을 뗍니다."
    liab = (ev.fin or {}).get("liabilities")
    if out["size"] and amt and liab:
        out["size"] += f" 이 돈이면 회사 빚(부채 {fmt_krw(liab)})의 {share_words(amt, liab)}를 갚을 수 있습니다."
    steps = ["BCG 매트릭스는 사업을 돈을 벌어 오는 사업, 돈을 넣어 키울 사업, 정리할 사업으로 나눕니다. "
             "판다는 건 이 지분을 '정리하거나 현금으로 바꿀 쪽'으로 봤다는 뜻입니다."]
    purpose = _fact(ev, "처분 목적")
    kinds = purpose_kinds(purpose)
    if "liquidity" in kinds:
        steps.append(f"공시 목적('{_short(purpose, 50)}')을 보면 사업 판단보다 현금 확보가 급한 경우로 보입니다.")
    elif "focus" in kinds:
        steps.append(f"공시 목적('{_short(purpose, 50)}')을 보면 핵심 사업에 집중하려는 정리입니다.")
    elif purpose:
        steps.append(f"공시 목적: '{_short(purpose, 60)}'.")
    steps.append("판 값이 장부에 적힌 값보다 크면 처분이익, 작으면 처분손실이 이번 실적에 잡힙니다. 그리고 판 돈을 어디에 쓰는지(빚 갚기, 새 투자)가 다음 관전 포인트입니다.")
    out["steps"] = steps
    out["takeaway"] = f"{tgt} 지분을 팔아 {fmt_krw(amt) if amt else '현금'}{_eul(fmt_krw(amt)) if amt else '을'} 확보하는 결정입니다. 판 돈을 어디에 쓰는지가 관건입니다."


def _business_acq(ev, out: dict) -> None:
    me = subject(ev)
    bsn = _raw(ev, "inh_bsn") or "사업 부문"
    who = clean_name(_raw(ev, "dlptn_cmpnm"))
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {who + '의 ' if who else ''}{bsn}{_eul(bsn)} {fmt_krw(amt) + '에 ' if amt else ''}통째로 사들입니다."
    sl = _raw_pct(ev, "sl_rt")
    if sl:
        out["what"] += f" 사 오는 사업의 매출은 우리 회사 매출의 {sl:.1f}% 규모입니다."
    steps = []
    if amt:
        steps.append(breakeven_line(ev, amt, "사 온 사업에서"))
    line = synergy_kind_line(_fact(ev, "양수 목적"))
    if line:
        steps.append(line)
    rel = relatedness(ev, bsn + " " + (_fact(ev, "양수 영업의 주요 내용") or ""))
    if rel:
        steps.append(rel)
    rl = _raw(ev, "dlptn_rl_cmpn")
    if any(w in rl for w in ("계열", "특수관계", "최대주주", "자회사", "종속")):
        steps.append(f"파는 쪽이 우리와 특수관계({_short(rl, 20)})라, 값이 공정한지(외부평가)가 특히 중요합니다. 그룹 안에서 값을 높게 쳐주면 한쪽 주주가 손해를 봅니다.")
    out["steps"] = steps
    out["takeaway"] = f"{bsn}{_eul(bsn)} 사 와서 키우려는 결정입니다. 산 값보다 큰 추가 이익(시너지)을 만들 수 있느냐가 관건입니다."


def _business_trf(ev, out: dict) -> None:
    me = subject(ev)
    bsn = _raw(ev, "trf_bsn") or "사업 부문"
    who = clean_name(_raw(ev, "dlptn_cmpnm"))
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {bsn}{_eul(bsn)} {who + '에 ' if who else ''}{fmt_krw(amt) + '에 ' if amt else ''}통째로 팝니다."
    sl = _raw_pct(ev, "sl_rt")
    steps = ["BCG 매트릭스로 보면, 파는 사업은 회사가 '더 키우지 않을 사업'으로 판단한 것입니다. 성장이 낮거나 1등이 아닌 사업을 정리해 그 돈을 잘되는 사업에 넣는 그림입니다."]
    if sl:
        steps.append(f"떼어 파는 사업은 회사 매출의 {sl:.1f}%입니다. 이 매출이 빠진 뒤 남은 사업만으로 성장할 수 있는지 봐야 합니다.")
    purpose = _fact(ev, "양도 목적")
    if purpose:
        steps.append(f"공시 목적: '{_short(purpose, 60)}'.")
    steps.append("판 값이 그 사업의 장부값보다 크면 처분이익이 생기고, 그 사업 실적은 '중단영업'으로 따로 표시될 수 있습니다.")
    out["steps"] = steps
    out["takeaway"] = f"{bsn}{_eul(bsn)} 정리해 {fmt_krw(amt) if amt else '현금'}{_eul(fmt_krw(amt)) if amt else '을'} 확보하는 결정입니다. 남은 사업의 성장성과 판 돈의 쓰임이 관건입니다."


def _asset_acq(ev, out: dict) -> None:
    me = subject(ev)
    name = _raw(ev, "ast_nm") or _raw(ev, "ast_sen") or "설비"
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} {_short(name, 40)}{_eul(_short(name, 40))} {fmt_krw(amt) + '에 ' if amt else ''}사들입니다."
    purpose = " ".join(filter(None, [_fact(ev, "양수 목적"), _fact(ev, "양수 영향")]))
    steps = ["규모의 경제: 설비를 늘려 많이 만들수록 제품 하나에 드는 고정비(설비값, 감가상각비)가 줄어듭니다."]
    if any(w in purpose for w in ("생산", "증설", "캐파", "CAPA", "생산능력", "공장", "라인")):
        steps[0] += f" 공시 목적('{_short(_fact(ev, '양수 목적') or purpose, 40)}')이 생산 능력을 늘리는 것이라 바로 이 논리입니다."
    elif any(w in purpose for w in ("사옥", "본사", "사무", "업무용")):
        steps[0] = (f"사옥·업무용 건물이라면 규모의 경제보다는 임차료를 아끼거나 자산으로 보유하려는 목적입니다"
                    f"(공시 목적: '{_short(_fact(ev, '양수 목적') or purpose, 40)}').")
    if amt:
        steps.append(breakeven_line(ev, amt, "새 설비로"))
    steps.append("가동률이 핵심: 설비를 놀리면 고정비만 늘어 오히려 이익이 줄어듭니다. 이 설비를 채울 주문(수요)이 있는지가 관건입니다.")
    out["steps"] = steps
    out["takeaway"] = "현금을 설비로 바꿔 생산 능력을 키우는 결정입니다. 늘어난 고정비를 채울 만큼 팔 수 있느냐가 관건입니다." \
        if "규모의 경제" in steps[0] else "현금을 부동산·설비로 바꾸는 결정입니다. 그 자산이 비용을 줄이거나 가치를 지켜 줄지가 관건입니다."


def _asset_trf(ev, out: dict) -> None:
    me = subject(ev)
    name = _raw(ev, "ast_nm") or _raw(ev, "ast_sen") or "자산"
    amt = ev.amount
    short_name = _short(name, 40)
    out["what"] = f"{me}{_i(me)} {short_name}{_eul(short_name)} {fmt_krw(amt) + '에 ' if amt else ''}팝니다."
    purpose = _fact(ev, "양도 목적") or ""
    effect = _fact(ev, "양도 영향") or ""
    both = purpose + " " + effect
    if any(w in both for w in ("재임차", "임차", "리스백", "임대차")):
        out["plain"] += " 판 뒤 다시 빌려 쓰는 '세일 앤 리스백'이면, 계속 쓰면서 현금만 먼저 받는 셈입니다."
    fin = ev.fin or {}
    liab, eq, oi = fin.get("liabilities"), fin.get("equity"), fin.get("operating_income")
    if out["size"] and amt and eq and eq > 0 and "자기자본" not in (out["size"] or ""):
        out["size"] = out["size"].replace("에 해당합니다.", f", 주주 몫 재산(자기자본)의 {share_words(amt, eq)}에 해당합니다.", 1)
    steps = ["자본구조 이론은 빚과 자기 돈의 비율이 회사 위험을 정한다고 봅니다. 빚이 많으면 이자 부담과 위기 때 버틸 힘이 약해집니다."]
    repay = any(w in both for w in ("차입금", "부채", "재무구조", "상환"))
    if amt and liab and eq and eq > 0 and repay:
        before = liab / eq * 100
        after = max(liab - amt, 0) / eq * 100
        steps.append(f"판 돈을 모두 빚 갚는 데 쓰면 부채비율(빚 ÷ 자기자본)이 {before:.0f}%에서 약 {after:.0f}%로 내려갑니다"
                     "(처분이익은 빼고 단순 계산).")
    if amt and repay:
        saving = amt * ASSUMED_RATE
        line = f"이자 절감: {fmt_krw(amt)}만큼 빚을 갚으면 연 5% 금리 가정으로 매년 이자 약 {fmt_krw(saving)}이 줄어듭니다."
        if oi and oi > 0:
            line += f" 본업으로 1년에 버는 이익({fmt_krw(oi)})의 {share_words(saving, oi)}에 해당합니다."
        steps.append(line)
    if effect:
        steps.append(f"대가: 판 자산에서 나오던 수익(임대료 등)이나 쓰던 공간이 사라집니다. 공시가 밝힌 영향은 '{_short(effect, 70)}'입니다.")
    elif purpose:
        steps.append(f"공시 목적: '{_short(purpose, 60)}'.")
    out["steps"] = steps
    portion = share_words(_fact_pct(ev, "자산총액 대비"), 100) if _fact_pct(ev, "자산총액 대비") else None
    head = f"회사 재산의 {portion}{_eul(portion)} " if portion else "자산을 "
    if repay:
        out["takeaway"] = f"{head}현금으로 바꿔 빚을 줄이는 결정입니다. 줄어드는 이자와 잃는 자산의 쓰임새를 비교하는 게 핵심입니다."
    else:
        out["takeaway"] = f"{head}현금으로 바꾸는 결정입니다. 판 돈을 어디에 쓰는지가 관건입니다."


def _merger(ev, out: dict) -> None:
    me = subject(ev)
    partner = clean_name(_raw(ev, "mgptncmp_cmpnm")) or "상대 회사"
    biz = _raw(ev, "mgptncmp_mbsn")
    form = _raw(ev, "mg_stn")
    out["what"] = f"{me}{_i(me)} {partner}{f'({biz})' if biz else ''}{josa(partner, '과', '와')} 합칩니다{f'({form})' if form else ''}."
    rl = _raw(ev, "mgptncmp_rl_cmpn")
    group = any(w in rl for w in ("계열", "자회사", "종속", "특수관계", "최대주주"))
    if group:
        out["plain"] += " 같은 그룹 안의 합병이라 시너지보다 지배구조 정리나 중복 비용 절감이 목적인 경우가 많습니다."
    fin = ev.fin or {}
    o_ast, o_rev, o_ni = _raw_num(ev, "rbsnfdtl_tast"), _raw_num(ev, "rbsnfdtl_sl"), _raw_num(ev, "rbsnfdtl_nic")
    parts = []
    if o_ast and fin.get("assets"):
        parts.append(f"재산(총자산 {fmt_krw(o_ast)})은 우리 회사의 {share_words(o_ast, fin['assets'])}")
    if o_rev and fin.get("revenue"):
        parts.append(f"매출({fmt_krw(o_rev)})은 우리의 {share_words(o_rev, fin['revenue'])}")
    out["size"] = (f"상대 회사의 " + ", ".join(parts) + "입니다.") if parts else None
    if o_ni is not None and o_ni < 0 and out["size"]:
        out["size"] += f" 상대 회사는 직전 해 순손실({fmt_krw(-o_ni)})을 냈습니다."
    steps = []
    ratio = _raw(ev, "mg_rt")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", ratio.replace(",", ""))][:2] if ratio else []
    if len(nums) == 2 and nums[0] > 0:
        per = f"{nums[1] / nums[0]:.4f}".rstrip("0").rstrip(".")
        steps.append(f"합병비율({nums[0]:g} : {float(per):g}): 없어지는 {partner} 주식 1주를 {ev.corp_name} 주식 {per}주로 바꿔 줍니다. "
                     "이 비율이 한쪽에 유리하면 다른 쪽 주주가 손해를 보니, 두 회사 값을 어떻게 매겼는지가 핵심입니다.")
    elif ratio:
        steps.append(f"합병비율({_short(ratio, 30)})은 없어지는 회사 주식 1주를 남는 회사 주식 몇 주로 바꿔 주는지 정한 것입니다. "
                     "이 비율이 한쪽에 유리하면 다른 쪽 주주가 손해를 봅니다.")
    line = synergy_kind_line(_fact(ev, "합병 목적"))
    if line:
        steps.append(line)
    if group:
        ev_name = _raw(ev, "exevl_intn")
        steps.append(f"같은 그룹끼리라 웃돈 문제보다 합병비율이 공정한지가 핵심입니다{f'(외부평가: {_short(ev_name, 20)})' if ev_name else ''}.")
    else:
        steps.append("남남끼리의 합병이면 합쳐서 없앨 수 있는 중복 비용(본사, 영업망, 구매)이 시너지의 출발점입니다.")
    rel = relatedness(ev, biz)
    if rel and not group:
        steps.append(rel)
    out["steps"] = steps
    out["takeaway"] = (f"{partner}{_eul(partner)} 흡수해 한 회사가 되는 결정입니다. "
                       + ("합병비율이 양쪽 주주에게 공정한지가 관건입니다." if group else "합쳐서 생기는 시너지가 치른 값보다 크냐가 관건입니다."))


def _split(ev, out: dict) -> None:
    me = subject(ev)
    mth = _raw(ev, "dv_mth")
    new_co = clean_name(_raw(ev, "dvfcmp_cmpnm")) or "새 회사"
    biz = _raw(ev, "dvfcmp_mbsn")
    physical = "물적" in mth
    personal = "인적" in mth
    kind = "물적분할" if physical else "인적분할" if personal else "분할"
    out["what"] = f"{me}{_i(me)} {biz + ' ' if biz else ''}사업을 떼어 {new_co}{_eul(new_co)} 새로 만듭니다({kind})."
    if physical:
        out["plain"] += (" 물적분할은 떼어 낸 새 회사 주식을 기존 회사가 100% 갖는 방식입니다. 당장 주주에게 달라지는 건 없지만, "
                         "나중에 새 회사를 따로 상장하면 기존 주주 몫이 묽어질 수 있습니다.")
    elif personal:
        out["plain"] += " 인적분할은 기존 주주가 지분대로 새 회사 주식을 나눠 받는 방식입니다. 한 회사 주식이 두 회사 주식으로 나뉩니다."
    new_rev, rest_rev = _raw_num(ev, "dvfcmp_nbsn_rsl"), _raw_num(ev, "atdv_excmp_exbsn_rsl")
    total = (new_rev or 0) + (rest_rev or 0) if new_rev and rest_rev else (ev.fin or {}).get("revenue")
    out["size"] = f"떼어 내는 사업의 매출({fmt_krw(new_rev)})은 분할 전 매출의 {share_words(new_rev, total)}입니다." if new_rev and total else out["size"]
    steps = ["복합기업 할인: 성격이 다른 사업이 한 회사에 섞여 있으면 시장이 사업별 가치를 제대로 쳐주지 않는 경향이 있습니다. "
             "분할은 사업마다 따로 제값을 받게 하려는 시도입니다."]
    if physical:
        relist = _raw(ev, "dvfcmp_rlst_atn")
        steps.append("물적분할 뒤 새 회사를 상장하면 모회사 주주는 새 회사 주식을 직접 갖지 못해, 새 회사 가치가 새로 들어온 주주와 나뉩니다('쪼개기 상장' 논란)."
                     + (f" 공시상 새 회사 재상장 계획: {_short(relist, 20)}." if relist else ""))
    elif personal:
        steps.append("인적분할은 지주회사로 바뀌는 첫 단계로 자주 쓰입니다. 이 과정에서 대주주의 지배력이 커진다는 비판이 있습니다.")
    steps.append("반대하는 주주가 회사에 '내 주식을 공정한 값에 사 달라'고 할 수 있는지(주식매수청구권)도 함께 봐야 합니다.")
    out["steps"] = steps
    out["takeaway"] = f"{biz or '일부'} 사업을 떼어 따로 값을 받게 하려는 결정입니다. 기존 주주 몫이 지켜지는지가 관건입니다."


def _rights(ev, out: dict) -> None:
    me = subject(ev)
    prefix = "piic_" if ev.rule.key == "rights_bonus" else ""
    new = _raw_num(ev, f"{prefix}nstk_ostk_cnt")
    before = _raw_num(ev, f"{prefix}bfic_tisstk_ostk")
    method = _raw(ev, f"{prefix}ic_mthn")
    amt = ev.amount
    out["what"] = (f"{me}{_i(me)} 새 주식{f' {new:,.0f}주' if new else ''}를 팔아 {fmt_krw(amt) + '을 ' if amt else '돈을 '}모읍니다"
                   f"{f'({method})' if method else ''}.")
    steps = ["신호이론: 회사 사정은 경영진이 투자자보다 잘 압니다. 그래서 '새 주식을 판다'는 행동 자체가 '지금 주가가 비싸다고 본다'는 신호로 읽혀 주가가 떨어지는 경우가 많습니다."]
    if new and before:
        d = new / before
        out["size"] = (f"새 주식은 지금 주식 수의 {d * 100:.1f}%입니다. 증자에 참여하지 않으면 지분 1%가 약 {1 / (1 + d):.2f}%로 줄어드는 셈입니다."
                       + (f" {out['size']}" if out["size"] else ""))
    if amt:
        d = ev.detail or {}
        use = {k: parse_amount(d.get(f"{prefix}{k}")) or 0 for k in ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc")}
        survive = use["fdpp_op"] + use["fdpp_dtrp"]
        grow = use["fdpp_fclt"] + use["fdpp_bsninh"] + use["fdpp_ocsa"]
        if survive / amt >= 0.5:
            steps.append(f"돈의 쓰임: 모은 돈의 {survive / amt * 100:.0f}%가 운영자금·빚 갚기라 '버티기 위한 증자'로 읽히기 쉽습니다(나쁜 신호 쪽).")
        elif grow / amt >= 0.5:
            steps.append(f"돈의 쓰임: 모은 돈의 {grow / amt * 100:.0f}%가 시설투자·인수 자금이라 '성장을 위한 증자'로 해석될 여지가 있습니다.")
    if "제3자" in method:
        steps.append("방식: 특정 투자자에게 파는 제3자배정이라 누가 사는지가 곧 신호입니다. 회사를 잘 아는 투자자가 들어오면 오히려 좋은 신호가 될 수 있습니다.")
    elif "주주배정" in method:
        steps.append("방식: 기존 주주에게 먼저 살 기회를 주는 주주배정이라, 참여하면 지분이 유지됩니다.")
    elif "공모" in method:
        steps.append("방식: 누구나 살 수 있는 일반공모라 흥행을 위해 할인 폭이 커질 수 있습니다.")
    out["steps"] = steps
    out["takeaway"] = "주주에게 돈을 더 받아 회사를 꾸리는 결정입니다. 모은 돈이 성장에 쓰이느냐 버티기에 쓰이느냐가 신호를 가릅니다."


def _bonus(ev, out: dict) -> None:
    me = subject(ev)
    per = parse_amount(_raw(ev, "nstk_ascnt_ps_ostk"))
    out["what"] = f"{me}{_i(me)} 주주에게{f' 1주당 {per:g}주씩' if per else ''} 새 주식을 공짜로 나눠 줍니다."
    if per:
        out["size"] = f"주식 수가 {1 + per:g}배가 되니, 이론상 주가는 지금의 약 {100 / (1 + per):.0f}% 수준으로 조정됩니다(권리락)."
    out["steps"] = [
        "행동경제학: 사람들은 주식 수가 늘고 주가가 낮아지면 '싸졌다'고 느끼기 쉽습니다. 그래서 가치가 그대로인데도 발표 뒤 주가가 오르는 일이 잦습니다.",
        "회계로는 쌓아 둔 잉여금을 자본금으로 옮기는 것뿐이라 자본 총액은 변하지 않습니다.",
        "실제 효과는 거래되는 주식이 많아져 사고팔기 쉬워지는 정도입니다.",
    ]
    out["takeaway"] = "회사 가치는 그대로인 '숫자 쪼개기'입니다. 발표 뒤 주가가 오르면 기대 심리가 만든 부분일 수 있습니다."


def _reduction(ev, out: dict) -> None:
    me = subject(ev)
    ratio = _raw(ev, "cr_rt_ostk")
    mth = _raw(ev, "cr_mth") + " " + (_fact(ev, "감자 사유") or "")
    free = "무상" in mth or "결손" in mth
    out["what"] = f"{me}{_i(me)} 자본금을 줄입니다{f'(감자비율 {_short(ratio, 20)})' if ratio else ''}."
    steps = []
    if free:
        steps.append("무상감자: 주식 수를 줄여 장부에 쌓인 손실을 자본금으로 메웁니다. 주주는 돈을 받지 못하고 주식 수만 줄어 손해를 봅니다.")
        steps.append("자본구조로 보면, 손실이 쌓여 자본이 깎인(자본잠식) 상태를 정리하는 절차입니다. 다음 단계로 새 돈을 넣는 유상증자가 이어지는 경우가 많습니다.")
    else:
        steps.append("유상감자: 주식을 줄이면서 주주에게 돈을 돌려줍니다. 쓸 데 없는 현금을 주주에게 돌려주는 주주환원이 될 수도 있고, 대주주가 돈을 빼 가는 수단이 될 수도 있습니다.")
    out["steps"] = steps
    out["takeaway"] = "장부상 손실을 정리하는 결정입니다. 이어서 새 돈이 들어오는지가 관건입니다." if free else "자본을 줄여 주주에게 돈을 돌려주는 결정입니다. 누가 그 돈을 가장 많이 받는지가 관건입니다."


def _treasury(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    key = ev.rule.key
    fin = ev.fin or {}
    if key == "treasury_trust":
        out["what"] = f"{me}{_i(me)} 증권사에 {fmt_krw(amt) + ' 한도로 ' if amt else ''}자기 회사 주식을 사 달라고 맡깁니다(신탁)."
    elif key == "treasury_buy":
        out["what"] = f"{me}{_i(me)} 자기 회사 주식을 {fmt_krw(amt) + '어치 ' if amt else ''}사들입니다."
    elif key == "treasury_cancel":
        out["what"] = f"{me}{_i(me)} 갖고 있던 자기 회사 주식을 없앱니다(소각)."
    ni = fin.get("net_income")
    if amt and ni and ni > 0:
        extra = f"{_year(ev)}순이익({fmt_krw(ni)})의 {share_words(amt, ni)} 규모입니다."
        out["size"] = (out["size"] + " " + extra) if out["size"] else extra
    purpose = _fact(ev, "취득 목적", "계약 목적") or ""
    steps = ["배당·자사주 이론: 번 돈을 주주에게 돌려주는 길은 배당과 자사주 두 가지입니다. 자사주는 팔고 싶은 주주만 현금을 받고, 남는 주주는 지분이 커지는 방식입니다."]
    if key == "treasury_cancel" or "소각" in purpose:
        steps.append("소각: 산 주식을 없애 주식 수가 실제로 줄어듭니다. 이익이 같아도 한 주당 이익(주당순이익)이 커져 주가에 직접 도움이 됩니다.")
    else:
        steps.append("소각 여부: 목적에 소각이 없으면 나중에 다시 팔 수도 있어 효과가 약합니다. 2026년 3월부터는 회사가 산 자사주를 원칙적으로 1년 안에 소각해야 합니다.")
    steps.append("신호: 회사가 자기 주가를 싸다고 본다는 메시지로 읽히는 경우가 많습니다. 다만 다른 투자보다 자사주가 낫다는 건 성장 기회가 적다는 뜻일 수도 있습니다.")
    out["steps"] = steps
    out["takeaway"] = "번 돈을 자사주로 주주에게 돌려주는 결정입니다. 실제로 소각까지 하는지가 관건입니다."


def _treasury_sell(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    out["what"] = f"{me}{_i(me)} 갖고 있던 자기 회사 주식을 {fmt_krw(amt) + '어치 ' if amt else ''}팝니다."
    purpose = _fact(ev, "처분 목적") or ""
    steps = ["신호이론: 회사가 자기 주식을 판다는 건 지금 주가를 충분히 높다고 본다는 신호로 읽힐 수 있습니다."]
    if any(w in purpose for w in ("임직원", "상여", "보상", "성과")):
        steps.append(f"목적('{_short(purpose, 40)}')을 보면 직원 보상용이라, 시장에 한꺼번에 풀리는 물량 부담은 크지 않을 수 있습니다.")
    elif any(w in purpose for w in ("교환사채", "EB")):
        steps.append("교환사채의 교환 대상으로 쓰는 처분이라, 사실상 자사주를 담보로 돈을 빌리는 셈입니다.")
    elif purpose:
        steps.append(f"목적: '{_short(purpose, 60)}'.")
    steps.append("자사주가 다시 시장에 풀리면 유통 주식이 늘어 한 주당 몫이 묽어지고, 우호 세력에게 넘어가면 경영권 방어 수단이 되기도 합니다.")
    out["steps"] = steps
    out["takeaway"] = "쌓아 둔 자사주를 현금이나 다른 용도로 돌리는 결정입니다. 누구에게, 왜 파는지가 관건입니다."


def _mezzanine(ev, out: dict) -> None:
    me = subject(ev)
    amt = ev.amount
    names = {"cb": "전환사채", "bw": "신주인수권부사채", "eb": "교환사채"}
    nm = names.get(ev.rule.key, "사채")
    out["what"] = f"{me}{_i(me)} {fmt_krw(amt) + ' 규모의 ' if amt else ''}{nm}{_eul(nm)} 발행합니다."
    price = parse_amount(_raw(ev, "cv_prc") or _raw(ev, "ex_prc"))
    if price:
        out["plain"] += f" 이번 조건은 1주 {price:,.0f}원입니다."
    vs = _raw_pct(ev, "cvisstk_tisstk_vs") or _raw_pct(ev, "nstk_isstk_tisstk_vs") or _raw_pct(ev, "extg_tisstk_vs")
    if vs:
        out["size"] = (f"모두 주식으로 바뀌면 지금 주식 수의 {vs:.1f}%만큼 주식이 새로 생기거나 넘어갑니다(잠재 희석)."
                       + (f" {out['size']}" if out["size"] else ""))
    coupon = parse_amount(_raw(ev, "bd_intr_ex"))
    steps = ["자본구조: 빚(이자 부담)과 주식(지분 희석)의 중간 형태입니다. 주가가 오르면 빚이 주식으로 바뀌어 갚을 돈이 사라지고, 주가가 안 오르면 만기에 빚으로 갚아야 합니다."]
    if coupon is not None:
        if coupon == 0:
            steps.append("이자: 표면이자율이 0%라 투자자는 이자가 아니라 주가 상승만 보고 들어옵니다.")
        else:
            steps.append(f"이자: 표면이자율 {coupon:g}%로 일반 회사채보다 낮게 빌리는 대신, 주식으로 바꿀 권리를 얹어 줍니다.")
    floor = parse_amount(_raw(ev, "act_mktprcfl_cvprc_lwtrsprc"))
    if floor:
        steps.append(f"리픽싱: 주가가 떨어지면 전환가격을 {floor:,.0f}원까지 낮출 수 있어, 그만큼 새 주식이 늘어 희석이 커질 수 있습니다.")
    if "사모" in _raw(ev, "bdis_mthn"):
        steps.append("발행 방식: 소수 투자자에게만 파는 사모입니다. 일반 회사채를 찍기 어려운 회사가 이 방식을 많이 써서, 재무 여력이 넉넉지 않다는 신호로 보기도 합니다.")
    out["steps"] = steps
    out["takeaway"] = f"이자 부담을 낮추는 대신 미래의 주식을 내주는 {nm} 발행입니다. 주가가 떨어질 때 희석이 얼마나 커지는지가 관건입니다."


def _ipo(ev, out: dict) -> None:
    price = _num(_fact(ev, "공모가(모집가액)"))
    count = _num(_fact(ev, "공모 주식 수"))
    amt = ev.amount
    name = ev.corp_name
    bits = []
    if count:
        bits.append(f"주식 {count:,.0f}주를")
    if price:
        bits.append(f"1주 {price:,.0f}원에 팔아")
    money = f"{fmt_krw(amt)}을 모으고" if amt else "돈을 모으고"
    out["what"] = f"{name}{_i(name)} {' '.join(bits) + ' ' if bits else ''}{money} 증권시장에 상장하려 합니다."
    steps = ["IPO 저평가: 처음 파는 주식은 일부러 조금 싸게 값을 정하는 경향이 있습니다. 회사를 잘 모르는 투자자를 끌어들이고 흥행 실패를 막으려는 '개업 할인'입니다."]
    if price:
        steps.append(f"그래서 상장 첫날 주가가 공모가보다 오르는 경우가 많습니다. 상장 첫날 종가와 공모가 {price:,.0f}원의 차이가 이 할인의 크기입니다.")
    steps.append("공모가는 기관투자자 수요예측으로 정합니다. 희망 범위 위쪽에서 정해질수록, 기관이 오래 팔지 않겠다고 약속한 물량(의무보유확약)이 많을수록 시장 기대가 크다는 뜻입니다.")
    out["steps"] = steps
    out["takeaway"] = "회사가 처음으로 시장에서 값을 매겨 받는 순간입니다. 공모가가 회사 가치에 비해 싼지, 상장 뒤 쏟아질 물량은 없는지가 관건입니다."


def _earnings(ev, out: dict) -> None:
    me = subject(ev)
    out["what"] = f"{me}{_i(me)} 실적(또는 실적 변동)을 미리 알렸습니다."
    fin = ev.fin or {}
    rev, rev_p, oi, oi_p = fin.get("revenue"), fin.get("revenue_prev"), fin.get("operating_income"), fin.get("operating_income_prev")
    steps = ["영업레버리지: 임차료·감가상각비·인건비처럼 고정비가 큰 회사는 매출이 조금만 변해도 이익이 크게 출렁입니다."]
    if rev and rev_p and oi and oi_p and oi_p > 0 and rev_p > 0:
        g_rev = (rev / rev_p - 1) * 100
        g_oi = (oi / oi_p - 1) * 100
        line = f"이 회사의 {_year(ev)}숫자로 보면 매출이 {g_rev:+.1f}% 변할 때 영업이익은 {g_oi:+.1f}% 변했습니다."
        if abs(g_rev) >= 1 and abs(g_oi) > abs(g_rev) * 1.5:
            line += f" 이익이 매출보다 {abs(g_oi / g_rev):.1f}배 크게 움직인 셈이라 고정비 부담이 큰 구조로 보입니다."
        steps.append(line)
    steps.append("이번 공시의 매출·영업이익 변화율을 같은 방식으로 나눠 보면, 실적 변화가 판매량 때문인지 비용 구조 때문인지 가늠할 수 있습니다.")
    out["steps"] = steps
    out["takeaway"] = "실적이 크게 바뀌었다는 알림입니다. 매출 변화보다 이익 변화가 얼마나 더 큰지가 이 회사의 체질을 보여 줍니다."


def _generic(ev, out: dict, lens: dict | None) -> None:
    me = subject(ev)
    out["what"] = f"{me}{_i(me)} '{ev.rule.label}' 공시를 냈습니다."
    if ev.amount:
        out["what"] += f" {ev.amount_label or '금액'}{_eun(ev.amount_label or '금액')} {fmt_krw(ev.amount)}입니다."
    if lens and lens.get("watch"):
        out["steps"] = [f"{lens['title']}로 보면: {lens['watch']}"]
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
        out["what"] += " (앞서 낸 공시 내용을 고친 정정 공시입니다.)"
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
    if len(s) < 15 or re.sub(r"\W", "", s) == re.sub(r"\W", "", title or ""):
        return ""
    return s if len(s) <= 200 else s[:199].rstrip() + "…"


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
    what = lead_sentence(getattr(item, "summary", ""), item.title) or item.title
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
