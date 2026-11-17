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


# 테스트 파일 이름과 녹화 폴더 이름이 다른 경우: 파일 → 필요한 녹화 폴더들
# (test_accounts.py -> fixtures/dart/recorded, test_assemble.py -> dart와 krx 둘 다).
# 적어 두지 않은 파일은 이름과 같은 폴더 하나예요 (test_dart.py -> fixtures/dart/recorded).
RECORDED_FOLDER = {"accounts": ["dart"], "assemble": ["dart", "krx"]}


def recorded_folders(test_file: Path, args: tuple = ()) -> list[str]:
    """필요한 녹화 폴더 이름들. 마커에 폴더를 적었으면 그것만, 막대 마커면 파일별 규칙이에요."""
    if args:
        return list(args)
    source = test_file.stem.removeprefix("test_")
    return RECORDED_FOLDER.get(source, [source])


def recorded_ready(test_file: Path, fixtures: Path = ROOT / "tests" / "fixtures",
                   args: tuple = ()) -> bool:
    """필요한 녹화 폴더가 모두 있고, 하나도 비어 있지 않으면 True."""
    folders = [fixtures / name / "recorded" for name in recorded_folders(test_file, args)]
    return all(f.is_dir() and any(f.iterdir()) for f in folders)


def pytest_collection_modifyitems(config, items):
    """@pytest.mark.recorded 테스트는 녹화 폴더가 없거나 비어 있으면 건너뛰어요."""
    skip = pytest.mark.skip(reason=RECORDED_SKIP)
    for item in items:
        marker = item.get_closest_marker("recorded")
        if marker is not None and not recorded_ready(Path(str(item.fspath)), args=marker.args):
            item.add_marker(skip)
