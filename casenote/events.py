"""공시 목록을 사례 유형별로 나누고, 주요사항보고서 상세 항목을 읽기 좋은 형태로 정리한다."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .dart import DartClient, DartError, DartFatalError, viewer_url
from .util import fmt_krw, fmt_pct, md_cell, parse_amount, parse_percent, pct, safe_div

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    pattern: str
    group: str  # restructuring / ma / capital / ipo / business / other
    card: str | None = None
    endpoint: str | None = None  # 주요사항보고서 상세 API
    weight: float = 3.0


# 위에서부터 먼저 맞는 규칙을 쓴다(분할합병 → 분할·합병, 유무상증자 → 유상·무상 순서가 중요)
RULES: list[Rule] = [
    Rule("split_merger", "분할합병", r"분할합병결정", "restructuring", "split", "cmpDvmgDecsn", 10),
    Rule("merger", "합병", r"회사합병결정", "restructuring", "merger", "cmpMgDecsn", 10),
    Rule("split", "분할", r"회사분할결정", "restructuring", "split", "cmpDvDecsn", 10),
    Rule("share_exchange", "주식교환·이전", r"주식(의포괄적)?교환.?이전결정|주식교환결정|주식이전결정", "restructuring", "share_exchange", "stkExtrDecsn", 9),
    Rule("tender_offer", "공개매수", r"공개매수신고서|공개매수결과보고서", "ma", "tender_offer", None, 9),
    Rule("control_change", "최대주주 변경", r"최대주주변경", "ma", "stock_acquisition", None, 7),
    Rule("stock_acq", "타법인 주식 취득", r"타법인주식및출자증권(양수|취득)결정", "ma", "stock_acquisition", "otcprStkInvscrInhDecsn", 8),
    Rule("stock_trf", "타법인 주식 처분", r"타법인주식및출자증권(양도|처분)결정", "ma", "stock_acquisition", "otcprStkInvscrTrfDecsn", 7),
    Rule("business_acq", "영업양수", r"영업양수결정", "ma", "business_transfer", "bsnInhDecsn", 8),
    Rule("business_trf", "영업양도", r"영업양도결정", "ma", "business_transfer", "bsnTrfDecsn", 8),
    Rule("asset_acq", "유형자산 양수", r"유형자산양수결정", "ma", "business_transfer", "tgastInhDecsn", 5),
    Rule("asset_trf", "유형자산 양도", r"유형자산양도결정", "ma", "business_transfer", "tgastTrfDecsn", 5),
    Rule("ipo", "IPO(공모)", r"증권신고서\(지분증권\)", "ipo", "ipo", "estkRs", 9),
    Rule("rights_bonus", "유무상증자", r"유무상증자결정", "capital", "rights_offering", "pifricDecsn", 6),
    Rule("rights_offering", "유상증자", r"유상증자결정", "capital", "rights_offering", "piicDecsn", 6),
    Rule("bonus_issue", "무상증자", r"무상증자결정", "capital", "bonus_issue", "fricDecsn", 4),
    Rule("capital_reduction", "감자", r"감자결정", "capital", "capital_reduction", "crDecsn", 6),
    Rule("treasury_trust", "자사주 신탁계약", r"자기주식취득신탁계약체결결정", "capital", "treasury_stock", "tsstkAqTrctrCnsDecsn", 4),
    Rule("treasury_buy", "자사주 취득", r"자기주식취득결정", "capital", "treasury_stock", "tsstkAqDecsn", 5),
    Rule("treasury_sell", "자사주 처분", r"자기주식처분결정", "capital", "treasury_stock", "tsstkDpDecsn", 5),
    Rule("treasury_cancel", "자사주 소각", r"주식소각결정", "capital", "treasury_stock", None, 6),
    Rule("cb", "전환사채(CB)", r"전환사채권발행결정", "capital", "mezzanine", "cvbdIsDecsn", 5),
    Rule("bw", "신주인수권부사채(BW)", r"신주인수권부사채권발행결정", "capital", "mezzanine", "bdwtIsDecsn", 5),
    Rule("eb", "교환사채(EB)", r"교환사채권발행결정", "capital", "mezzanine", "exbdIsDecsn", 5),
    Rule("valueup", "밸류업(기업가치 제고)", r"기업가치제고계획", "business", "shareholder_return", None, 5),
    Rule("dividend", "배당 결정", r"현금.?현물배당결정|분기.?반기배당결정", "business", "shareholder_return", None, 2),
    Rule("earnings", "잠정실적·실적변동", r"영업\(잠정\)실적|매출액또는손익구조", "business", "earnings", None, 3),
    Rule("contract", "수주·공급계약", r"단일판매.?공급계약체결", "business", "contract", None, 3),
    Rule("insolvency", "부실·회생", r"부도발생|회생절차개시신청|영업정지|해산사유발생|채권은행등의관리절차개시", "other", "insolvency", None, 7),
]

GROUP_LABELS = {
    "restructuring": "구조 개편(합병·분할·주식교환)",
    "ma": "M&A·지분·사업 양수도",
    "ipo": "IPO",
    "capital": "자본 거래(증자·감자·자사주·메자닌)",
    "business": "실적·수주·주주환원",
    "other": "부실·위험 신호",
}

_PREFIX = re.compile(r"^\[([^\]]+)\]")
_COMPILED = [(r, re.compile(r.pattern)) for r in RULES]
RULES_BY_KEY = {r.key: r for r in RULES}

# 공시 유형별로 같이 읽을 경영·경제 이론(data/knowledge/theories의 id). 앞에 있을수록 먼저 쓴다.
RULE_THEORIES: dict[str, list[str]] = {
    "merger": ["ma_synergy", "scale_scope_learning", "agency_theory"],
    "split_merger": ["conglomerate_discount", "org_structure", "agency_theory"],
    "split": ["conglomerate_discount", "agency_theory", "org_structure"],
    "share_exchange": ["agency_theory", "org_structure", "valuation"],
    "tender_offer": ["agency_theory", "game_theory", "ma_synergy"],
    "control_change": ["agency_theory", "ma_synergy"],
    "stock_acq": ["ma_synergy", "ansoff_diversification", "vertical_integration"],
    "stock_trf": ["bcg_portfolio", "conglomerate_discount"],
    "business_acq": ["ma_synergy", "value_chain", "rbv_vrio"],
    "business_trf": ["bcg_portfolio", "rbv_vrio"],
    "asset_acq": ["scale_scope_learning", "value_chain"],
    "asset_trf": ["capital_structure", "bcg_portfolio"],
    "ipo": ["ipo_underpricing", "valuation", "signaling"],
    "rights_bonus": ["signaling", "capital_structure"],
    "rights_offering": ["signaling", "capital_structure"],
    "bonus_issue": ["behavioral_econ", "signaling"],
    "capital_reduction": ["capital_structure", "signaling"],
    "treasury_trust": ["payout_policy", "signaling"],
    "treasury_buy": ["payout_policy", "signaling"],
    "treasury_sell": ["signaling", "payout_policy"],
    "treasury_cancel": ["payout_policy", "valuation"],
    "cb": ["capital_structure", "signaling"],
    "bw": ["capital_structure", "signaling"],
    "eb": ["capital_structure", "signaling"],
    "valueup": ["payout_policy", "valuation", "agency_theory"],
    "dividend": ["payout_policy", "signaling"],
    "earnings": ["operating_leverage", "generic_strategy"],
    "contract": ["operating_leverage", "business_cycle"],
    "insolvency": ["capital_structure", "operating_leverage"],
}


def classify_report(report_nm: str) -> tuple[Rule | None, bool]:
    """보고서명 → (규칙, 정정 여부). 공백과 [기재정정] 같은 머리말을 떼고 판단한다."""
    name = re.sub(r"\s+", "", report_nm or "")
    is_correction = False
    while True:
        m = _PREFIX.match(name)
        if not m:
            break
        if "정정" in m.group(1) or "추가" in m.group(1):
            is_correction = True
        name = name[m.end():]
    for rule, rx in _COMPILED:
        if rx.search(name):
            return rule, is_correction
    return None, is_correction


# --------------------------------------------------------------------- 상세 항목 정의
# (키, 표시 이름, 형식) 형식: text, krw(큰 금액), won(주당 가격), shares, pct, long
DETAIL_FIELDS: dict[str, list[tuple[str, str, str]]] = {
    "cmpMgDecsn": [
        ("mg_stn", "합병형태", "text"), ("mg_mth", "합병방법", "text"),
        ("mgptncmp_cmpnm", "합병상대회사", "text"), ("mgptncmp_mbsn", "상대회사 주요사업", "text"),
        ("mgptncmp_rl_cmpn", "회사와의 관계", "text"), ("mg_rt", "합병비율", "text"),
        ("rbsnfdtl_tast", "상대회사 자산총계", "krw"), ("rbsnfdtl_tdbt", "상대회사 부채총계", "krw"),
        ("rbsnfdtl_sl", "상대회사 매출액", "krw"), ("rbsnfdtl_nic", "상대회사 당기순이익", "krw"),
        ("mgnstk_ostk_cnt", "합병신주(보통주)", "shares"), ("exevl_intn", "외부평가기관", "text"),
        ("aprskh_plnprc", "주식매수청구가격", "text"), ("mgsc_mgdt", "합병기일", "text"),
        ("bdlst_atn", "우회상장 해당 여부", "text"), ("bddd", "이사회 결의일", "text"),
        ("mg_pp", "합병 목적", "long"), ("mg_rt_bs", "합병비율 산출근거", "long"),
    ],
    "cmpDvDecsn": [
        ("dv_mth", "분할방법", "text"), ("dv_rt", "분할비율", "text"),
        ("dvfcmp_cmpnm", "분할설립회사", "text"), ("dvfcmp_mbsn", "신설회사 주요사업", "text"),
        ("dvfcmp_nbsn_rsl", "신설사업부문 매출액", "krw"), ("ffdtl_tast", "신설회사 자산총계", "krw"),
        ("ffdtl_tdbt", "신설회사 부채총계", "krw"), ("atdv_excmp_cmpnm", "분할존속회사", "text"),
        ("atdv_excmp_exbsn_rsl", "존속사업부문 매출액", "krw"), ("atdvfdtl_tast", "분할 후 존속회사 자산총계", "krw"),
        ("dvfcmp_rlst_atn", "신설회사 재상장 신청 여부", "text"), ("dvdt", "분할기일", "text"),
        ("bddd", "이사회 결의일", "text"),
        ("dv_trfbsnprt_cn", "분할로 이전할 사업과 재산", "long"), ("dv_impef", "분할의 영향과 효과", "long"),
    ],
    "cmpDvmgDecsn": [
        ("dvmg_mth", "분할합병 방법", "text"), ("mgptncmp_cmpnm", "분할합병 상대회사", "text"),
        ("mgptncmp_mbsn", "상대회사 주요사업", "text"), ("mgptncmp_rl_cmpn", "회사와의 관계", "text"),
        ("dvmg_rt", "분할합병 비율", "text"), ("rbsnfdtl_tast", "상대회사 자산총계", "krw"),
        ("rbsnfdtl_sl", "상대회사 매출액", "krw"), ("dvfcmp_cmpnm", "분할설립회사", "text"),
        ("ffdtl_tast", "신설회사 자산총계", "krw"), ("dvmgnstk_ostk_cnt", "분할합병 신주(보통주)", "shares"),
        ("dvmgsc_dvmgdt", "분할합병 기일", "text"), ("bddd", "이사회 결의일", "text"),
        ("dv_trfbsnprt_cn", "분할로 이전할 사업과 재산", "long"), ("dvmg_impef", "분할합병의 영향과 효과", "long"),
        ("dvmg_rt_bs", "비율 산출근거", "long"),
    ],
    "stkExtrDecsn": [
        ("extr_sen", "구분", "text"), ("extr_stn", "교환·이전 형태", "text"),
        ("extr_tgcmp_cmpnm", "대상회사", "text"), ("extr_tgcmp_mbsn", "대상회사 주요사업", "text"),
        ("extr_tgcmp_rl_cmpn", "회사와의 관계", "text"), ("extr_rt", "교환·이전 비율", "text"),
        ("rbsnfdtl_tast", "대상회사 자산총계", "krw"), ("rbsnfdtl_teqt", "대상회사 자본총계", "krw"),
        ("atextr_cpcmpnm", "교환·이전 후 완전모회사", "text"), ("extrsc_extrdt", "교환·이전일", "text"),
        ("aprskh_plnprc", "주식매수청구가격", "text"), ("bddd", "이사회 결의일", "text"),
        ("extr_pp", "목적", "long"), ("extr_rt_bs", "비율 산출근거", "long"),
    ],
    "otcprStkInvscrInhDecsn": [
        ("iscmp_cmpnm", "대상회사", "text"), ("iscmp_nt", "국적", "text"), ("iscmp_mbsn", "대상회사 주요사업", "text"),
        ("iscmp_rl_cmpn", "회사와의 관계", "text"), ("inhdtl_stkcnt", "취득 주식 수", "shares"),
        ("inhdtl_inhprc", "취득금액", "krw"), ("inhdtl_tast_vs", "총자산 대비", "pct"),
        ("inhdtl_ecpt_vs", "자기자본 대비", "pct"), ("atinh_eqrt", "취득 후 지분율", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("dl_pym", "대금 지급 방식", "text"),
        ("inh_prd", "취득 예정일", "text"), ("exevl_intn", "외부평가기관", "text"),
        ("ftc_stt_atn", "공정위 신고 대상", "text"), ("bddd", "이사회 결의일", "text"),
        ("inh_pp", "취득 목적", "long"),
    ],
    "otcprStkInvscrTrfDecsn": [
        ("iscmp_cmpnm", "대상회사", "text"), ("iscmp_mbsn", "대상회사 주요사업", "text"),
        ("iscmp_rl_cmpn", "회사와의 관계", "text"), ("trfdtl_stkcnt", "처분 주식 수", "shares"),
        ("trfdtl_trfprc", "처분금액", "krw"), ("trfdtl_tast_vs", "총자산 대비", "pct"),
        ("trfdtl_ecpt_vs", "자기자본 대비", "pct"), ("attrf_eqrt", "처분 후 지분율", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("trf_prd", "처분 예정일", "text"),
        ("bddd", "이사회 결의일", "text"), ("trf_pp", "처분 목적", "long"),
    ],
    "bsnInhDecsn": [
        ("inh_bsn", "양수 영업", "text"), ("inh_prc", "양수가액", "krw"),
        ("ast_rt", "자산액 비중", "pct"), ("sl_rt", "매출액 비중", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("dlptn_rl_cmpn", "회사와의 관계", "text"),
        ("inh_prd_inh_std", "양수 기준일", "text"), ("exevl_intn", "외부평가기관", "text"),
        ("gmtsck_spd_atn", "주총 특별결의 여부", "text"), ("ftc_stt_atn", "공정위 신고 대상", "text"),
        ("bddd", "이사회 결의일", "text"),
        ("inh_bsn_mc", "양수 영업의 주요 내용", "long"), ("inh_pp", "양수 목적", "long"), ("inh_af", "양수 영향", "long"),
    ],
    "bsnTrfDecsn": [
        ("trf_bsn", "양도 영업", "text"), ("trf_prc", "양도가액", "krw"),
        ("ast_rt", "자산액 비중", "pct"), ("sl_rt", "매출액 비중", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("dlptn_rl_cmpn", "회사와의 관계", "text"),
        ("trf_prd_trf_std", "양도 기준일", "text"), ("exevl_intn", "외부평가기관", "text"),
        ("gmtsck_spd_atn", "주총 특별결의 여부", "text"), ("bddd", "이사회 결의일", "text"),
        ("trf_bsn_mc", "양도 영업의 주요 내용", "long"), ("trf_pp", "양도 목적", "long"), ("trf_af", "양도 영향", "long"),
    ],
    "tgastInhDecsn": [
        ("ast_sen", "자산 구분", "text"), ("ast_nm", "자산명", "text"),
        ("inhdtl_inhprc", "양수금액", "krw"), ("inhdtl_tast_vs", "자산총액 대비", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("inh_prd_inh_std", "양수 기준일", "text"),
        ("bddd", "이사회 결의일", "text"), ("inh_pp", "양수 목적", "long"), ("inh_af", "양수 영향", "long"),
    ],
    "tgastTrfDecsn": [
        ("ast_sen", "자산 구분", "text"), ("ast_nm", "자산명", "text"),
        ("trfdtl_trfprc", "양도금액", "krw"), ("trfdtl_tast_vs", "자산총액 대비", "pct"),
        ("dlptn_cmpnm", "거래상대방", "text"), ("trf_prd_trf_std", "양도 기준일", "text"),
        ("bddd", "이사회 결의일", "text"), ("trf_pp", "양도 목적", "long"), ("trf_af", "양도 영향", "long"),
    ],
    "piicDecsn": [
        ("ic_mthn", "증자 방식", "text"), ("nstk_ostk_cnt", "신주(보통주)", "shares"),
        ("nstk_estk_cnt", "신주(기타주식)", "shares"), ("bfic_tisstk_ostk", "증자 전 발행주식(보통주)", "shares"),
        ("fdpp_fclt", "시설자금", "krw"), ("fdpp_bsninh", "영업양수자금", "krw"),
        ("fdpp_op", "운영자금", "krw"), ("fdpp_dtrp", "채무상환자금", "krw"),
        ("fdpp_ocsa", "타법인 증권 취득자금", "krw"), ("fdpp_etc", "기타자금", "krw"),
    ],
    "pifricDecsn": [
        ("piic_ic_mthn", "유상증자 방식", "text"), ("piic_nstk_ostk_cnt", "유상 신주(보통주)", "shares"),
        ("piic_bfic_tisstk_ostk", "증자 전 발행주식(보통주)", "shares"),
        ("piic_fdpp_fclt", "시설자금", "krw"), ("piic_fdpp_op", "운영자금", "krw"),
        ("piic_fdpp_dtrp", "채무상환자금", "krw"), ("piic_fdpp_ocsa", "타법인 증권 취득자금", "krw"),
        ("piic_fdpp_etc", "기타자금", "krw"), ("fric_nstk_ostk_cnt", "무상 신주(보통주)", "shares"),
        ("fric_nstk_ascnt_ps_ostk", "무상 1주당 배정 주식 수", "text"),
    ],
    "fricDecsn": [
        ("nstk_ostk_cnt", "신주(보통주)", "shares"), ("bfic_tisstk_ostk", "증자 전 발행주식(보통주)", "shares"),
        ("nstk_ascnt_ps_ostk", "1주당 배정 주식 수", "text"), ("nstk_asstd", "신주 배정기준일", "text"),
        ("nstk_lstprd", "신주 상장 예정일", "text"), ("bddd", "이사회 결의일", "text"),
    ],
    "crDecsn": [
        ("cr_mth", "감자 방법", "text"), ("cr_rt_ostk", "감자비율(보통주)", "text"),
        ("crstk_ostk_cnt", "감자 주식 수(보통주)", "shares"), ("bfcr_cpt", "감자 전 자본금", "krw"),
        ("atcr_cpt", "감자 후 자본금", "krw"), ("cr_std", "감자 기준일", "text"),
        ("bddd", "이사회 결의일", "text"), ("cr_rs", "감자 사유", "long"),
    ],
    "tsstkAqDecsn": [
        ("aqpln_stk_ostk", "취득 예정 주식(보통주)", "shares"), ("aqpln_prc_ostk", "취득 예정 금액(보통주)", "krw"),
        ("aqexpd_bgd", "취득 기간 시작", "text"), ("aqexpd_edd", "취득 기간 종료", "text"),
        ("aq_mth", "취득 방법", "text"), ("aq_wtn_div_ostk_rt", "취득 전 자사주 비율", "pct"),
        ("aq_dd", "취득 결정일", "text"), ("aq_pp", "취득 목적", "long"),
    ],
    "tsstkAqTrctrCnsDecsn": [
        ("ctr_prc", "신탁 계약금액", "krw"), ("ctr_pd_bgd", "계약 기간 시작", "text"),
        ("ctr_pd_edd", "계약 기간 종료", "text"), ("ctr_cns_int", "계약 체결 기관", "text"),
        ("aq_wtn_div_ostk_rt", "계약 전 자사주 비율", "pct"), ("bddd", "이사회 결의일", "text"),
        ("ctr_pp", "계약 목적", "long"),
    ],
    "tsstkDpDecsn": [
        ("dppln_stk_ostk", "처분 예정 주식(보통주)", "shares"), ("dpstk_prc_ostk", "처분 단가(보통주)", "won"),
        ("dppln_prc_ostk", "처분 예정 금액(보통주)", "krw"), ("dpprpd_bgd", "처분 기간 시작", "text"),
        ("dpprpd_edd", "처분 기간 종료", "text"), ("dp_m_mkt", "시장 매도(주)", "shares"),
        ("dp_m_ovtm", "시간외 대량매매(주)", "shares"), ("dp_m_otc", "장외 처분(주)", "shares"),
        ("dp_dd", "처분 결정일", "text"), ("dp_pp", "처분 목적", "long"),
    ],
    "cvbdIsDecsn": [
        ("bd_tm", "회차", "text"), ("bd_knd", "사채 종류", "text"), ("bd_fta", "발행 총액", "krw"),
        ("bdis_mthn", "발행 방법", "text"), ("bd_intr_ex", "표면이자율(%)", "text"),
        ("bd_intr_sf", "만기이자율(%)", "text"), ("bd_mtd", "만기일", "text"),
        ("cv_prc", "전환가액(원)", "text"), ("cvisstk_cnt", "전환 시 발행 주식 수", "shares"),
        ("cvisstk_tisstk_vs", "발행주식총수 대비", "pct"), ("act_mktprcfl_cvprc_lwtrsprc", "최저 조정가액(원)", "text"),
        ("cvrqpd_bgd", "전환 청구 시작", "text"), ("bddd", "이사회 결의일", "text"),
    ],
    "bdwtIsDecsn": [
        ("bd_tm", "회차", "text"), ("bd_fta", "발행 총액", "krw"), ("bdis_mthn", "발행 방법", "text"),
        ("bd_intr_ex", "표면이자율(%)", "text"), ("bd_intr_sf", "만기이자율(%)", "text"),
        ("bd_mtd", "만기일", "text"), ("ex_prc", "행사가액(원)", "text"),
        ("nstk_isstk_cnt", "행사 시 발행 주식 수", "shares"), ("nstk_isstk_tisstk_vs", "발행주식총수 대비", "pct"),
        ("bdwt_div_atn", "사채·신주인수권 분리 여부", "text"), ("bddd", "이사회 결의일", "text"),
    ],
    "exbdIsDecsn": [
        ("bd_tm", "회차", "text"), ("bd_fta", "발행 총액", "krw"), ("bdis_mthn", "발행 방법", "text"),
        ("bd_intr_ex", "표면이자율(%)", "text"), ("bd_intr_sf", "만기이자율(%)", "text"),
        ("bd_mtd", "만기일", "text"), ("ex_prc", "교환가액(원)", "text"), ("extg", "교환 대상", "text"),
        ("extg_stkcnt", "교환 대상 주식 수", "shares"), ("extg_tisstk_vs", "발행주식총수 대비", "pct"),
        ("bddd", "이사회 결의일", "text"),
    ],
}

# 사례 크기를 대표하는 금액 항목
AMOUNT_KEYS: dict[str, tuple[str, list[str]]] = {
    "otcprStkInvscrInhDecsn": ("취득금액", ["inhdtl_inhprc"]),
    "otcprStkInvscrTrfDecsn": ("처분금액", ["trfdtl_trfprc"]),
    "bsnInhDecsn": ("양수가액", ["inh_prc"]),
    "bsnTrfDecsn": ("양도가액", ["trf_prc"]),
    "tgastInhDecsn": ("양수금액", ["inhdtl_inhprc"]),
    "tgastTrfDecsn": ("양도금액", ["trfdtl_trfprc"]),
    "piicDecsn": ("조달금액", ["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]),
    "pifricDecsn": ("유상 조달금액", ["piic_fdpp_fclt", "piic_fdpp_bsninh", "piic_fdpp_op", "piic_fdpp_dtrp", "piic_fdpp_ocsa", "piic_fdpp_etc"]),
    "tsstkAqDecsn": ("취득 예정 금액", ["aqpln_prc_ostk", "aqpln_prc_estk"]),
    "tsstkAqTrctrCnsDecsn": ("신탁 계약금액", ["ctr_prc"]),
    "tsstkDpDecsn": ("처분 예정 금액", ["dppln_prc_ostk", "dppln_prc_estk"]),
    "cvbdIsDecsn": ("발행 총액", ["bd_fta"]),
    "bdwtIsDecsn": ("발행 총액", ["bd_fta"]),
    "exbdIsDecsn": ("발행 총액", ["bd_fta"]),
    "cmpMgDecsn": ("상대회사 자산", ["rbsnfdtl_tast"]),
    "cmpDvDecsn": ("신설회사 자산", ["ffdtl_tast"]),
    "cmpDvmgDecsn": ("상대회사 자산", ["rbsnfdtl_tast"]),
    "stkExtrDecsn": ("대상회사 자산", ["rbsnfdtl_tast"]),
}


@dataclass
class Event:
    rule: Rule
    rcept_no: str
    rcept_dt: str
    corp_code: str
    corp_name: str
    stock_code: str
    corp_cls: str
    report_nm: str
    is_correction: bool = False
    detail: dict = field(default_factory=dict)
    facts: list[tuple[str, str]] = field(default_factory=list)
    long_facts: list[tuple[str, str]] = field(default_factory=list)
    amount: float | None = None
    amount_label: str | None = None
    notes: list[str] = field(default_factory=list)
    fin: dict | None = None
    size_class: str | None = None
    score: float = 0.0
    related_news: list = field(default_factory=list)
    same_day_count: int = 1

    @property
    def url(self) -> str:
        return viewer_url(self.rcept_no)

    @property
    def market(self) -> str:
        return {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "비상장"}.get(self.corp_cls, self.corp_cls or "-")

    @property
    def title(self) -> str:
        return f"{self.corp_name} {self.rule.label}"

    def to_dict(self) -> dict:
        return {
            "type": self.rule.key,
            "label": self.rule.label,
            "corp_name": self.corp_name,
            "stock_code": self.stock_code,
            "market": self.market,
            "rcept_no": self.rcept_no,
            "rcept_dt": self.rcept_dt,
            "report_nm": self.report_nm,
            "amount": self.amount,
            "amount_label": self.amount_label,
            "notes": self.notes,
            "score": round(self.score, 2),
            "url": self.url,
        }


def build_events(filings: list[dict], markets: list[str]) -> list[Event]:
    """공시 목록 → 사례 목록. 철회 공시는 빼고, 같은 회사·같은 유형은 가장 최근 것만 남긴다."""
    events: dict[tuple[str, str], Event] = {}
    for f in filings:
        rm = str(f.get("rm") or "")
        if "철" in rm:
            continue
        rule, is_corr = classify_report(str(f.get("report_nm", "")))
        if not rule:
            continue
        cls = str(f.get("corp_cls") or "")
        if rule.key == "ipo":
            if cls != "E":  # 상장사의 지분증권 신고서는 유상증자(주요사항보고서)로 이미 잡힌다
                continue
        elif cls not in markets:
            continue
        ev = Event(
            rule=rule,
            rcept_no=str(f.get("rcept_no", "")),
            rcept_dt=str(f.get("rcept_dt", "")),
            corp_code=str(f.get("corp_code", "")),
            corp_name=str(f.get("corp_name", "")),
            stock_code=str(f.get("stock_code") or "").strip(),
            corp_cls=cls,
            report_nm=str(f.get("report_nm", "")),
            is_correction=is_corr,
        )
        key = (ev.corp_code, rule.key)
        prev = events.get(key)
        if prev is None or ev.rcept_no > prev.rcept_no:
            if prev is not None:
                ev.same_day_count = prev.same_day_count + 1
            events[key] = ev
        else:
            prev.same_day_count += 1
    return list(events.values())


def _fmt_value(raw, kind: str) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s in {"", "-", "해당사항없음", "해당없음"}:
        return None
    if kind == "krw":
        n = parse_amount(s)
        return fmt_krw(n) if n is not None and n != 0 else None
    if kind == "won":
        n = parse_amount(s)
        return f"{n:,.0f}원" if n else None
    if kind == "shares":
        n = parse_amount(s)
        return f"{n:,.0f}주" if n else None
    if kind == "pct":
        n = parse_percent(s)
        return fmt_pct(n, 2) if n is not None else None
    if kind == "long":
        return md_cell(s)[:400]
    return md_cell(s)[:120]


def summarize_detail(ev: Event) -> None:
    """상세 항목(raw dict)을 표시용 facts와 대표 금액으로 정리한다."""
    endpoint = ev.rule.endpoint
    d = ev.detail or {}
    if not endpoint or not d:
        return
    for key, label, kind in DETAIL_FIELDS.get(endpoint, []):
        val = _fmt_value(d.get(key), kind)
        if val is None:
            continue
        if kind == "long":
            ev.long_facts.append((label, val))
        else:
            ev.facts.append((label, val))
    if endpoint in AMOUNT_KEYS:
        label, keys = AMOUNT_KEYS[endpoint]
        total = 0.0
        found = False
        for k in keys:
            n = parse_amount(d.get(k))
            if n:
                total += n
                found = True
        if found:
            ev.amount = total
            ev.amount_label = label
    _derive_notes(ev)


def _derive_notes(ev: Event) -> None:
    d = ev.detail
    key = ev.rule.key
    if key == "split":
        mth = str(d.get("dv_mth") or "")
        if "물적" in mth:
            ev.notes.append("물적분할: 신설회사 주식을 기존 회사가 100% 갖는다(연결 실체는 그대로).")
        elif "인적" in mth:
            ev.notes.append("인적분할: 신설회사 주식을 기존 주주가 지분율대로 나눠 받는다.")
    if key in {"rights_offering", "rights_bonus"}:
        prefix = "piic_" if key == "rights_bonus" else ""
        new = parse_amount(d.get(f"{prefix}nstk_ostk_cnt"))
        before = parse_amount(d.get(f"{prefix}bfic_tisstk_ostk"))
        dil = pct(new, before)
        if dil is not None:
            ev.notes.append(f"신주가 기존 발행주식의 {dil:.1f}%(지분 희석 크기).")
        method = str(d.get(f"{prefix}ic_mthn") or "")
        if "제3자" in method:
            ev.notes.append("제3자배정: 발행가 할인 한도 10%, 정관 근거와 경영상 목적이 필요하다.")
        elif "일반공모" in method:
            ev.notes.append("일반공모: 발행가 할인 한도 30%.")
        if ev.amount:
            op = sum(parse_amount(d.get(f"{prefix}{k}")) or 0 for k in ("fdpp_op", "fdpp_dtrp"))
            share = safe_div(op, ev.amount)
            if share is not None and share >= 0.5:
                ev.notes.append(f"조달금액의 {share * 100:.0f}%가 운영·채무상환 자금(투자보다 버티기 성격이 강한 증자).")
    if key == "treasury_buy":
        purpose = str(d.get("aq_pp") or "")
        if "소각" in purpose:
            ev.notes.append("취득 목적에 '소각'이 들어 있다(주주환원 효과가 확실한 편).")
    if key in {"cb", "bw", "eb"}:
        coupon = parse_amount(d.get("bd_intr_ex"))
        if coupon is not None and coupon == 0:
            ev.notes.append("표면이자율 0%: 투자자는 이자 대신 주가 상승에 따른 전환·행사 차익을 노린다.")
        method = str(d.get("bdis_mthn") or "")
        if "사모" in method:
            ev.notes.append("사모 발행: 리픽싱 하한 70% 규정과 콜옵션 조건을 확인할 것.")
    if key == "bonus_issue":
        per = d.get("nstk_ascnt_ps_ostk")
        if per:
            ev.notes.append(f"1주당 {md_cell(per)}주를 새로 받는다(권리락으로 주가가 조정된다).")
    if key == "capital_reduction":
        mth = str(d.get("cr_mth") or "") + str(d.get("cr_rs") or "")
        if "결손" in mth or "무상" in mth:
            ev.notes.append("결손 보전 성격의 무상감자로 보인다(자본잠식 해소 목적인지 확인).")


def attach_details(client: DartClient, events: list[Event], bgn_de: str, end_de: str) -> int:
    """주요사항보고서 상세 API를 불러 사례에 붙인다. 돌려준 값은 호출 실패 건수."""
    failures = 0
    cache: dict[tuple[str, str], list[dict]] = {}
    for ev in events:
        ep = ev.rule.endpoint
        if not ep:
            continue
        if ev.rule.key == "ipo":
            try:
                groups = client.registration(ep, ev.corp_code, bgn_de, end_de)
                ev.detail = {"_groups": groups}
                summarize_ipo(ev)
            except DartFatalError:
                raise
            except DartError as exc:
                failures += 1
                log.warning("증권신고서 상세 실패 %s: %s", ev.corp_name, exc)
            continue
        if "주요사항보고서" not in ev.report_nm:
            continue  # 거래소 수시공시 등은 상세 API가 없다
        key = (ep, ev.corp_code)
        if key not in cache:
            try:
                cache[key] = client.event_detail(ep, ev.corp_code, bgn_de, end_de)
            except DartFatalError:
                raise
            except DartError as exc:
                failures += 1
                log.warning("상세 조회 실패 %s %s: %s", ev.corp_name, ep, exc)
                cache[key] = []
        rows = cache[key]
        if not rows and ev.is_correction:
            # 정정 공시는 상세 API에 원래 공시의 접수번호·접수일로 남아 있는 경우가 많아 90일 앞까지 넓혀 찾는다
            wide = (ep, ev.corp_code, "wide")
            if wide not in cache:
                wide_bgn = (datetime.strptime(bgn_de, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
                try:
                    cache[wide] = client.event_detail(ep, ev.corp_code, wide_bgn, end_de)
                except DartFatalError:
                    raise
                except DartError as exc:
                    failures += 1
                    log.warning("정정 공시 상세 조회 실패 %s %s: %s", ev.corp_name, ep, exc)
                    cache[wide] = []
            rows = cache[wide]
        match = next((r for r in rows if str(r.get("rcept_no")) == ev.rcept_no), None)
        if match is None and rows:
            match = sorted(rows, key=lambda r: str(r.get("rcept_no", "")))[-1]
        if match:
            ev.detail = match
            summarize_detail(ev)
    return failures


_IPO_KEYS = {
    "stkcnt": ("공모 주식 수", "shares"),
    "fv": ("액면가", "won"),
    "slprc": ("공모가(모집가액)", "won"),
    "slta": ("공모 총액", "krw"),
    "slmthn": ("모집 방법", "text"),
    "sbd": ("청약일", "text"),
    "pymd": ("납입일", "text"),
}


def summarize_ipo(ev: Event) -> None:
    groups: dict = ev.detail.get("_groups", {})
    seen: set[str] = set()
    for title, rows in groups.items():
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key, (label, kind) in _IPO_KEYS.items():
                if label in seen:
                    continue
                val = _fmt_value(row.get(key), kind)
                if val:
                    ev.facts.append((label, val))
                    seen.add(label)
            if "인수" in title:
                name = row.get("actnmn")
                if name and "인수인" not in seen:
                    ev.facts.append(("인수인(주관사 등)", md_cell(name)))
                    seen.add("인수인")
    for title, rows in groups.items():
        for row in rows if isinstance(rows, list) else []:
            n = parse_amount(row.get("slta")) if isinstance(row, dict) else None
            if n:
                ev.amount = n
                ev.amount_label = "공모 총액"
                return


# 대표 금액이 상대 회사의 '자산 규모'인 유형(돈이 오가는 금액이 아님)
ASSET_LIKE = {"cmpMgDecsn", "cmpDvDecsn", "cmpDvmgDecsn", "stkExtrDecsn"}

# 관련 기사를 고를 때 제목에 있어야 할 단어
NEWS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "merger": ("합병",), "split_merger": ("분할", "합병"), "split": ("분할", "분사"),
    "share_exchange": ("교환", "이전", "자회사", "100%"), "tender_offer": ("공개매수",),
    "control_change": ("최대주주", "경영권", "인수", "매각"), "stock_acq": ("인수", "지분", "취득"),
    "stock_trf": ("매각", "지분", "처분"), "business_acq": ("양수", "인수"), "business_trf": ("양도", "매각"),
    "asset_acq": ("취득", "매입", "양수"), "asset_trf": ("매각", "양도", "처분"), "ipo": ("상장", "공모", "IPO", "수요예측"),
    "rights_bonus": ("증자",), "rights_offering": ("유상증자", "증자"), "bonus_issue": ("무상증자", "증자"),
    "capital_reduction": ("감자",), "treasury_trust": ("자사주", "자기주식"), "treasury_buy": ("자사주", "자기주식"),
    "treasury_sell": ("자사주", "자기주식", "처분"), "treasury_cancel": ("소각", "자사주"), "cb": ("전환사채", "CB"),
    "bw": ("신주인수권", "BW"), "eb": ("교환사채", "EB"), "valueup": ("밸류업", "가치 제고", "주주환원"),
    "dividend": ("배당",), "earnings": ("실적", "영업이익", "매출"), "contract": ("계약", "수주", "공급"),
    "insolvency": ("회생", "부도", "영업정지", "해산"),
}


def related_for(ev: Event, company_news: list) -> list:
    words = NEWS_KEYWORDS.get(ev.rule.key, ())
    return [n for n in company_news if any(w in n.title for w in words)]


def context_notes(ev: Event) -> list[str]:
    """회사 재무와 거래 금액을 비교한 '숫자로 보기' 문장."""
    out: list[str] = []
    fin = ev.fin or {}
    assets = fin.get("assets")
    equity = fin.get("equity")
    revenue = fin.get("revenue")
    year = fin.get("year")
    tail = f" ({year}년 기준)" if year else ""
    if ev.amount and ev.rule.endpoint in ASSET_LIKE:
        if assets:
            out.append(f"{ev.amount_label} {fmt_krw(ev.amount)} = 우리 회사 총자산의 {pct(ev.amount, assets):.1f}%{tail}")
        else:
            out.append(f"{ev.amount_label} {fmt_krw(ev.amount)}")
        other_rev = parse_amount(ev.detail.get("rbsnfdtl_sl")) or parse_amount(ev.detail.get("dvfcmp_nbsn_rsl"))
        if other_rev and revenue:
            who = "신설 사업부문" if ev.rule.key == "split" else "상대회사"
            out.append(f"{who} 매출 {fmt_krw(other_rev)} = 우리 회사 매출의 {pct(other_rev, revenue):.1f}%")
    elif ev.amount and (assets or equity):
        # 공시 원문에 비율이 있으면 그 숫자를 그대로 쓴다(공시는 직전 재무 기준이라 사업보고서로 다시 계산하면 다를 수 있다)
        labels = {label for label, _ in ev.facts}
        parts = []
        if assets and not labels & {"총자산 대비", "자산총액 대비"}:
            parts.append(f"총자산의 {pct(ev.amount, assets):.1f}%")
        if equity and equity > 0 and "자기자본 대비" not in labels:
            parts.append(f"자기자본의 {pct(ev.amount, equity):.1f}%")
        if parts:
            out.append(f"{ev.amount_label} {fmt_krw(ev.amount)} = " + ", ".join(parts) + tail)
    elif ev.amount:
        out.append(f"{ev.amount_label} {fmt_krw(ev.amount)}")
    if revenue:
        out.append(f"회사 규모: 매출 {fmt_krw(revenue)}, 총자산 {fmt_krw(assets)}" + (f" — {ev.size_class}" if ev.size_class else ""))
    return out


def score_event(ev: Event, watchlist: set[str]) -> float:
    s = ev.rule.weight
    s += {"Y": 2.0, "K": 1.0, "E": 1.0}.get(ev.corp_cls, 0.0)
    if ev.corp_name in watchlist or ev.stock_code in watchlist:
        s += 6
    if ev.is_correction:
        s -= 2.5
    if ev.facts:
        s += 1.5  # 상세 항목이 있어야 공부할 거리가 많다
    fin = ev.fin or {}
    assets = fin.get("assets")
    if assets:
        if assets >= 1e13:
            s += 3
        elif assets >= 1e12:
            s += 2
        elif assets >= 1e11:
            s += 1
    if ev.amount and assets:
        ratio = ev.amount / assets
        if ratio >= 0.10:
            s += 3
        elif ratio >= 0.05:
            s += 2
        elif ratio >= 0.01:
            s += 1
    elif ev.amount and ev.amount >= 1e11:
        s += 1.5
    ev.score = s
    return s


def pick_key_cases(events: list[Event], n: int) -> list[Event]:
    """점수 순으로 고르되 같은 유형·같은 회사가 몰리지 않게 한다."""
    ranked = sorted(events, key=lambda e: e.score, reverse=True)
    picked: list[Event] = []

    def take(require_new_type: bool, require_new_corp: bool) -> None:
        for ev in ranked:
            if len(picked) >= n:
                return
            if ev in picked:
                continue
            if require_new_type and any(p.rule.key == ev.rule.key for p in picked):
                continue
            if require_new_corp and any(p.corp_code == ev.corp_code for p in picked):
                continue
            picked.append(ev)

    take(True, True)
    take(True, False)
    take(False, False)
    return picked
