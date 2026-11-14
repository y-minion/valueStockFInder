from pathlib import Path

import pytest

from vsf.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def template_path() -> Path:
    path = load_settings(ROOT / "settings.toml").calculator_path
    if not path.exists():
        pytest.skip("원본 계산기 파일이 없어요")
    return path
