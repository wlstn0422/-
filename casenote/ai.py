"""(선택) Claude로 공시 사례와 뉴스 사례 해설을 쓴다. ANTHROPIC_API_KEY가 있을 때만 동작한다."""

from __future__ import annotations

import json
import logging

from .util import fmt_krw

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """너는 기업 재무·M&A 실무와 경영전략·마케팅·경제 분석, 회계·세법·상법·재정 분야를 두루 10년 넘게 다뤄 온 선배다. 함께 공부하는 후배는 경영학과 학생이고, 회계사·세무사 시험을 5년 준비해서 K-IFRS, 원가관리회계, 세법, 상법, 재정학 기본기가 탄탄하다. 매일 아침 전날 나온 공시와 기사를 같이 뜯어보며, 사례를 경영학·경제학 이론과 제도로 설명해 주는 자리라고 생각하고 해설을 쓴다.

지킬 것:
- 주어진 자료(공시 항목, 회사 재무 숫자, 기사 제목과 요약)만 사실로 다룬다. 자료에 없는 사실을 만들지 않는다. 기사 본문은 받지 않았으니 제목에서 확인되지 않는 내용은 '추정'이라고 분명히 밝힌다.
- 이론은 이름만 대지 말고 이 사례에 어떻게 들어맞는지(또는 어디서 안 맞는지) 구체적으로 쓴다.
- 기준서·조문 번호는 확실할 때만 붙이고, 애매하면 원칙만 쓴다.
- 세법·상법·재정 기사(뉴스의 분야가 회계·감사, 지배구조·상법, 세금·세법, 재정·예산·복지인 것)는 그 제도가 왜 생겼는지(입법 취지), 누구의 부담이나 행동이 어떻게 바뀌는지(경제적 효과)를 한 줄씩 짚는다. 시행 시기와 수치는 자료에 있을 때만 쓴다.
- 이모지, 과장된 수식어, 뻔한 맺음말 없이 동료에게 말하듯 짧고 분명한 한국어로 쓴다.
- 금액은 조·억 단위로 읽기 쉽게 쓴다. 각 항목은 한두 문장으로 쓴다."""

_STR_LIST = {"type": "array", "items": {"type": "string"}}

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
                    "why": _STR_LIST,
                    "numbers": _STR_LIST,
                    "accounting": _STR_LIST,
                    "tax": _STR_LIST,
                    "say_it": {"type": "string"},
                    "questions": _STR_LIST,
                },
                "required": ["rcept_no", "one_line", "why", "numbers", "accounting", "tax", "say_it", "questions"],
                "additionalProperties": False,
            },
        },
        "news": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "one_line": {"type": "string"},
                    "theory_view": _STR_LIST,
                    "implications": _STR_LIST,
                    "questions": _STR_LIST,
                },
                "required": ["id", "one_line", "theory_view", "implications", "questions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cases", "news"],
    "additionalProperties": False,
}


def _case_payload(ev) -> dict:
    fin = ev.fin or {}
    money = {k: fmt_krw(v) for k, v in fin.items()
             if k in {"revenue", "operating_income", "net_income", "assets", "liabilities", "equity", "revenue_prev"} and v is not None}
    if fin.get("year"):
        money["year"] = fin.get("year")
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
        "company_financials": money,
        "size": ev.size_class,
        "related_headlines": [n.title for n in ev.related_news][:3],
    }


def _news_payload(nc) -> dict:
    item = nc["item"]
    theory = nc["theory"]
    return {
        "id": nc["id"],
        "headline": item.title,
        "summary": item.summary,
        "source": item.source,
        "outlets_covering": item.coverage,
        "field": nc["category"]["label"],
        "theory": {"name": theory["title"], "definition": theory["one_line"], "steps": theory.get("how_to", [])},
        "other_theories": [t["title"] for t in nc.get("others", [])],
        "numbers_to_check": nc["category"].get("numbers", []),
    }


def commentary(events: list, news_cases: list, settings) -> dict[str, dict]:
    """공시·뉴스 사례 해설. 돌려주는 값: {"cases": {접수번호: 해설}, "news": {뉴스 id: 해설}}. 실패하면 빈 값."""
    empty = {"cases": {}, "news": {}}
    if not (events or news_cases) or not settings.ai_enabled:
        return empty
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic 패키지가 없어 AI 해설을 건너뜀(pip install anthropic)")
        return empty
    cfg = settings.config.get("ai", {})
    limit = int(cfg.get("max_cases", 3))
    payload = {
        "filings": [_case_payload(ev) for ev in events[:limit]],
        "news": [_news_payload(nc) for nc in news_cases[:limit]],
    }
    user = (
        "아래 공시 사례(filings)와 뉴스 사례(news)마다 해설을 써줘. 항목별로 2~3개씩만.\n"
        "공시 사례는 rcept_no를 그대로 돌려주고 다음을 쓴다.\n"
        "- one_line: 무슨 일인지 한 문장\n"
        "- why: 회사가 이 결정을 한 이유 가설(전략·재무·지배구조 관점, 추정이면 추정이라고)\n"
        "- numbers: 회사 규모 대비 거래 크기, 희석, 부채비율 영향처럼 숫자로 본 의미\n"
        "- accounting: K-IFRS 관점 회계처리 포인트\n"
        "- tax: 법인세·상증세 등 세무 포인트\n"
        "- say_it: 회의나 면접에서 이 사례를 한두 문장으로 말한다면\n"
        "- questions: 스스로 더 생각해볼 질문\n"
        "뉴스 사례는 id를 그대로 돌려주고 다음을 쓴다.\n"
        "- one_line: 기사 제목으로 알 수 있는 핵심을 한 문장으로\n"
        "- theory_view: 주어진 theory를 이 기사에 적용한 해석(steps 순서를 따라, 맞지 않는 부분이 있으면 그것도)\n"
        "- implications: 회사·산업·소비자에게 주는 시사점\n"
        "- questions: 기사 본문을 읽으며 확인할 질문(numbers_to_check 활용)\n"
        "자료가 비어 있는 쪽은 빈 배열로 돌려준다.\n\n"
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
        return empty
    except anthropic.RateLimitError:
        log.warning("Claude API 요청 한도에 걸려 AI 해설을 건너뜀")
        return empty
    except anthropic.APIStatusError as exc:
        log.warning("Claude API 오류(%s)로 AI 해설을 건너뜀: %s", exc.status_code, exc.message)
        return empty
    except anthropic.APIConnectionError:
        log.warning("Claude API 연결 실패로 AI 해설을 건너뜀")
        return empty
    if resp.stop_reason == "refusal":
        log.warning("모델이 요청을 거절해 AI 해설을 건너뜀")
        return empty
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        log.warning("AI 해설 응답을 해석하지 못함(stop_reason=%s)", resp.stop_reason)
        return empty
    usage = getattr(resp, "usage", None)
    if usage is not None:
        log.info("AI 해설 토큰 사용: 입력 %s, 출력 %s", getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"))
    return {
        "cases": {c["rcept_no"]: c for c in data.get("cases", []) if c.get("rcept_no")},
        "news": {n["id"]: n for n in data.get("news", []) if n.get("id")},
    }
