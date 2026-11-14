"""conftest의 녹화 자료 건너뛰기 규칙."""
from pathlib import Path

from conftest import recorded_ready


def _fill(root: Path, source: str) -> None:
    folder = root / source / "recorded"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x.json").write_text("{}", encoding="utf-8")


def test_mapped_file_needs_every_folder(tmp_path):
    assemble = Path("tests/test_assemble.py")
    assert not recorded_ready(assemble, tmp_path)
    _fill(tmp_path, "dart")
    assert not recorded_ready(assemble, tmp_path)            # krx 폴더가 없어요
    (tmp_path / "krx" / "recorded").mkdir(parents=True)
    assert not recorded_ready(assemble, tmp_path)            # krx 폴더가 비었어요
    _fill(tmp_path, "krx")
    assert recorded_ready(assemble, tmp_path)


def test_single_folder_mapping_and_default_kept(tmp_path):
    _fill(tmp_path, "dart")
    assert recorded_ready(Path("tests/test_accounts.py"), tmp_path)   # accounts → dart
    assert recorded_ready(Path("tests/test_dart.py"), tmp_path)       # 적어 두지 않은 파일은 이름과 같은 폴더
    assert not recorded_ready(Path("tests/test_krx.py"), tmp_path)
