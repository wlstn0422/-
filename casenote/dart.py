"""OpenDART API 클라이언트.

- 응답 항목명은 OpenDART 개발가이드 기준(공시검색 list.json, 주요사항보고서 DS005, 재무 DS003 등).
- 키 오류나 하루 한도 초과처럼 계속 호출해도 소용없는 상태가 되면 이번 실행에서는 DART를 끄고 나머지 리포트는 계속 만든다.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api/"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# 정상, 데이터 없음, 그리고 이번 실행을 멈춰야 하는 상태 코드
STATUS_OK = "000"
STATUS_NODATA = "013"
STATUS_FATAL = {
    "010": "등록되지 않은 인증키",
    "011": "사용할 수 없는 인증키",
    "012": "접근할 수 없는 IP",
    "020": "요청 제한 초과(하루 2만 건)",
    "901": "개인정보 보유기간이 지난 키",
}

# 보고서 코드
REPRT_ANNUAL = "11011"
REPRT_HALF = "11012"
REPRT_Q1 = "11013"
REPRT_Q3 = "11014"


class DartError(Exception):
    def __init__(self, status: str, message: str, endpoint: str = ""):
        super().__init__(f"[{status}] {message} ({endpoint})")
        self.status = status
        self.message = message
        self.endpoint = endpoint


class DartFatalError(DartError):
    """키 오류·한도 초과 등 이번 실행에서 DART를 더 쓸 수 없는 상태."""


def to_list(value) -> list:
    """OpenDART는 결과가 1건이면 배열 대신 객체 하나를 주는 경우가 있다."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def viewer_url(rcept_no: str) -> str:
    return VIEWER_URL.format(rcept_no=rcept_no)


@dataclass
class Corp:
    corp_code: str
    corp_name: str
    stock_code: str
    modify_date: str = ""


_NAME_NOISE = re.compile(r"\(주\)|㈜|주식회사|\s")


def normalize_name(name: str) -> str:
    return _NAME_NOISE.sub("", name or "").upper()


class CorpIndex:
    """상장사 종목코드·회사명으로 DART 고유번호(corp_code)를 찾는다."""

    def __init__(self, corps: list[Corp]):
        self.corps = corps
        self.by_stock = {c.stock_code: c for c in corps if c.stock_code}
        self.by_code = {c.corp_code: c for c in corps}
        self.by_norm: dict[str, list[Corp]] = {}
        for c in corps:
            self.by_norm.setdefault(normalize_name(c.corp_name), []).append(c)

    def __len__(self) -> int:
        return len(self.corps)

    def find(self, query: str, aliases: dict[str, str] | None = None) -> Corp | None:
        q = (query or "").strip()
        if not q:
            return None
        if aliases and q in aliases:
            q = aliases[q]
        if re.fullmatch(r"\d{6}", q):
            return self.by_stock.get(q)
        if re.fullmatch(r"\d{8}", q):
            return self.by_code.get(q)
        n = normalize_name(q)
        if n in self.by_norm:
            return self.by_norm[n][0]
        # 부분 일치: 가장 이름이 짧은(가장 가까운) 회사
        hits = [c for key, cs in self.by_norm.items() if n in key for c in cs]
        if hits:
            return sorted(hits, key=lambda c: len(c.corp_name))[0]
        return None


class DartClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path | None = None,
        interval: float = 0.2,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.interval = interval
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "casenote/1.0 (study tool)")
        self.calls = 0
        self.disabled_reason: str | None = None
        self._last_call = 0.0

    # ---------------------------------------------------------------- 저수준
    def _throttle(self) -> None:
        wait = self.interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _http_get(self, endpoint: str, params: dict) -> requests.Response:
        if self.disabled_reason:
            raise DartFatalError("disabled", self.disabled_reason, endpoint)
        query = {"crtfc_key": self.api_key, **{k: v for k, v in params.items() if v not in (None, "")}}
        last_exc: Exception | None = None
        for attempt in range(3):
            self._throttle()
            try:
                self.calls += 1
                resp = self.session.get(BASE_URL + endpoint, params=query, timeout=self.timeout)
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_exc = exc
                time.sleep(1.5 * (2**attempt))
        raise DartError("network", f"DART 접속 실패: {last_exc}", endpoint)

    def _cache_path(self, endpoint: str, params: dict) -> Path | None:
        if not self.cache_dir:
            return None
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(f"{endpoint}|{key}".encode()).hexdigest()[:20]
        return self.cache_dir / "dart" / endpoint.replace(".", "_") / f"{digest}.json"

    def get_json(self, endpoint: str, params: dict, ttl_hours: float | None = None) -> dict:
        path = self._cache_path(endpoint, params) if ttl_hours else None
        if path and path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if time.time() - saved.get("saved_at", 0) < ttl_hours * 3600:
                    return saved["data"]
            except (ValueError, KeyError):
                pass
        resp = self._http_get(endpoint, params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise DartError("parse", f"JSON이 아닌 응답: {resp.text[:120]}", endpoint) from exc
        status = str(data.get("status", ""))
        if status in STATUS_FATAL:
            self.disabled_reason = f"{STATUS_FATAL[status]}: {data.get('message', '')}"
            raise DartFatalError(status, self.disabled_reason, endpoint)
        if status not in (STATUS_OK, STATUS_NODATA):
            raise DartError(status, str(data.get("message", "")), endpoint)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"saved_at": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
        return data

    def get_list(self, endpoint: str, params: dict, ttl_hours: float | None = None) -> list[dict]:
        data = self.get_json(endpoint, params, ttl_hours=ttl_hours)
        if str(data.get("status")) == STATUS_NODATA:
            return []
        return to_list(data.get("list"))

    # ---------------------------------------------------------------- 고유번호
    def corp_index(self, refresh_days: float = 7) -> CorpIndex:
        """상장사 고유번호 목록. 전체 목록(zip)을 받아 상장사만 캐시에 저장한다."""
        cache = self.cache_dir / "corp_codes.json" if self.cache_dir else None
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < refresh_days * 86400:
            rows = json.loads(cache.read_text(encoding="utf-8"))
            return CorpIndex([Corp(**r) for r in rows])
        resp = self._http_get("corpCode.xml", {})
        content = resp.content
        if not content.startswith(b"PK"):
            # 오류는 JSON 또는 XML로 온다
            text = content[:300].decode("utf-8", "ignore")
            status = re.search(r"\"?status\"?\s*[:>]\s*\"?(\d{3})", text)
            code = status.group(1) if status else "parse"
            if code in STATUS_FATAL:
                self.disabled_reason = STATUS_FATAL[code]
                raise DartFatalError(code, self.disabled_reason, "corpCode.xml")
            raise DartError(code, f"고유번호 파일을 받지 못함: {text[:100]}", "corpCode.xml")
        corps = parse_corp_code_zip(content)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([c.__dict__ for c in corps], ensure_ascii=False), encoding="utf-8")
        return CorpIndex(corps)

    # ---------------------------------------------------------------- 공시검색
    def list_filings(
        self,
        bgn_de: str,
        end_de: str,
        pblntf_ty: str | None = None,
        corp_cls: str | None = None,
        corp_code: str | None = None,
        pblntf_detail_ty: str | None = None,
        max_pages: int = 30,
    ) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            data = self.get_json(
                "list.json",
                {
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "pblntf_ty": pblntf_ty,
                    "pblntf_detail_ty": pblntf_detail_ty,
                    "corp_cls": corp_cls,
                    "corp_code": corp_code,
                    "page_no": page,
                    "page_count": 100,
                },
                ttl_hours=1,
            )
            if str(data.get("status")) == STATUS_NODATA:
                break
            out.extend(to_list(data.get("list")))
            total_page = int(data.get("total_page") or 1)
            if page >= total_page:
                break
            page += 1
        return out

    # ---------------------------------------------------------------- 주요사항보고서
    def event_detail(self, endpoint: str, corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
        return self.get_list(endpoint, {"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de}, ttl_hours=24)

    def registration(self, endpoint: str, corp_code: str, bgn_de: str, end_de: str) -> dict:
        """증권신고서 주요정보(DS006). group[] 안에 title, list[]가 들어 있다."""
        data = self.get_json(endpoint, {"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de}, ttl_hours=24)
        groups = {}
        for g in to_list(data.get("group")):
            title = str(g.get("title") or "")
            groups[title] = to_list(g.get("list"))
        if not groups and data.get("list"):
            groups[""] = to_list(data.get("list"))
        return groups

    # ---------------------------------------------------------------- 기업·재무
    def company(self, corp_code: str) -> dict:
        data = self.get_json("company.json", {"corp_code": corp_code}, ttl_hours=24 * 30)
        return data if str(data.get("status")) == STATUS_OK else {}

    def single_accounts(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        return self.get_list(
            "fnlttSinglAcnt.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code},
            ttl_hours=24 * 7,
        )

    def multi_accounts(self, corp_codes: list[str], year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        rows: list[dict] = []
        for i in range(0, len(corp_codes), 50):
            chunk = ",".join(corp_codes[i : i + 50])
            rows.extend(
                self.get_list(
                    "fnlttMultiAcnt.json",
                    {"corp_code": chunk, "bsns_year": str(year), "reprt_code": reprt_code},
                    ttl_hours=24 * 7,
                )
            )
        return rows

    def full_statements(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL, fs_div: str = "CFS") -> list[dict]:
        return self.get_list(
            "fnlttSinglAcntAll.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code, "fs_div": fs_div},
            ttl_hours=24 * 7,
        )

    def employees(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        return self.get_list(
            "empSttus.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code},
            ttl_hours=24 * 7,
        )

    def auditor_opinion(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        return self.get_list(
            "accnutAdtorNmNdAdtOpinion.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code},
            ttl_hours=24 * 7,
        )

    def dividends(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        return self.get_list(
            "alotMatter.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code},
            ttl_hours=24 * 7,
        )

    def major_shareholders(self, corp_code: str, year: int, reprt_code: str = REPRT_ANNUAL) -> list[dict]:
        return self.get_list(
            "hyslrSttus.json",
            {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code},
            ttl_hours=24 * 7,
        )


def parse_corp_code_zip(content: bytes) -> list[Corp]:
    """corpCode.xml(zip) → 상장사(종목코드가 있는 회사)만 추린다."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if not name:
            raise DartError("parse", "zip 안에 XML이 없음", "corpCode.xml")
        xml_bytes = zf.read(name)
    root = ElementTree.fromstring(xml_bytes)
    corps: list[Corp] = []
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if not stock:
            continue
        corps.append(
            Corp(
                corp_code=(item.findtext("corp_code") or "").strip(),
                corp_name=(item.findtext("corp_name") or "").strip(),
                stock_code=stock,
                modify_date=(item.findtext("modify_date") or "").strip(),
            )
        )
    return corps
