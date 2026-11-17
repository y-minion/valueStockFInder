"""기준선 바로 옆 숫자에 '경계' 표시를 달고, 한 칸 차이로 탈락한 종목을 찾아요. 판정은 바꾸지 않아요."""
from dataclasses import dataclass

from vsf.config import ReportSettings
from vsf.excelfn import excel_round
from vsf.financial import CAPITAL_LABELS, FinancialGate
from vsf.model import Criteria, SheetValues

STEPS = {"roe_min": 1.0, "debt_ratio_max": 25.0, "interest_coverage_min": 0.5,
         "ocf_to_ni_min": 0.1, "payout": 0.05, "fcf_to_div_min": 0.1}
CAPITAL_STEPS = {"금융지주": 1.0, "은행": 1.0, "보험": 10.0, "증권": 100.0}
_EPS = 1e-9
_FAIL_CELLS = ("D78", "D79", "D80", "D81", "D86", "D87", "D88", "D89", "F_LOSS_D", "F_CAP_D")


@dataclass(frozen=True)
class Boundary:
    cell: str
    label: str
    value: float
    threshold: float
    gap: float
    unit: str
    passed: bool


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _make(cells, d_cell, b_cell, label, unit, threshold, step, scale=1.0, value=None):
    verdict = cells.get(d_cell)
    if verdict not in ("통과", "탈락"):
        return None
    native = cells.get(b_cell) if value is None else value
    if not _num(native) or threshold is None or abs(native - threshold) > step + _EPS:
        return None
    v, t = round(native * scale, 4), round(threshold * scale, 4)
    return Boundary(d_cell, label, v, t, round(v - t, 4), unit, verdict == "통과")


def boundaries(cells: SheetValues, criteria: Criteria, financial: FinancialGate | None) -> tuple[Boundary, ...]:
    c, out = criteria, []
    out.append(_make(cells, "D78", "B78", "ROE 5년 평균", "%p", c.roe_min, STEPS["roe_min"]))
    out.append(_make(cells, "D79", "B79", "부채비율", "%p", c.debt_ratio_max, STEPS["debt_ratio_max"]))
    out.append(_make(cells, "D80", "B80", "이자보상배율", "배", c.interest_coverage_min, STEPS["interest_coverage_min"]))
    out.append(_make(cells, "D81", "B81", "영업현금흐름÷순이익", "배", c.ocf_to_ni_min, STEPS["ocf_to_ni_min"]))
    b88 = cells.get("B88")
    if _num(b88):
        r = excel_round(b88, 2)
        t = min((c.payout_min, c.payout_max), key=lambda x: abs(r - x))
        out.append(_make(cells, "D88", "B88", "배당성향", "%p", t, STEPS["payout"], 100.0, value=r))
    out.append(_make(cells, "D89", "B89", "잉여현금흐름÷배당", "배", c.fcf_to_div_min, STEPS["fcf_to_div_min"]))
    if financial is not None and financial.kind in CAPITAL_STEPS:
        out.append(_make(cells, "F_CAP_D", "F_CAP_B", CAPITAL_LABELS[financial.kind], "%p",
                         financial.capital_min, CAPITAL_STEPS[financial.kind]))
    return tuple(b for b in out if b is not None)


def near_miss_state(cells: SheetValues, bounds: tuple[Boundary, ...], report: ReportSettings,
                    extra_gate1: str | None = None) -> str | None:
    if extra_gate1 == "탈락":        # 업종 안 ROE 순위로 떨어진 종목은 경계 근처가 아니에요
        return None
    if "탈락" not in (cells.get("D82"), cells.get("D90")):
        return None
    failed = {b.cell for b in bounds if not b.passed}
    if any(cells.get(k) == "탈락" and k not in failed for k in _FAIL_CELLS):
        return None
    if cells.get("D110") == "통과":
        return "buy"
    b109 = cells.get("B109")
    if _num(b109) and b109 <= report.watch_range:
        return "watch"
    return "out"
