import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from casenote.settings import load_settings  # noqa: E402

TEST_INDUSTRIES = """
industries:
  - name: 전자
    profile: "테스트용 업종 설명. 고정비가 크고 경기에 따라 이익이 크게 움직인다."
    theories: [scale_scope_learning, operating_leverage]
    companies:
      - {name: 테스트전자, code: "900001"}
      - {name: 모의반도체, code: "900005"}
  - name: 화학
    companies:
      - {name: 샘플화학, code: "900002"}
  - name: 바이오
    companies:
      - {name: 가상바이오, code: "900003"}
"""

TEST_CONFIG = """
report:
  key_cases: 3
watchlist: []
ai:
  enabled: false
"""


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "data" / "knowledge").mkdir(parents=True)
    shutil.copy(ROOT / "data" / "knowledge" / "cards.yaml", tmp_path / "data" / "knowledge" / "cards.yaml")
    shutil.copy(ROOT / "data" / "benchmarks.yaml", tmp_path / "data" / "benchmarks.yaml")
    shutil.copy(ROOT / "data" / "news_sources.yaml", tmp_path / "data" / "news_sources.yaml")
    shutil.copytree(ROOT / "data" / "knowledge" / "theories", tmp_path / "data" / "knowledge" / "theories")
    (tmp_path / "data" / "industries.yaml").write_text(TEST_INDUSTRIES, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(TEST_CONFIG, encoding="utf-8")
    return load_settings(tmp_path)
