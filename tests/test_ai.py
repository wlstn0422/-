"""AI 해설 경로를 가짜 Anthropic 클라이언트로 검증한다(네트워크·과금 없음)."""

import json
import sys
import types
from datetime import date

from casenote import report

from fake_data import FakeDart


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, payload, stop="end_turn"):
        self.stop_reason = stop
        self.content = [_Block(json.dumps(payload, ensure_ascii=False))]
        self.usage = types.SimpleNamespace(input_tokens=1000, output_tokens=500)


def _install_fake_anthropic(monkeypatch, captured, stop="end_turn"):
    mod = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        status_code = 500
        message = "x"

    for name in ("AuthenticationError", "RateLimitError", "APIConnectionError"):
        setattr(mod, name, type(name, (Exception,), {}))
    mod.APIStatusError = APIStatusError

    class _Stream:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return self._resp

    class _Messages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            data = json.loads(kwargs["messages"][0]["content"].split("\n\n", 1)[1])
            payload = {"cases": [{
                "rcept_no": c["rcept_no"], "one_line": f"{c['company']} 사례 요약", "why": ["가설 하나"],
                "numbers": ["숫자 하나"], "accounting": ["회계 하나"], "tax": ["세무 하나"],
                "say_it": "한 문장 정리", "questions": ["질문 하나"],
            } for c in data["filings"]], "news": [{
                "id": n["id"], "one_line": "뉴스 요약", "theory_view": [f"{n['theory']['name']}로 보면"],
                "implications": ["시사점 하나"], "questions": ["확인 질문"],
            } for n in data["news"]]}
            return _Stream(_Resp(payload, stop))

    class Anthropic:
        def __init__(self, **kwargs):
            self.beta = types.SimpleNamespace(messages=_Messages())

    mod.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def _news():
    from casenote.news import dedupe, parse_feed
    from fake_data import GOOGLE_NEWS_RSS
    return dedupe(parse_feed(GOOGLE_NEWS_RSS.encode("utf-8"), origin="구글뉴스")), []


def test_ai_commentary_in_report(settings, monkeypatch):
    captured = {}
    _install_fake_anthropic(monkeypatch, captured)
    settings.anthropic_api_key = "test-key"
    settings.config["ai"]["enabled"] = "auto"
    out = report.run_daily(settings, date(2026, 11, 20), client=FakeDart(), news_fetcher=_news)
    md = out.read_text(encoding="utf-8")
    assert "**AI 해설**" in md
    assert "한 문장 요약: 한 문장 정리" in md
    assert "이론의 적용:" in md and "시사점: 시사점 하나" in md
    assert captured["model"] == "claude-opus-5-5"
    assert captured["fallbacks"] == "default"
    assert captured["max_tokens"] >= 32000
    # 노트에 실린 뉴스 사례가 모두 해설 대상이다
    sent = json.loads(captured["messages"][0]["content"].split("\n\n", 1)[1])
    assert len(sent["news"]) == md.count("\n### 1-")
    assert md.count("\n- 이론의 적용:") == len(sent["news"])  # AI 해설 줄(무료 해설의 번호 목록과 구분)
    assert captured["output_config"]["format"]["type"] == "json_schema"


def test_ai_refusal_is_skipped(settings, monkeypatch):
    _install_fake_anthropic(monkeypatch, {}, stop="refusal")
    settings.anthropic_api_key = "test-key"
    settings.config["ai"]["enabled"] = "auto"
    out = report.run_daily(settings, date(2026, 11, 20), client=FakeDart(), news_fetcher=_news)
    assert "AI 해설" not in out.read_text(encoding="utf-8")
