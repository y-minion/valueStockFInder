"""원본 계산기를 formulas 라이브러리로 계산해서 사례별 정답 자료(JSON)를 만들어요.

원본 파일은 읽기만 해요. 사례마다 임시 폴더에 복사해서 쓰고 지워요.
"""
import json
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "tests", ROOT):
    sys.path.insert(0, str(p))

import formulas  # noqa: E402
import openpyxl  # noqa: E402

from engine_cases import CASES  # noqa: E402
from vsf.config import load_settings  # noqa: E402
from vsf.model import (FORMULA_CELLS, criteria_to_cells, inputs_to_dict,  # noqa: E402
                       to_cells)
from dataclasses import asdict  # noqa: E402

SHEET = "분석_빈칸"
CRITERIA_SHEET = "기준값"
OUT_DIR = ROOT / "tests" / "fixtures" / "oracle"


def clean(v):
    """엑셀 값 하나를 JSON으로 저장할 수 있는 모양으로 바꿔요: 빈 글자 → None, 숫자 → float, 날짜 → date."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if v is None or (isinstance(v, str) and v == ""):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) or type(v).__module__ == "numpy":
        return float(v)
    if isinstance(v, str):
        return v
    return f"#ERR:{v}"   # formulas의 XlError 등 엑셀 오류 값


def _jsonable(v):
    return v.isoformat() if isinstance(v, date) else v


def calculate(template: Path, inputs, criteria) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "calc.xlsx"
        shutil.copyfile(template, path)
        wb = openpyxl.load_workbook(path)
        for name in wb.sheetnames:
            if name not in (SHEET, CRITERIA_SHEET):
                del wb[name]
        ws = wb[SHEET]
        for addr, v in to_cells(inputs).items():
            if isinstance(v, date) and not isinstance(v, datetime):
                v = datetime(v.year, v.month, v.day)
            ws[addr].value = v
        for addr, v in criteria_to_cells(criteria).items():
            wb[CRITERIA_SHEET][addr].value = v
        wb.save(path)
        result = formulas.ExcelModel().loads(str(path)).finish().calculate()
    by_key = {str(k).upper(): v for k, v in result.items()}
    suffix = f"{SHEET}'!".upper()
    out: dict[str, object] = {}
    for addr in FORMULA_CELLS:
        hits = [v for k, v in by_key.items() if k.endswith(suffix + addr)]
        if len(hits) != 1:
            raise RuntimeError(f"{addr} 계산 결과를 찾을 수 없어요 ({len(hits)}개)")
        out[addr] = clean(hits[0].value[0][0])
    return out


def main() -> None:
    template = load_settings(ROOT / "settings.toml").calculator_path
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (inputs, criteria) in CASES.items():
        cells = calculate(template, inputs, criteria)
        doc = {"inputs": inputs_to_dict(inputs), "criteria": asdict(criteria),
               "cells": {k: _jsonable(cells[k]) for k in sorted(cells)}}
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {name}")
    print(f"{len(CASES)}개 사례 저장")


if __name__ == "__main__":
    main()
