"""여러 테스트가 같이 쓰는 도우미."""
import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from vsf.model import (FORMULA_CELLS, Criteria, SheetValues, StockInputs, inputs_from_dict,
                       to_cells)

ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / "tests" / "fixtures" / "oracle"
ORACLE_NAMES: list[str] = sorted(p.stem for p in ORACLE_DIR.glob("*.json"))


def write_settings(tmp_path: Path, criteria: dict[str, str] | None = None,
                   overrides: str | None = None) -> Path:
    """배포용 settings.toml을 tmp_path에 복사하고 해당 줄만 바꿔요.

    criteria: {키: TOML 값 글자}. 이미 있는 키는 줄을 바꾸고, 없는 키는 [criteria] 끝에 넣어요.
    overrides: [industry.overrides] 본문 전체를 이 글자로 바꿔요.
    """
    text = (ROOT / "settings.toml").read_text(encoding="utf-8")
    for key, value in (criteria or {}).items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        if pattern.search(text):
            text = pattern.sub(lambda _: f"{key} = {value}", text, count=1)
        else:
            text = text.replace("\n[report]", f"{key} = {value}\n\n[report]", 1)
    if overrides is not None:
        text = re.sub(r"(\[industry\.overrides\]\n).*?(?=^\[)",
                      lambda m: m.group(1) + overrides + "\n\n", text, count=1, flags=re.S | re.M)
    out = tmp_path / "settings.toml"
    out.write_text(text, encoding="utf-8")
    return out


def load_oracle(name: str) -> tuple[StockInputs, Criteria, SheetValues]:
    """tests/fixtures/oracle/<name>.json → (입력, 기준, 수식 칸 값)."""
    doc = json.loads((ORACLE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return inputs_from_dict(doc["inputs"]), Criteria(**doc["criteria"]), doc["cells"]


def assert_cells_match(got: SheetValues, want: SheetValues, cells: Iterable[str]) -> None:
    """숫자는 상대·절대 1e-9 안에서, 글자와 None은 정확히 같아야 해요. 어긋난 칸을 모두 모아 보여줘요."""
    bad = []
    for addr in cells:
        g, w = got.get(addr), want.get(addr)
        both_num = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (g, w))
        same = math.isclose(g, w, rel_tol=1e-9, abs_tol=1e-9) if both_num else (g == w and type(g) is type(w))
        if not same:
            bad.append(f"{addr}: 나온 값 {g!r} / 기대한 값 {w!r}")
    assert not bad, "칸 값이 달라요:\n" + "\n".join(bad)


def _normalize(v):
    """엑셀에서 읽은 값을 정답 자료와 같은 모양으로: "" → None, 정수 → float, 날짜 → date."""
    if isinstance(v, datetime):
        return v.date()
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return v


def _read(template: Path, sheet: str, addresses: Iterable[str]) -> dict:
    wb = openpyxl.load_workbook(template, data_only=True)
    ws = wb[sheet]
    return {a: _normalize(ws[a].value) for a in addresses}


def input_values(template: Path, sheet: str, exclude: Iterable[str] = ()) -> dict:
    """시트에서 to_cells가 만드는 입력 칸 주소의 값을 읽어요."""
    skip = set(exclude)
    return _read(template, sheet, [a for a in to_cells(StockInputs()) if a not in skip])


def stored_values(template: Path, sheet: str) -> SheetValues:
    """시트에 저장돼 있는 FORMULA_CELLS의 값 (엑셀이 마지막으로 저장한 값)."""
    return _read(template, sheet, FORMULA_CELLS)


def approx_cells(cells: dict, exclude: Iterable[str] = ()) -> dict:
    """to_cells 결과의 숫자를 pytest.approx로 감싸서, 엑셀에서 읽은 값과 == 로 비교할 수 있게 해요."""
    skip = set(exclude)
    return {a: (pytest.approx(float(v), rel=1e-9, abs=1e-9)
                if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for a, v in cells.items() if a not in skip}
