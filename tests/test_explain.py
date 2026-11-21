"""쉬운 해설(무료, 규칙 기반)이 공시 유형마다 실제 숫자로 이론을 대입하는지 확인한다."""

from casenote import explain as ex
from casenote.events import RULES, Event, summarize_detail
from casenote.settings import load_settings

RULE = {r.key: r for r in RULES}
FIN = {"year": 2025, "revenue": 129e8, "operating_income": 9e8, "net_income": 7e8, "assets": 484e8,
       "liabilities": 85e8, "equity": 399e8}


def make(key: str, detail: dict, fin: dict | None = None, induty: str = "") -> Event:
    ev = Event(rule=RULE[key], rcept_no="20261120000001", rcept_dt="20261120", corp_code="00000001",
               corp_name="애드바이오텍", stock_code="179530", corp_cls="K", report_nm="주요사항보고서", detail=detail)
    ev.fin = fin if fin is not None else dict(FIN)
    ev.induty_code = induty
    summarize_detail(ev)
    return ev


def text_of(out: dict) -> str:
    return " ".join([out["what"], out["plain"], out.get("size") or "", *out["steps"], out.get("takeaway") or ""])


def test_stock_acquisition_applies_synergy_with_numbers():
    ev = make("stock_acq", {
        "iscmp_cmpnm": "주식회사 드림인사이트 ( DREAMINSIGHT Co,.Ltd).", "iscmp_mbsn": "광고대행업",
        "inhdtl_stkcnt": "3,115,871", "atinh_owstkcnt": "3,115,871", "inhdtl_inhprc": "8,000,000,000",
        "inhdtl_tast_vs": "16.53", "inhdtl_ecpt_vs": "20.03", "atinh_eqrt": "18.55",
        "dl_pym": "1) 대금지급 형태 : 현금 지급 2) 자금조달 방법 : 차입금",
        "inh_pp": "사업 다각화 및 디지털 마케팅 ·온라인 유통 역량 확보",
    }, induty="21102")
    out = ex.explain_filing(ev, {"id": "ma_synergy", "title": "M&A 시너지", "watch": "x"})
    t = text_of(out)
    assert out["what"] == "의약품 제조 기업 애드바이오텍이 드림인사이트(광고대행업)의 주식을 80억원에 취득한다. 취득 후 지분율은 18.55%이다."
    assert "투자 목적의 지분이다" in out["plain"] and "금융자산으로 분류" in out["plain"]
    assert "약 6분의 1(16.5%)" in out["size"] and "차입금으로 조달한다" in out["size"]
    assert "지분 전체 가치를 약 431억원으로 평가한 것이다" in t  # 80억 ÷ 18.55%
    assert "연간 자본비용은 4억원이다" in t  # 연 5% 가정의 손익분기
    assert "매출 시너지" in t
    assert "제약·바이오·의료" in t and "미디어·광고·콘텐츠" in t and "다각화" in t
    assert "지배력:" in t and out["takeaway"].startswith("회사 총자산의 약 6분의 1(16.5%)에 해당하는 자금을 차입금으로 조달하여")
    # 교과서 문체: 경어체와 명령형이 섞이지 않는다
    assert "습니다" not in t and "입니다" not in t and "보세요" not in t


def test_asset_sale_computes_debt_ratio_and_interest_saving():
    fin = {"year": 2025, "revenue": 775e8, "operating_income": 40e8, "assets": 1581e8, "liabilities": 800e8, "equity": 781e8}
    ev = make("asset_trf", {
        "ast_sen": "토지 및 건물", "ast_nm": "본사 사옥", "trfdtl_trfprc": "63,000,000,000", "trfdtl_tast_vs": "39.86",
        "trf_pp": "자산매각을 통한 재무구조 개선, 자산 효율화",
        "trf_af": "매각대금을 활용한 차입금 상환으로 금융비용 절감 및 재무구조 개선이 기대됩니다.",
    }, fin=fin)
    out = ex.explain_filing(ev, None)
    t = text_of(out)
    assert "본사 사옥을 630억원에 매각한다" in out["what"]
    assert "부채비율(부채÷자기자본)은 102%에서 약 22%로 하락한다" in t
    assert "연간 이자비용이 약 32억원 감소한다" in t
    assert "부채를 줄이는 결정이다" in out["takeaway"]
    assert "년분" not in out["size"]  # 매각 거래에는 '연간 영업이익의 몇 년분'을 붙이지 않는다


