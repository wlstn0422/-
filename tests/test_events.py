from casenote.events import RULES_BY_KEY, Event, build_events, classify_report, pick_key_cases, summarize_detail

from fake_data import DETAILS, FILINGS


def test_classify_report_names():
    cases = {
        "주요사항보고서(회사합병결정)": ("merger", False),
        "[기재정정]주요사항보고서(회사분할합병결정)": ("split_merger", True),
        "주요사항보고서(회사분할결정)": ("split", False),
        "주요사항보고서(유무상증자결정)": ("rights_bonus", False),
        "주요사항보고서(유상증자결정)": ("rights_offering", False),
        "주요사항보고서(자기주식취득신탁계약체결결정)": ("treasury_trust", False),
        "주요사항보고서(자기주식취득결정)": ("treasury_buy", False),
        "주요사항보고서(타법인주식및출자증권양수결정)": ("stock_acq", False),
        "주식소각결정": ("treasury_cancel", False),
        "단일판매ㆍ공급계약체결": ("contract", False),
        "[기재정정]단일판매ㆍ공급계약체결(자율공시)": ("contract", True),
        "연결재무제표기준영업(잠정)실적(공정공시)": ("earnings", False),
        "매출액또는손익구조30%(대규모법인은15%)이상변경": ("earnings", False),
        "기업가치제고계획(자율공시)": ("valueup", False),
        "주식등의 대량보유상황보고서(일반)": (None, False),
        "증권신고서(지분증권)": ("ipo", False),
        "[발행조건확정]증권신고서(지분증권)": ("ipo", False),
    }
    for name, (key, corr) in cases.items():
        rule, is_corr = classify_report(name)
        assert (rule.key if rule else None) == key, name
        assert is_corr == corr, name


def test_build_events_filters_and_dedupes():
    filings = FILINGS["B"] + FILINGS["I"] + FILINGS["C"]
    events = build_events(filings, ["Y", "K"])
    keys = {(e.corp_name, e.rule.key) for e in events}
    assert ("가상바이오", "cb") not in keys  # 철회 공시 제외
    assert ("예시물산", "ipo") in keys  # 비상장사 증권신고서는 IPO로
    assert ("샘플화학", "treasury_buy") in keys
    tsb = next(e for e in events if e.rule.key == "treasury_buy")
    assert tsb.is_correction


def test_summarize_rights_offering():
    f = FILINGS["B"][1]
    ev = Event(rule=RULES_BY_KEY["rights_offering"], rcept_no=f["rcept_no"], rcept_dt=f["rcept_dt"], corp_code=f["corp_code"],
               corp_name=f["corp_name"], stock_code=f["stock_code"], corp_cls=f["corp_cls"], report_nm=f["report_nm"])
    ev.detail = DETAILS[("piicDecsn", "90000003")][0]
    summarize_detail(ev)
    assert ev.amount == 75_000_000_000
    labels = dict(ev.facts)
    assert labels["증자 방식"].startswith("주주배정")
    assert any("20.0%" in n for n in ev.notes)  # 희석률 5백만/2천5백만
    assert any("운영·채무상환" in n for n in ev.notes)


def test_summarize_split_notes():
    f = FILINGS["B"][3]
    ev = Event(rule=RULES_BY_KEY["split"], rcept_no=f["rcept_no"], rcept_dt=f["rcept_dt"], corp_code=f["corp_code"],
               corp_name=f["corp_name"], stock_code=f["stock_code"], corp_cls=f["corp_cls"], report_nm=f["report_nm"])
    ev.detail = DETAILS[("cmpDvDecsn", "90000002")][0]
    summarize_detail(ev)
    assert any("물적분할" in n for n in ev.notes)
    assert ev.amount == 600_000_000_000


def test_pick_key_cases_diversity():
    events = build_events(FILINGS["B"] + FILINGS["I"], ["Y", "K"])
    for i, e in enumerate(events):
        e.score = 10 - i
    picked = pick_key_cases(events, 3)
    assert len(picked) == 3
    assert len({e.rule.key for e in picked}) == 3


def test_context_notes_prefer_official_ratios():
    from casenote.events import context_notes
    ev = Event(rule=RULES_BY_KEY["stock_acq"], rcept_no="1", rcept_dt="20261120", corp_code="9", corp_name="모의바이오",
               stock_code="999999", corp_cls="K", report_nm="주요사항보고서(타법인주식및출자증권양수결정)")
    ev.amount = 8e9
    ev.amount_label = "취득금액"
    ev.fin = {"year": 2025, "assets": 48.4e9, "equity": 13.5e9, "revenue": 12.9e9}
    ev.facts = [("취득금액", "80억원"), ("총자산 대비", "16.53%"), ("자기자본 대비", "20.03%")]
    notes = context_notes(ev)
    assert not any("자기자본의" in n or "총자산의" in n for n in notes)  # 공시 원문 비율과 다른 숫자를 만들지 않는다
    assert any(n.startswith("회사 규모") for n in notes)
    ev.facts = [("취득금액", "80억원")]
    notes = context_notes(ev)
    assert any("자기자본의 59.3%" in n for n in notes)  # 원문에 비율이 없으면 직접 계산


def test_correction_details_found_with_wider_window():
    from casenote.events import attach_details

    class _Client:
        def __init__(self):
            self.windows = []

        def event_detail(self, endpoint, corp_code, bgn_de, end_de):
            self.windows.append((bgn_de, end_de))
            if bgn_de == end_de:  # 정정일 하루로는 안 나오고, 원래 공시일까지 넓히면 나온다
                return []
            return [{"rcept_no": "20261105000111", "nstk_ostk_cnt": "1000000", "fdpp_op": "3000000000"}]

    ev = Event(rule=RULES_BY_KEY["rights_offering"], rcept_no="20261120000617", rcept_dt="20261120", corp_code="9",
               corp_name="모의산업", stock_code="999999", corp_cls="K",
               report_nm="[기재정정]주요사항보고서(유상증자결정)", is_correction=True)
    client = _Client()
    attach_details(client, [ev], "20261120", "20261120")
    assert client.windows == [("20261120", "20261120"), ("20260822", "20261120")]
    assert ev.detail.get("rcept_no") == "20261105000111"
