"""설정 파일(config.yaml)과 데이터 파일, 환경변수를 읽는다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "report": {
        "title": "매일 기업 케이스 노트",
        "key_cases": 3,
        "news_per_category": 5,
        "filings_per_type": 12,
        "markets": ["Y", "K"],
        "max_window_days": 7,
    },
    "watchlist": [],
    "dart": {"request_interval_sec": 0.2, "scale_refresh_days": 30, "include_employees": True},
    "news": {"lookback_hours": 30, "timeout_sec": 15},
    "ai": {"enabled": "auto", "model": "claude-opus-5-5", "effort": "medium", "max_cases": 3},
}


def _merge(base: dict, override: dict | None) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    root: Path = ROOT
    config: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG))
    dart_api_key: str | None = None
    anthropic_api_key: str | None = None

    # 경로
    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs"

    @property
    def archive_dir(self) -> Path:
        return self.root / "data" / "archive"

    @property
    def generated_dir(self) -> Path:
        return self.root / "data" / "generated"

    # 데이터 파일
    @cached_property
    def cards(self) -> list[dict]:
        return load_yaml(self.data_dir / "knowledge" / "cards.yaml")

    @cached_property
    def benchmarks(self) -> dict:
        return load_yaml(self.data_dir / "benchmarks.yaml")

    @cached_property
    def industries(self) -> list[dict]:
        return load_yaml(self.data_dir / "industries.yaml").get("industries", [])

    @cached_property
    def news_sources(self) -> dict:
        return load_yaml(self.data_dir / "news_sources.yaml")

    # 편의 속성
    @property
    def report_cfg(self) -> dict:
        return self.config["report"]

    @property
    def ai_enabled(self) -> bool:
        flag = self.config.get("ai", {}).get("enabled", "auto")
        if flag is False or str(flag).lower() in {"false", "off", "no"}:
            return False
        return bool(self.anthropic_api_key)


def load_settings(root: Path | None = None) -> Settings:
    root = Path(root) if root else ROOT
    cfg_path = root / "config.yaml"
    user_cfg = load_yaml(cfg_path) if cfg_path.exists() else {}
    config = _merge(DEFAULT_CONFIG, user_cfg if isinstance(user_cfg, dict) else {})
    return Settings(
        root=root,
        config=config,
        dart_api_key=(os.environ.get("DART_API_KEY") or "").strip() or None,
        anthropic_api_key=(os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None,
    )
