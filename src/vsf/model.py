"""공용 데이터 모델."""
from dataclasses import asdict, dataclass, field, fields
from datetime import date


@dataclass(frozen=True)
class Criteria:
    """판정 기준값. 기본값은 엑셀 '기준값' 시트와 같아요."""

    required_return: float = 0.10
    safety_margin: float = 0.25
    roe_min: float = 8.0
    debt_ratio_max: float = 200.0
    interest_coverage_min: float = 3.0
    ocf_to_ni_min: float = 1.0
    payout_min: float = 0.20
    payout_max: float = 0.60
    fcf_to_div_min: float = 1.0
    abnormal_ratio: float = 0.5
    isa_weight_max: float = 0.10


Num = float | None
Cell = float | str | None   # None은 엑셀의 빈칸이나 ""
SheetValues = dict[str, Cell]   # 키는 FORMULA_CELLS (금융회사 계산이면 FIN_CELLS 7개가 더 있어요)

_COLS = "BCDEF"


@dataclass(frozen=True)
class YearRow:
    """1번 표의 한 해(한 열). 못 가져온 숫자는 None이에요."""

    year: int | None = None
    eps: Num = None
    per: Num = None
    dps: Num = None
    roe: Num = None
    debt_ratio: Num = None
    interest_coverage: Num = None
    net_income: Num = None
    ocf: Num = None
    capex: Num = None
    dividends_paid: Num = None
    exclude_avg: bool = False
    exclude_div: bool = False


@dataclass(frozen=True)
class Gate4Inputs:
    """관문 ④ 직접 판단 칸 (B129–B134)."""

    reason: str = ""
    q1: str = ""
    q2: str = ""
    q3: str = ""
    judgment: str = ""
    why: str = ""


def _blank_years() -> tuple[YearRow, ...]:
    return (YearRow(),) * 5


@dataclass(frozen=True)
class StockInputs:
    """계산기 노란 칸에 넣는 값 전부."""

    name: str = ""
    code: str = ""
    price: Num = None
    price_date: date | None = None
    pbr: Num = None
    memo: str = ""
    years: tuple[YearRow, ...] = field(default_factory=_blank_years)
    prior_years: tuple[int | None, ...] = (None,) * 5
    prior_dps: tuple[Num, ...] = (None,) * 5
    normal_eps_override: Num = None
    my_eps: Num = None
    gate4: Gate4Inputs = field(default_factory=Gate4Inputs)


FORMULA_CELLS: tuple[str, ...] = tuple("""
B6 B7 B8 B9 B10 B11 C11 B12 C12 B13 C13 B14 C14 B15 C43 D43 E43 F43 B46 C46 D46 E46 F46 B47 C47 D47 E47 F47
B48 C48 D48 E48 F48 B49 C49 D49 E49 F49 B50 C50 D50 E50 F50 B51 C51 D51 E51 F51 B52 C52 D52 E52 F52
B53 C53 D53 E53 F53 B54 C54 D54 E54 F54 B55 C55 D55 E55 F55 B78 C78 D78 B79 C79 D79 B80 C80 D80
B81 C81 D81 D82 B86 D86 B87 D87 B88 C88 D88 B89 C89 D89 D90 B94 B96 B97 B98 B99 B100 B102 B103 B104
B105 B106 B107 B108 C108 B109 D110 B112 B113 B114 B115 B116 B117 B118 B120 C120 D120 E120 F120
B121 C121 D121 E121 F121 B122 C122 D122 E122 F122 B123 C123 D123 E123 F123 B124 C124 D124 E124 F124
C125 D125 E125 F125 B126 C126 D126 E126 F126 C131 C132 D135
""".split())

# 1번 표 행 번호 → YearRow 필드
_YEAR_ROWS = {
    26: "year", 27: "eps", 28: "per", 29: "dps", 30: "roe", 31: "debt_ratio",
    32: "interest_coverage", 33: "net_income", 34: "ocf", 35: "capex",
    36: "dividends_paid",
}


def _text(s: str) -> str | None:
    return s if s != "" else None


def to_cells(inputs: StockInputs) -> dict[str, float | str | date | None]:
    """입력 칸 주소 → 값. 빈 글자와 못 가져온 값은 None, X 표시는 "X"."""
    i = inputs
    cells: dict[str, float | str | date | None] = {
        "B18": _text(i.name), "B19": _text(i.code), "B20": i.price,
        "B21": i.price_date, "B22": i.pbr, "B23": _text(i.memo),
    }
    for col, y in zip(_COLS, i.years):
        for row, attr in _YEAR_ROWS.items():
            v = getattr(y, attr)
            cells[f"{col}{row}"] = str(v) if attr == "year" and v is not None else v
        cells[f"{col}37"] = "X" if y.exclude_avg else None
        cells[f"{col}38"] = "X" if y.exclude_div else None
    for col, yr, dps in zip(_COLS, i.prior_years, i.prior_dps):
        cells[f"{col}41"] = None if yr is None else str(yr)
        cells[f"{col}42"] = dps
    cells["B95"] = i.normal_eps_override
    cells["B125"] = i.my_eps
    g = i.gate4
    for addr, v in (("B129", g.reason), ("B130", g.q1), ("B131", g.q2),
                    ("B132", g.q3), ("B133", g.judgment), ("B134", g.why)):
        cells[addr] = _text(v)
    return cells


def criteria_to_cells(c: Criteria) -> dict[str, float]:
    """'기준값' 시트 B5..B15 (Criteria 필드 순서)."""
    return {f"B{5 + n}": getattr(c, f.name) for n, f in enumerate(fields(c))}


def inputs_to_dict(i: StockInputs) -> dict:
    d = asdict(i)
    d["price_date"] = i.price_date.isoformat() if i.price_date else None
    return d


def inputs_from_dict(d: dict) -> StockInputs:
    pd = d.get("price_date")
    return StockInputs(
        name=d["name"], code=d["code"], price=d["price"],
        price_date=date.fromisoformat(pd) if pd else None,
        pbr=d["pbr"], memo=d["memo"],
        years=tuple(YearRow(**y) for y in d["years"]),
        prior_years=tuple(d["prior_years"]), prior_dps=tuple(d["prior_dps"]),
        normal_eps_override=d["normal_eps_override"], my_eps=d["my_eps"],
        gate4=Gate4Inputs(**d["gate4"]),
    )