def test_ipo_reads_counts_with_units():
    ev = make("ipo", {}, fin={})
    ev.facts = [("공모 주식 수", "1,400,000주"), ("공모가(모집가액)", "18,000원")]
    ev.amount, ev.amount_label = 252e8, "공모 총액"
    out = ex.explain_filing(ev, None)
    assert "주식 1,400,000주를 1주당 18,000원에 공모하여 252억원을 조달하고" in out["what"]


def test_rights_offering_dilution_and_use_of_funds():
    ev = make("rights_offering", {
        "ic_mthn": "제3자배정증자", "nstk_ostk_cnt": "5,000,000", "bfic_tisstk_ostk": "25,000,000",
        "fdpp_op": "50,000,000,000", "fdpp_dtrp": "10,000,000,000", "fdpp_fclt": "15,000,000,000",
    })
    t = text_of(ex.explain_filing(ev, None))
    assert "기존 발행주식 수의 20.0%" in t and "약 0.83%로 낮아진다" in t
    assert "80%가 운영자금과 채무상환자금이다" in t
    assert "제3자배정" in t and "신호" in t


def test_mezzanine_refixing_and_private_placement():
    ev = make("cb", {
        "bd_fta": "20,000,000,000", "bdis_mthn": "사모", "bd_intr_ex": "0.0", "cv_prc": "5,000",
        "cvisstk_tisstk_vs": "12.5", "act_mktprcfl_cvprc_lwtrsprc": "3,500",
    })
    t = text_of(ex.explain_filing(ev, None))
    assert "200억원 규모의 전환사채를 발행한다" in t
    assert "1주당 5,000원" in t and "12.5%" in t
    assert "0%" in t and "3,500원까지" in t and "사모" in t


def test_merger_ratio_split_and_others_do_not_fall_back():
    merger = make("merger", {
        "mg_stn": "소규모합병", "mgptncmp_cmpnm": "모의부품", "mgptncmp_mbsn": "전자부품 제조", "mgptncmp_rl_cmpn": "계열회사",
        "mg_rt": "1 : 0.5000000", "rbsnfdtl_tast": "350,000,000,000", "rbsnfdtl_sl": "410,000,000,000",
        "mg_pp": "부품 내재화를 통한 원가 절감",
    }, fin={"year": 2025, "revenue": 12e12, "assets": 10e12, "equity": 6e12, "liabilities": 4e12, "operating_income": 1e12})
    t = text_of(ex.explain_filing(merger, None))
    assert "모의부품(전자부품 제조)과 합병한다(소규모합병)" in t
    assert "동일 기업집단" in t and "비용 시너지" in t and "3.5%" in t
    assert "합병비율(1 : 0.5): 소멸회사 주식 1주당 존속회사 주식 0.5주를 교부한다" in t
    split = make("split", {
        "dv_mth": "물적분할", "dvfcmp_cmpnm": "샘플첨단소재(가칭)", "dvfcmp_mbsn": "첨단소재 제조",
        "dvfcmp_nbsn_rsl": "450,000,000,000", "atdv_excmp_exbsn_rsl": "1,500,000,000,000",
    })
    t = text_of(ex.explain_filing(split, None))
    assert "샘플첨단소재를 신설한다(물적분할)" in t and "쪼개기 상장" in t and "약 4분의 1(23.1%)" in t
    for key, detail, marker in [
        ("bonus_issue", {"nstk_ostk_cnt": "10,000,000", "bfic_tisstk_ostk": "10,000,000", "nstk_ascnt_ps_ostk": "1"}, "약 50% 수준"),
        ("treasury_buy", {"aqpln_prc_ostk": "10,000,000,000", "aq_pp": "주주가치 제고 및 소각"}, "발행주식 수가 실제로 감소"),
        ("stock_trf", {"iscmp_cmpnm": "가상전자", "trfdtl_trfprc": "5,000,000,000", "attrf_eqrt": "0", "trf_pp": "유동성 확보"}, "투자를 완전히 회수한다"),
        ("asset_acq", {"ast_nm": "평택 제2공장", "inhdtl_inhprc": "30,000,000,000", "inh_pp": "생산능력 확대"}, "생산능력 확대이므로"),
        ("capital_reduction", {"cr_mth": "무상감자", "cr_rt_ostk": "90.0"}, "무상감자"),
        ("treasury_sell", {"dppln_prc_ostk": "3,000,000,000", "dp_pp": "임직원 성과보상"}, "임직원 보상을 위한 처분"),
    ]:
        out = ex.explain_filing(make(key, detail), None)
        assert marker in text_of(out), (key, text_of(out))


