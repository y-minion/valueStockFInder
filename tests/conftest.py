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


RECORDED_SKIP = "실제 API 녹화 자료가 아직 없어요 (keys.toml 준비 후 tools/record_fixtures.py 실행)"


def pytest_collection_modifyitems(config, items):
    """@pytest.mark.recorded 테스트는 녹화 폴더가 비어 있으면 건너뛰어요."""
    def has_recorded(item) -> bool:
        source = Path(str(item.fspath)).stem.removeprefix("test_")  # test_dart.py -> dart
        folder = ROOT / "tests" / "fixtures" / source / "recorded"
        return folder.is_dir() and any(folder.iterdir())

    skip = pytest.mark.skip(reason=RECORDED_SKIP)
    for item in items:
        if "recorded" in item.keywords and not has_recorded(item):
            item.add_marker(skip)
