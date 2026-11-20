"""테스트 전용 가짜 데이터. 회사명과 숫자는 모두 지어낸 것이며 실제 기업과 관계없다.
응답 구조(항목명)는 OpenDART 개발가이드의 필드명을 따른다."""

from __future__ import annotations

from casenote.dart import Corp, CorpIndex

CORPS = [
    Corp("90000001", "테스트전자", "900001"),
    Corp("90000002", "샘플화학", "900002"),
    Corp("90000003", "가상바이오", "900003"),
    Corp("90000005", "모의반도체", "900005"),
]

DAY = "20261119"

FILINGS = {
    "B": [
        {"corp_cls": "Y", "corp_name": "테스트전자", "corp_code": "90000001", "stock_code": "900001",
         "report_nm": "주요사항보고서(회사합병결정)", "rcept_no": "20261119000101", "flr_nm": "테스트전자", "rcept_dt": DAY, "rm": "유"},
        {"corp_cls": "K", "corp_name": "가상바이오", "corp_code": "90000003", "stock_code": "900003",
         "report_nm": "주요사항보고서(유상증자결정)", "rcept_no": "20261119000202", "flr_nm": "가상바이오", "rcept_dt": DAY, "rm": "코"},
        {"corp_cls": "Y", "corp_name": "샘플화학", "corp_code": "90000002", "stock_code": "900002",
         "report_nm": "[기재정정]주요사항보고서(자기주식취득결정)", "rcept_no": "20261119000303", "flr_nm": "샘플화학", "rcept_dt": DAY, "rm": "유"},
        {"corp_cls": "Y", "corp_name": "샘플화학", "corp_code": "90000002", "stock_code": "900002",
         "report_nm": "주요사항보고서(회사분할결정)", "rcept_no": "20261119000404", "flr_nm": "샘플화학", "rcept_dt": DAY, "rm": "유"},
        {"corp_cls": "K", "corp_name": "가상바이오", "corp_code": "90000003", "stock_code": "900003",
         "report_nm": "주요사항보고서(전환사채권발행결정)", "rcept_no": "20261119000505", "flr_nm": "가상바이오", "rcept_dt": DAY, "rm": "코 철"},
    ],
    "I": [
        {"corp_cls": "Y", "corp_name": "테스트전자", "corp_code": "90000001", "stock_code": "900001",
         "report_nm": "주식소각결정", "rcept_no": "20261119800601", "flr_nm": "테스트전자", "rcept_dt": DAY, "rm": "유"},
        {"corp_cls": "Y", "corp_name": "샘플화학", "corp_code": "90000002", "stock_code": "900002",
         "report_nm": "단일판매ㆍ공급계약체결", "rcept_no": "20261119800702", "flr_nm": "샘플화학", "rcept_dt": DAY, "rm": "유"},
        {"corp_cls": "K", "corp_name": "가상바이오", "corp_code": "90000003", "stock_code": "900003",
         "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)", "rcept_no": "20261119800803", "flr_nm": "가상바이오", "rcept_dt": DAY, "rm": "코"},
    ],
    "C": [
        {"corp_cls": "E", "corp_name": "예시물산", "corp_code": "90000004", "stock_code": "",
         "report_nm": "증권신고서(지분증권)", "rcept_no": "20261119000909", "flr_nm": "예시물산", "rcept_dt": DAY, "rm": ""},
    ],
    "D": [],
}

