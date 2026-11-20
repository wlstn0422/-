"""명령줄 실행: python -m casenote <명령>

  daily     오늘의 케이스 노트 만들기(기본)
  company   기업 하나를 깊게 분석      예) python -m casenote company 삼성전자
  scale     업종별 규모 지도 다시 만들기
  weekly    지난 7일 복습 노트
  site      reports/ 를 docs/ 웹페이지로 변환
  doctor    키와 네트워크 연결 점검
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from . import report
from .settings import load_settings
from .site import build_site
from .util import parse_ymd


def _date(s: str) -> date:
    d = parse_ymd(s)
    if not d:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식으로 적어 주세요")
    return d


def cmd_doctor(settings) -> int:
    from .dart import DartClient, DartError
    from .news import fetch

    ok = True
    print("[설정] config.yaml 읽기: 정상")
    if settings.dart_api_key:
        client = DartClient(settings.dart_api_key, cache_dir=None)
        try:
            info = client.company("00126380")  # 삼성전자 고유번호
            print(f"[DART] 키 정상 (테스트 조회: {info.get('corp_name', '응답 확인')})")
        except DartError as exc:
            ok = False
            print(f"[DART] 실패: {exc}")
    else:
        ok = False
        print("[DART] DART_API_KEY 없음: 공시·재무 기능이 꺼진 채로 실행됩니다")
    feeds = settings.news_sources.get("feeds", [])[:2]
    for f in feeds:
        try:
            size = len(fetch(f["url"], 10))
            print(f"[뉴스] {f['name']}: 정상 ({size:,} bytes)")
        except Exception as exc:  # 진단용
            ok = False
            print(f"[뉴스] {f['name']}: 실패 ({exc})")
    print("[AI 해설] " + ("사용 (ANTHROPIC_API_KEY 있음)" if settings.ai_enabled else "사용 안 함"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="casenote", description="매일 기업 케이스 노트")
    parser.add_argument("-v", "--verbose", action="store_true", help="자세한 로그")
    sub = parser.add_subparsers(dest="cmd")

    p_daily = sub.add_parser("daily", help="오늘의 노트 만들기")
    p_daily.add_argument("--date", type=_date, help="리포트 날짜(기본: 오늘, 한국시간)")
    p_daily.add_argument("--no-news", action="store_true", help="뉴스 수집 건너뛰기")
    p_daily.add_argument("--no-dart", action="store_true", help="DART 건너뛰기")
    p_daily.add_argument("--no-ai", action="store_true", help="AI 해설 건너뛰기")
    p_daily.add_argument("--out", help="리포트를 이 폴더에만 저장(기록·목차는 건드리지 않음)")
    p_daily.add_argument("--no-site", action="store_true", help="웹페이지 변환 생략")

    p_company = sub.add_parser("company", help="기업 하나 분석")
    p_company.add_argument("query", help="회사 이름 또는 종목코드")
    p_company.add_argument("--year", type=int, help="사업연도(기본: 최신 사업보고서)")

    p_scale = sub.add_parser("scale", help="업종별 규모 지도")
    p_scale.add_argument("--year", type=int, help="사업연도")
    p_scale.add_argument("--no-rebuild", action="store_true", help="저장된 자료로 표만 다시 만들기")

    p_weekly = sub.add_parser("weekly", help="주간 복습 노트")
    p_weekly.add_argument("--date", type=_date)

    sub.add_parser("site", help="docs/ 웹페이지 다시 만들기")
    sub.add_parser("doctor", help="연결 점검")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("urllib3", "markdown", "httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = load_settings()
    cmd = args.cmd or "daily"

    if cmd == "doctor":
        return cmd_doctor(settings)
    if cmd == "daily":
        out = report.run_daily(
            settings,
            getattr(args, "date", None),
            use_news=not getattr(args, "no_news", False),
            use_dart=not getattr(args, "no_dart", False),
            use_ai=not getattr(args, "no_ai", False),
            out_dir=getattr(args, "out", None),
        )
        print(f"리포트: {out}")
        if not getattr(args, "out", None) and not getattr(args, "no_site", False):
            build_site(settings)
    elif cmd == "company":
        out = report.run_company(settings, args.query, args.year)
        print(f"기업 분석: {out}")
        build_site(settings)
    elif cmd == "scale":
        out = report.run_scale(settings, args.year, rebuild=not args.no_rebuild)
        print(f"규모 지도: {out}")
        build_site(settings)
    elif cmd == "weekly":
        out = report.run_weekly(settings, args.date)
        print(f"주간 복습: {out}" if out else "지난 7일 기록이 없어 만들지 않았습니다.")
        build_site(settings)
    elif cmd == "site":
        pages = build_site(settings)
        print(f"웹페이지 {len(pages)}개 생성: {settings.docs_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
