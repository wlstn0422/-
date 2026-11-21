"""(선택) Claude로 공시 사례와 뉴스 사례 해설을 쓴다. ANTHROPIC_API_KEY가 있을 때만 동작한다."""

from __future__ import annotations

import json
import logging

from .util import fmt_krw

log = logging.getLogger(__name__)

# 실행 기록에 대략의 비용을 남기기 위한 단가(달러/100만 토큰, 입력·출력). 2026년 11월 공식 요금표 기준
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}

SYSTEM_PROMPT = """너는 기업재무·인수합병·경영전략·마케팅·경제학과 회계·세법·상법·재정학을 두루 다루는 경영학 교과서의 저자다. 독자는 경영학과 학생으로, 회계사·세무사 시험을 준비하며 K-IFRS, 원가관리회계, 세법, 상법, 재정학의 기본기를 갖추었다. 전날 공시와 기사를 사례로 삼아, 사례를 경영학·경제학 이론과 제도로 설명하는 교과서의 '사례 연구' 단락을 쓴다고 생각하고 해설을 작성한다.

지킬 것:
- 경영학·경제학 교과서의 문체로 쓴다. 문장은 '~이다', '~한다', '~된다'로 끝내고, 구어체와 경어체('~입니다', '~보세요')를 쓰지 않는다.
- 전문용어는 정확하게 쓰되, 처음 나오는 용어는 괄호 안에 짧게 정의한다.
- 주어진 자료(공시 항목, 회사 재무 수치, 기사 제목과 요약)만 사실로 다룬다. 자료에 없는 사실을 만들지 않는다. 기사 본문은 받지 않았으므로 제목으로 확인되지 않는 내용은 '추정된다'고 명시한다.
- 이론은 명칭만 제시하지 말고 이 사례에 어떻게 적용되는지(또는 어디서 들어맞지 않는지) 구체적으로 서술한다.
- 기준서·조문 번호는 확실할 때만 제시하고, 불확실하면 원칙만 서술한다.
- 세법·상법·재정 기사(분야가 회계·감사, 지배구조·상법, 세금·세법, 재정·예산·복지인 것)는 그 제도의 입법 취지와, 누구의 부담이나 행동이 어떻게 달라지는지(경제적 효과)를 한 문장씩 서술한다. 시행 시기와 수치는 자료에 있을 때만 쓴다.
- 금액은 조·억 단위로 표기한다. 각 항목은 한두 문장으로 간결하게 쓴다."""

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
    limit = int(cfg.get("max_cases", 4))  # 노트에 실리는 사례 수(공시 3건, 뉴스 4건)를 모두 덮는다
    payload = {
        "filings": [_case_payload(ev) for ev in events[:limit]],
        "news": [_news_payload(nc) for nc in news_cases[:limit]],
    }
    user = (
        "아래 공시 사례(filings)와 뉴스 사례(news)마다 교과서 문체로 해설을 작성하라. 항목별로 2~3개씩만 쓴다.\n"
        "공시 사례는 rcept_no를 그대로 돌려주고 다음을 작성한다.\n"
        "- one_line: 사례의 요지를 한 문장으로\n"
        "- why: 회사가 이 결정을 한 동기에 관한 가설(전략·재무·지배구조 관점, 추정이면 추정이라고 명시)\n"
        "- numbers: 회사 규모 대비 거래 규모, 지분 희석, 부채비율 영향 등 수치 분석\n"
        "- accounting: K-IFRS 관점의 회계처리 쟁점\n"
        "- tax: 법인세·상속세및증여세 등 세무 쟁점\n"
        "- say_it: 이 사례를 한두 문장으로 요약한 서술\n"
        "- questions: 추가로 검토할 과제\n"
        "뉴스 사례는 id를 그대로 돌려주고 다음을 작성한다.\n"
        "- one_line: 기사 제목으로 확인되는 요지를 한 문장으로\n"
        "- theory_view: 주어진 theory를 이 기사에 적용한 분석(steps 순서를 따르고, 들어맞지 않는 부분이 있으면 함께 서술)\n"
        "- implications: 기업·산업·소비자에 대한 시사점\n"
        "- questions: 기사 본문에서 확인할 검토 과제(numbers_to_check 활용)\n"
        "자료가 비어 있는 쪽은 빈 배열로 돌려준다.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=600)
    model = cfg.get("model", "claude-opus-5-5")
    try:
        # 생각하는 데 쓴 토큰과 한국어 해설 7건을 합치면 길어질 수 있어 출력 한도를 넉넉히 두고,
        # 긴 응답도 시간 초과 없이 받도록 스트리밍으로 받는다. 요금은 실제로 쓴 토큰만큼만 나간다.
        extra = {}
        if not str(model).startswith("claude-haiku"):  # Haiku에는 거절 시 다른 모델로 넘기는 기능이 없다
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg.get("effort", "medium"), "format": {"type": "json_schema", "schema": SCHEMA}},
            **extra,
        ) as stream:
            resp = stream.get_final_message()
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
    usage = getattr(resp, "usage", None)
    if usage is not None:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        price = PRICES.get(getattr(resp, "model", model) or model)
        cost = f", 약 {(inp * price[0] + out * price[1]) / 1e6:.2f}달러" if price else ""
        log.info("AI 해설 토큰 사용: 입력 %s, 출력 %s%s", f"{inp:,}", f"{out:,}", cost)
    if resp.stop_reason == "refusal":
        log.warning("모델이 요청을 거절해 AI 해설을 건너뜀")
        return empty
    if resp.stop_reason == "max_tokens":
        log.warning("AI 해설이 출력 한도에 걸려 잘려서 건너뜀")
        return empty
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        log.warning("AI 해설 응답을 해석하지 못함(stop_reason=%s)", resp.stop_reason)
        return empty
    return {
        "cases": {c["rcept_no"]: c for c in data.get("cases", []) if c.get("rcept_no")},
        "news": {n["id"]: n for n in data.get("news", []) if n.get("id")},
    }
