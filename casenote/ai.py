"""(선택) Claude로 핵심 사례 해설을 쓴다. ANTHROPIC_API_KEY가 있을 때만 동작한다."""

from __future__ import annotations

import json
import logging

from .util import fmt_krw

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """너는 기업 재무와 M&A 실무를 10년 넘게 한 선배다. 함께 공부하는 후배는 경영학과 학생이고, 회계사·세무사 시험을 5년 준비해서 K-IFRS와 법인세법 기본기가 탄탄하다. 매일 아침 전날 나온 공시 사례를 같이 뜯어보는 자리라고 생각하고 해설을 쓴다.

지킬 것:
- 주어진 자료(공시 항목, 회사 재무 숫자, 기사 제목)만 사실로 다룬다. 자료에 없는 사실을 만들지 않는다. 추측은 '추정'이라고 분명히 밝힌다.
- 기준서·조문 번호는 확실할 때만 붙이고, 애매하면 원칙만 쓴다.
- 이모지, 과장된 수식어, 뻔한 맺음말 없이 동료에게 말하듯 짧고 분명한 한국어로 쓴다.
- 금액은 조·억 단위로 읽기 쉽게 쓴다.
- 각 항목은 한두 문장으로, 학생이 바로 실무 감각으로 옮길 수 있게 쓴다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rcept_no": {"type": "string"},
                    "one_line": {"type": "string"},
                    "why": {"type": "array", "items": {"type": "string"}},
                    "numbers": {"type": "array", "items": {"type": "string"}},
                    "accounting": {"type": "array", "items": {"type": "string"}},
                    "tax": {"type": "array", "items": {"type": "string"}},
                    "say_it": {"type": "string"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["rcept_no", "one_line", "why", "numbers", "accounting", "tax", "say_it", "questions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}


def _case_payload(ev) -> dict:
    fin = ev.fin or {}
    return {
        "rcept_no": ev.rcept_no,
        "company": ev.corp_name,
        "market": ev.market,
        "type": ev.rule.label,
        "report_name": ev.report_nm,
        "filed": ev.rcept_dt,
        "facts": dict(ev.facts),
        "excerpts": dict(ev.long_facts),
        "derived": ev.notes,
        "company_financials": {
            k: fmt_krw(v) for k, v in fin.items()
            if k in {"revenue", "operating_income", "net_income", "assets", "liabilities", "equity", "revenue_prev"} and v is not None
        } | ({"year": fin.get("year")} if fin.get("year") else {}),
        "size": ev.size_class,
        "related_headlines": [n.title for n in ev.related_news][:3],
    }


def commentary(events: list, settings) -> dict[str, dict]:
    """핵심 사례 해설. 돌려주는 값: {접수번호: 해설}. 실패하면 빈 dict."""
    if not events or not settings.ai_enabled:
        return {}
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic 패키지가 없어 AI 해설을 건너뜀(pip install anthropic)")
        return {}
    cfg = settings.config.get("ai", {})
    payload = [_case_payload(ev) for ev in events[: int(cfg.get("max_cases", 3))]]
    user = (
        "아래 공시 사례마다 해설을 써줘. 각 사례의 rcept_no를 그대로 돌려주고, 항목별로 2~3개씩만.\n"
        "- one_line: 무슨 일인지 한 문장\n"
        "- why: 회사가 이 결정을 한 이유 가설(추정이면 추정이라고)\n"
        "- numbers: 회사 규모 대비 거래 크기, 희석, 부채비율 영향처럼 숫자로 본 의미\n"
        "- accounting: K-IFRS 관점 회계처리 포인트\n"
        "- tax: 법인세·상증세 등 세무 포인트\n"
        "- say_it: 회의나 면접에서 이 사례를 한두 문장으로 말한다면\n"
        "- questions: 스스로 더 생각해볼 질문\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=300)
    try:
        resp = client.beta.messages.create(
            model=cfg.get("model", "claude-opus-5-5"),
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg.get("effort", "medium"), "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        log.warning("ANTHROPIC_API_KEY가 올바르지 않아 AI 해설을 건너뜀")
        return {}
    except anthropic.RateLimitError:
        log.warning("Claude API 요청 한도에 걸려 AI 해설을 건너뜀")
        return {}
    except anthropic.APIStatusError as exc:
        log.warning("Claude API 오류(%s)로 AI 해설을 건너뜀: %s", exc.status_code, exc.message)
        return {}
    except anthropic.APIConnectionError:
        log.warning("Claude API 연결 실패로 AI 해설을 건너뜀")
        return {}
    if resp.stop_reason == "refusal":
        log.warning("모델이 요청을 거절해 AI 해설을 건너뜀")
        return {}
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        log.warning("AI 해설 응답을 해석하지 못함(stop_reason=%s)", resp.stop_reason)
        return {}
    usage = getattr(resp, "usage", None)
    if usage is not None:
        log.info("AI 해설 토큰 사용: 입력 %s, 출력 %s", getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"))
    return {c["rcept_no"]: c for c in data.get("cases", []) if c.get("rcept_no")}