DETAILS = {
    ("cmpMgDecsn", "90000001"): [{
        "rcept_no": "20261119000101", "corp_cls": "Y", "corp_code": "90000001", "corp_name": "테스트전자",
        "mg_mth": "테스트전자가 모의부품을 흡수합병", "mg_stn": "소규모합병", "mg_pp": "부품 내재화를 통한 원가 절감과 의사결정 단순화",
        "mg_rt": "1 : 0.5000000", "mg_rt_bs": "자본시장법 시행령 제176조의5에 따른 기준시가로 산정",
        "exevl_atn": "미해당", "exevl_intn": "-", "mgnstk_ostk_cnt": "1,200,000", "mgptncmp_cmpnm": "모의부품",
        "mgptncmp_mbsn": "전자부품 제조", "mgptncmp_rl_cmpn": "계열회사", "rbsnfdtl_tast": "350,000,000,000",
        "rbsnfdtl_tdbt": "120,000,000,000", "rbsnfdtl_sl": "410,000,000,000", "rbsnfdtl_nic": "21,000,000,000",
        "mgsc_mgdt": "2027년 02월 01일", "bdlst_atn": "미해당", "aprskh_plnprc": "해당사항없음", "bddd": "2026년 11월 19일",
    }],
    ("piicDecsn", "90000003"): [{
        "rcept_no": "20261119000202", "corp_cls": "K", "corp_code": "90000003", "corp_name": "가상바이오",
        "nstk_ostk_cnt": "5,000,000", "nstk_estk_cnt": "-", "fv_ps": "500", "bfic_tisstk_ostk": "25,000,000",
        "fdpp_fclt": "20,000,000,000", "fdpp_bsninh": "-", "fdpp_op": "40,000,000,000", "fdpp_dtrp": "15,000,000,000",
        "fdpp_ocsa": "-", "fdpp_etc": "-", "ic_mthn": "주주배정후 실권주 일반공모", "ssl_at": "아니오",
    }],
    ("tsstkAqDecsn", "90000002"): [{
        "rcept_no": "20261119000303", "corp_cls": "Y", "corp_code": "90000002", "corp_name": "샘플화학",
        "aqpln_stk_ostk": "300,000", "aqpln_stk_estk": "-", "aqpln_prc_ostk": "30,000,000,000", "aqpln_prc_estk": "-",
        "aqexpd_bgd": "2026년 11월 20일", "aqexpd_edd": "2027년 02월 19일", "aq_pp": "주주가치 제고를 위한 소각",
        "aq_mth": "유가증권시장을 통한 장내 직접 취득", "aq_wtn_div_ostk_rt": "1.2", "aq_dd": "2026년 11월 19일",
    }],
    ("cmpDvDecsn", "90000002"): [{
        "rcept_no": "20261119000404", "corp_cls": "Y", "corp_code": "90000002", "corp_name": "샘플화학",
        "dv_mth": "물적분할 방식으로 분할회사가 분할신설회사 발행주식 100%를 취득", "dv_rt": "-",
        "dv_trfbsnprt_cn": "첨단소재 사업부문 일체", "dv_impef": "사업 전문성 제고와 외부 투자 유치",
        "atdv_excmp_cmpnm": "샘플화학", "atdvfdtl_tast": "2,100,000,000,000", "atdv_excmp_exbsn_rsl": "1,500,000,000,000",
        "dvfcmp_cmpnm": "샘플첨단소재(가칭)", "ffdtl_tast": "600,000,000,000", "dvfcmp_nbsn_rsl": "450,000,000,000",
        "dvfcmp_mbsn": "첨단소재 제조", "dvfcmp_rlst_atn": "미해당", "dvdt": "2027년 04월 01일", "bddd": "2026년 11월 19일",
    }],
}

IPO_GROUPS = {
    "일반사항": [{"rcept_no": "20261119000909", "sbd": "2026년 12월 10일 ~ 2026년 12월 11일", "pymd": "2026년 12월 15일"}],
    "증권의종류": [{"stksen": "기명식보통주", "stkcnt": "2,000,000", "fv": "500", "slprc": "25,000", "slta": "50,000,000,000", "slmthn": "일반공모"}],
    "인수인정보": [{"actsen": "대표", "actnmn": "모의증권", "udtcnt": "2,000,000"}],
}


def _acct(year: str, fs: str, name: str, cur: str, prev: str, prev2: str, sj: str = "IS", corp_code: str | None = None):
    row = {"rcept_no": "20260310000001", "bsns_year": year, "stock_code": "", "reprt_code": "11011", "account_nm": name,
           "fs_div": fs, "fs_nm": "연결재무제표" if fs == "CFS" else "재무제표", "sj_div": sj, "sj_nm": "",
           "thstrm_nm": f"제 {year} 기", "thstrm_dt": "", "thstrm_amount": cur, "frmtrm_amount": prev, "bfefrmtrm_amount": prev2,
           "ord": "1", "currency": "KRW"}
    if corp_code:
        row["corp_code"] = corp_code
    return row


def major_rows(scale: float, corp_code: str | None = None, year: str = "2025") -> list[dict]:
    """scale 배수로 숫자를 키운 주요계정(연결·별도)."""
    def v(x):
        return f"{x * scale:,.0f}"
    rows = []
    for fs, k in (("CFS", 1.0), ("OFS", 0.7)):
        rows += [
            _acct(year, fs, "자산총계", v(1000e8 * k), v(900e8 * k), v(800e8 * k), "BS", corp_code),
            _acct(year, fs, "부채총계", v(400e8 * k), v(380e8 * k), v(350e8 * k), "BS", corp_code),
            _acct(year, fs, "자본총계", v(600e8 * k), v(520e8 * k), v(450e8 * k), "BS", corp_code),
            _acct(year, fs, "유동자산", v(450e8 * k), v(400e8 * k), v(380e8 * k), "BS", corp_code),
            _acct(year, fs, "유동부채", v(250e8 * k), v(240e8 * k), v(220e8 * k), "BS", corp_code),
            _acct(year, fs, "매출액", v(1200e8 * k), v(1000e8 * k), v(950e8 * k), "IS", corp_code),
            _acct(year, fs, "영업이익", v(150e8 * k), v(100e8 * k), v(90e8 * k), "IS", corp_code),
            _acct(year, fs, "법인세차감전 순이익", v(140e8 * k), v(95e8 * k), v(85e8 * k), "IS", corp_code),
            _acct(year, fs, "당기순이익", v(110e8 * k), v(75e8 * k), v(66e8 * k), "IS", corp_code),
        ]
    return rows


