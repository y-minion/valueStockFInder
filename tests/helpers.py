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


RECORDED_DART = ROOT / "tests" / "fixtures" / "dart" / "recorded"
_RECORDED_FIN = {"kia": "000270", "cheil": "030000"}
_NO_ID = "-표준계정코드 미사용-"


def load_fin(name: str):
    """녹화한 재무제표 응답을 읽어요. 이름 예: "kia_2025_cfs" → fin_000270_2025_cfs.json."""
    from vsf.data.dart import FinRows

    company, year, fs = name.split("_")
    doc = json.loads((RECORDED_DART / f"fin_{_RECORDED_FIN[company]}_{year}_{fs}.json")
                     .read_text(encoding="utf-8"))
    rows = doc["list"]
    return FinRows(rows=rows, fs=fs.upper(), rcept_no=rows[0]["rcept_no"])


def fin_row(sj_div: str, account_id: str, account_nm: str, thstrm="", frmtrm="", bfefrmtrm="",
            ord: int = 1) -> dict:
    """fnlttSinglAcntAll 목록 한 줄을 문서화된 모양 그대로 만들어요 (금액은 글자)."""
    return {"rcept_no": "20260310000001", "reprt_code": "11011", "bsns_year": "2025",
            "corp_code": "99000270", "sj_div": sj_div, "account_id": account_id,
            "account_nm": account_nm, "thstrm_amount": str(thstrm), "frmtrm_amount": str(frmtrm),
            "bfefrmtrm_amount": str(bfefrmtrm), "ord": str(ord), "currency": "KRW"}


def synthetic(capex_name: str | None = None, eps_rows: list[tuple[str, float]] | None = None,
              extra: list[dict] | None = None, defaults: bool = True):
    """합성 재무제표 (FinRows). 이자비용 줄은 일부러 없어요.

    capex_name: 주면 유형자산 취득 줄이 표준계정코드 없이 이 이름으로만 들어가요.
    eps_rows: [(이름, 값), …]이면 기본 EPS 줄 대신 이 줄들을 넣어요 (모두 EPS 표준계정코드).
    extra: 덧붙일 줄. defaults=False면 기본 줄 없이 extra만 써요.
    """
    from vsf.data.dart import FinRows

    rows: list[dict] = []
    if defaults:
        rows += [
            fin_row("BS", "ifrs-full_CurrentAssets", "유동자산", "5,000,000", "4,000,000", "3,000,000", 1),
            fin_row("BS", "ifrs-full_Liabilities", "부채총계", "8,000,000", "7,000,000", "6,000,000", 2),
            fin_row("BS", "ifrs-full_Equity", "자본총계", "20,000,000", "18,000,000", "16,000,000", 3),
            fin_row("IS", "ifrs-full_ProfitLoss", "당기순이익(손실)", "7,600,000", "6,000,000", "5,000,000", 4),
            fin_row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                    "지배기업의 소유주에게 귀속되는 당기순이익(손실)", "7,560,983", "5,900,000", "4,900,000", 5),
            fin_row("IS", "dart_OperatingIncomeLoss", "영업이익", "9,000,000", "7,000,000", "6,000,000", 6),
            fin_row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름",
                    "10,000,000", "9,000,000", "8,000,000", 7),
            fin_row("CF", _NO_ID if capex_name else
                    "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                    capex_name or "유형자산의 취득", "-3,000,000", "-2,500,000", "-2,000,000", 8),
            fin_row("CF", "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "배당금의 지급",
                    "-1,500,000", "-1,200,000", "-1,000,000", 9),
        ]
        if eps_rows is None:
            rows.append(fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", "기본주당이익(손실)",
                                "19,382", "15,000", "12,000", 10))
    for i, (name, value) in enumerate(eps_rows or []):
        rows.append(fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", name, f"{value:,}",
                            ord=20 + i))
    rows += extra or []
    return FinRows(rows=rows, fs="CFS", rcept_no="20260310000001")