def test_missing_data_still_gives_plain_explanation():
    ev = make("dividend", {}, fin={})
    out = ex.explain_filing(ev, {"id": "payout_policy", "title": "배당·자사주 정책", "watch": "번 돈을 어디에 쓰는지 보세요."})
    assert "배당 결정" in out["what"] and out["plain"].startswith("배당은")
    assert out["steps"] == ["배당·자사주 정책의 관점: 번 돈을 어디에 쓰는지 보세요."]


def test_share_words_and_josa():
    assert ex.share_words(80, 484) == "약 6분의 1(16.5%)"
    assert ex.share_words(50, 100) == "절반 정도(50%)"
    assert ex.share_words(180, 100) == "1.8배"
    assert ex._eul("약 6분의 1(16.5%)") == "을" and ex._eul("62%") == "를"
    assert ex.clean_name("(주)모의상사") == "모의상사"
    assert ex.clean_name("주식회사 드림인사이트\n( DREAMINSIGHT\nCo,.Ltd).") == "드림인사이트"  # 원문 줄바꿈


def test_news_helpers():
    lead = ex.lead_sentence("(평택=연합뉴스) 최해민 기자 = 반도체 호황에 따른 세수 증가로 경기 평택시가 사상 처음으로 "
                            "4조원대 본예산안을 편성했다. 평택시는 20일", "평택시, 반도체 세수 증가에 본예산안 첫 4조원대")
    assert lead == "반도체 호황에 따른 세수 증가로 경기 평택시가 사상 처음으로 4조원대 본예산안을 편성했다."
    # 요약이 문장 중간에서 잘리면 마지막으로 끝난 절을 문장으로 닫는다
    cut = ex.lead_sentence("다음 주(23∼27일) 기업공개(IPO) 시장에서는 4개 기업이 기관투자자 대상 수요예측을 진행하고, 엠비디가...")
    assert cut == "다음 주(23∼27일) 기업공개(IPO) 시장에서는 4개 기업이 기관투자자 대상 수요예측을 진행한다."
    assert ex.lead_sentence("모의전자의 3분기 영업이익은 전년보다 40% 늘었고, 매출은...") == "모의전자의 3분기 영업이익은 전년보다 40% 늘었다."
    # 닫을 절이 없는 제목형 요약은 쓰지 않는다(제목은 노트에 이미 있다)
    assert ex.lead_sentence("엔비디아 일주일 만에 23% 폭락…SEC 조사·8대 법적 리스크에 위기 더 커지나?") == ""
    assert ex.pct_text(18.55) == "18.55%" and ex.pct_text(18.6) == "18.6%" and ex.pct_text(20.0) == "20%"
    assert ex.number_phrases("2027년 4조원대 본예산안을 편성 4조원대 편성, 20% 인상") == ["4조원대 본예산안", "20% 인상"]
    lines, words = ex.apply_cues("모의식품, MZ 겨냥 리브랜딩", [["겨냥|MZ", "'{m}'{m_eun} 표적시장을 선정한 부분이다."]])
    assert lines == ["'MZ'는 표적시장을 선정한 부분이다."] and words == ["MZ"]


def test_glossary_matching(tmp_path):
    from pathlib import Path
    import shutil
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "data" / "knowledge").mkdir(parents=True)
    shutil.copy(root / "data" / "knowledge" / "glossary.yaml", tmp_path / "data" / "knowledge" / "glossary.yaml")
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    gl = load_settings(tmp_path).glossary
    assert len(gl) >= 120
    hits = [e["term"] for e in ex.glossary_hits("지분법으로 반영하고 지분율은 18%", gl)]
    assert hits == ["지분법", "지분율"]  # '지분법' 안의 '지분'은 지분율로 두 번 세지 않는다
    assert "감자" not in [e["term"] for e in ex.glossary_hits("감자 가격이 올랐다", gl, news=True)]
    seen: set[str] = set()
    first = ex.pick_terms("유상증자와 희석", gl, seen)
    assert [e["term"] for e in first] == ["유상증자", "희석"]
    assert ex.pick_terms("유상증자", gl, seen) == []  # 한 노트에서 같은 용어는 한 번만
    sig = ex.pick_signals("관세 인상 여파", gl, seen, limit=2)
    assert sig and sig[0]["term"] == "관세"
    assert ex.pick_signals("관세 인상 여파", gl, set(), limit=2, skip_words=["관세"]) == [] or \
        all(e["term"] != "관세" for e in ex.pick_signals("관세 인상 여파", gl, set(), limit=2, skip_words=["관세"]))