SCALES = {"90000001": 100.0, "90000002": 30.0, "90000003": 0.8, "90000005": 60.0}


def full_rows(scale: float, year: str = "2025") -> list[dict]:
    def row(sj, aid, name, cur, prev):
        return {"rcept_no": "20260310000001", "reprt_code": "11011", "bsns_year": year, "corp_code": "90000001",
                "sj_div": sj, "sj_nm": "", "account_id": aid, "account_nm": name, "account_detail": "-",
                "thstrm_nm": "", "thstrm_amount": f"{cur * scale:.0f}", "frmtrm_nm": "", "frmtrm_amount": f"{prev * scale:.0f}",
                "bfefrmtrm_nm": "", "bfefrmtrm_amount": "", "ord": "1", "currency": "KRW"}
    return [
        row("BS", "ifrs-full_Assets", "자산총계", 1000e8, 900e8),
        row("BS", "ifrs-full_Liabilities", "부채총계", 400e8, 380e8),
        row("BS", "ifrs-full_Equity", "자본총계", 600e8, 520e8),
        row("BS", "ifrs-full_Inventories", "재고자산", 120e8, 110e8),
        row("BS", "ifrs-full_TradeAndOtherCurrentReceivables", "매출채권및기타채권", 150e8, 140e8),
        row("CIS", "ifrs-full_Revenue", "매출액", 1200e8, 1000e8),
        row("CIS", "ifrs-full_CostOfSales", "매출원가", 800e8, 690e8),
        row("CIS", "ifrs-full_GrossProfit", "매출총이익", 400e8, 310e8),
        row("CIS", "dart_TotalSellingGeneralAdministrativeExpenses", "판매비와관리비", 250e8, 210e8),
        row("CIS", "dart_OperatingIncomeLoss", "영업이익", 150e8, 100e8),
        row("CIS", "ifrs-full_FinanceCosts", "금융비용", 12e8, 11e8),
        row("CIS", "ifrs-full_ProfitLossBeforeTax", "법인세비용차감전순이익", 140e8, 95e8),
        row("CIS", "ifrs-full_IncomeTaxExpenseContinuingOperations", "법인세비용", 30e8, 20e8),
        row("CIS", "ifrs-full_ProfitLoss", "당기순이익", 110e8, 75e8),
        row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", 180e8, 130e8),
        row("CF", "ifrs-full_CashFlowsFromUsedInInvestingActivities", "투자활동현금흐름", -120e8, -90e8),
        row("CF", "ifrs-full_CashFlowsFromUsedInFinancingActivities", "재무활동현금흐름", -40e8, -20e8),
        row("CF", "ifrs-full_PurchaseOfPropertyPlantAndEquipment", "유형자산의 취득", -100e8, -80e8),
        row("CF", "ifrs-full_IncomeTaxesPaidRefundClassifiedAsOperatingActivities", "법인세의 납부", -25e8, -18e8),
        row("CF", "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "배당금의 지급", -20e8, -15e8),
        row("CF", "ifrs-full_AdjustmentsForDepreciationExpense", "감가상각비", 60e8, 55e8),
    ]


EMPLOYEES = [
    {"rcept_no": "x", "corp_cls": "Y", "corp_code": "90000001", "corp_name": "테스트전자", "fo_bbm": "전사", "sexdstn": "남",
     "rgllbr_co": "6,000", "cnttk_co": "200", "sm": "6,200", "avrg_cnwk_sdytrn": "12.5", "fyer_salary_totamt": "744,000,000,000", "jan_salary_am": "120,000,000"},
    {"rcept_no": "x", "corp_cls": "Y", "corp_code": "90000001", "corp_name": "테스트전자", "fo_bbm": "전사", "sexdstn": "여",
     "rgllbr_co": "1,700", "cnttk_co": "100", "sm": "1,800", "avrg_cnwk_sdytrn": "9.5", "fyer_salary_totamt": "180,000,000,000", "jan_salary_am": "100,000,000"},
    {"rcept_no": "x", "corp_cls": "Y", "corp_code": "90000001", "corp_name": "테스트전자", "fo_bbm": "합계", "sexdstn": "",
     "rgllbr_co": "7,700", "cnttk_co": "300", "sm": "8,000", "avrg_cnwk_sdytrn": "11.8", "fyer_salary_totamt": "924,000,000,000", "jan_salary_am": "115,500,000"},
]


class FakeDart:
    """DartClient와 같은 메서드 이름을 가진 가짜 클라이언트(네트워크 없음)."""

    def __init__(self):
        self.calls: list[str] = []

    def corp_index(self, refresh_days: float = 7) -> CorpIndex:
        return CorpIndex(list(CORPS))

    def list_filings(self, bgn_de, end_de, pblntf_ty=None, corp_cls=None, corp_code=None, pblntf_detail_ty=None, max_pages=30):
        self.calls.append(f"list:{pblntf_ty}")
        return [dict(f) for f in FILINGS.get(pblntf_ty, [])]

    def event_detail(self, endpoint, corp_code, bgn_de, end_de):
        self.calls.append(f"detail:{endpoint}")
        return [dict(r) for r in DETAILS.get((endpoint, corp_code), [])]

    def registration(self, endpoint, corp_code, bgn_de, end_de):
        return {k: [dict(r) for r in v] for k, v in IPO_GROUPS.items()}

    def company(self, corp_code):
        return {"status": "000", "corp_name": next(c.corp_name for c in CORPS if c.corp_code == corp_code),
                "ceo_nm": "홍길동", "est_dt": "19900101", "acc_mt": "12", "hm_url": "www.example.com"}

    def single_accounts(self, corp_code, year, reprt_code="11011"):
        if year != 2025:
            return []
        return major_rows(SCALES.get(corp_code, 1.0))

    def multi_accounts(self, corp_codes, year, reprt_code="11011"):
        if year != 2025:
            return []
        rows = []
        for code in corp_codes:
            rows += major_rows(SCALES.get(code, 1.0), corp_code=code)
        return rows

    def full_statements(self, corp_code, year, reprt_code="11011", fs_div="CFS"):
        return full_rows(SCALES.get(corp_code, 1.0)) if fs_div == "CFS" else []

    def employees(self, corp_code, year, reprt_code="11011"):
        return [dict(r) for r in EMPLOYEES] if corp_code == "90000001" else []

    def auditor_opinion(self, corp_code, year, reprt_code="11011"):
        return [{"bsns_year": "제56기(당기)", "adtor": "가상회계법인", "adt_opinion": "적정의견", "emphs_matter": "-", "core_adt_matter": "수익인식"}]

    def dividends(self, corp_code, year, reprt_code="11011"):
        return [{"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,500", "frmtrm": "1,200", "lwfr": "1,000"}]

    def major_shareholders(self, corp_code, year, reprt_code="11011"):
        return [{"nm": "가상홀딩스", "relate": "최대주주", "stock_knd": "보통주", "trmend_posesn_stock_co": "30,000,000", "trmend_posesn_stock_qota_rt": "35.10"}]


GOOGLE_NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>test</title>
<item><title>테스트전자, 모의부품 흡수합병 결정…부품 내재화 - 가상경제</title><link>https://news.example.com/a1</link>
<pubDate>Thu, 19 Nov 2026 09:00:00 GMT</pubDate><description>테스트전자, 모의부품 흡수합병 결정…부품 내재화 가상경제</description><source url="https://news.example.com">가상경제</source></item>
<item><title>테스트전자 모의부품 흡수합병 결정, 부품 내재화 - 모의일보</title><link>https://news.example.com/a2</link>
<pubDate>Thu, 19 Nov 2026 09:10:00 GMT</pubDate><source url="https://news.example.org">모의일보</source></item>
<item><title>샘플화학, 첨단소재 사업 물적분할…자회사 상장은 미정 - 가상경제</title><link>https://news.example.com/a3</link>
<pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate><source url="https://news.example.com">가상경제</source></item>
<item><title>[단독] 가상바이오 유상증자 750억…운영자금 확보 - 모의일보</title><link>https://news.example.com/a4</link>
<pubDate>Thu, 19 Nov 2026 11:00:00 GMT</pubDate><source url="https://news.example.org">모의일보</source></item>
<item><title>예시물산, 수요예측 앞두고 공모가 희망밴드 제시 - 가상경제</title><link>https://news.example.com/a5</link>
<pubDate>Thu, 19 Nov 2026 12:00:00 GMT</pubDate><source url="https://news.example.com">가상경제</source></item>
<item><title>모의식품, MZ 겨냥 리브랜딩 캠페인 시작 - 모의일보</title><link>https://news.example.com/a6</link>
<pubDate>Thu, 19 Nov 2026 12:30:00 GMT</pubDate><source url="https://news.example.org">모의일보</source></item>
<item><title>오늘 날씨 맑음 - 모의일보</title><link>https://news.example.com/a7</link>
<pubDate>Thu, 19 Nov 2026 12:40:00 GMT</pubDate><source url="https://news.example.org">모의일보</source></item>
</channel></rss>"""
