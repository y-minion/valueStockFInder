"""업종 묶음, 업종 안 순위, 업종별 기준 덮어쓰기."""
import csv
import statistics
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import resources

from vsf.config import IndustrySettings
from vsf.model import Criteria, Num, StockInputs

ALL = "ALL"
ALL_NAME = "전체 시장"

_SECTIONS = (
    (1, 3, "A"), (5, 8, "B"), (10, 34, "C"), (35, 35, "D"), (36, 39, "E"), (41, 42, "F"),
    (45, 47, "G"), (49, 52, "H"), (55, 56, "I"), (58, 63, "J"), (64, 66, "K"), (68, 68, "L"),
    (70, 73, "M"), (74, 76, "N"), (84, 84, "O"), (85, 85, "P"), (86, 87, "Q"), (90, 91, "R"),
    (94, 96, "S"), (97, 98, "T"), (99, 99, "U"),
)


@dataclass(frozen=True)
class IndustryInfo:
    group_code: str
    group_name: str
    size: int
    roe_median: Num
    roe_rank_pct: Num
    debt_median: Num
    debt_rank_pct: Num


def division(induty_code: str | None) -> str:
    """KSIC 코드의 앞 두 자리(중분류). 비어 있으면 빈 글자."""
    return (induty_code or "").strip()[:2]


def section(div: str) -> str:
    """중분류 → 대분류 글자. KSIC 범위 밖이면 빈 글자."""
    if len(div) == 2 and div.isdigit():
        n = int(div)
        for lo, hi, sec in _SECTIONS:
            if lo <= n <= hi:
                return sec
    return ""


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    text = resources.files("vsf.data").joinpath("ksic.csv").read_text(encoding="utf-8")
    return {r["code"]: r["name"] for r in csv.DictReader(text.splitlines())}


def group_names() -> dict[str, str]:
    return {**_names(), ALL: ALL_NAME}


def _name(code: str) -> str:
    return group_names().get(code, f"업종코드 {code}")


def _rank_pct(value: float, values: list[float], higher_better: bool) -> float:
    better = sum(1 for v in values if (v > value if higher_better else v < value))
    return round((better + 1) / len(values) * 100, 1)


def build_industry(stocks: dict[str, tuple[str, Num, Num]],
                   min_group_size: int) -> dict[str, IndustryInfo]:
    """종목코드 → 업종 정보. 입력은 (induty_code, ROE 평균, 최근 부채비율)."""
    divs = {c: division(v[0]) for c, v in stocks.items()}
    secs = {c: section(d) for c, d in divs.items()}
    n_roe_div: dict[str, int] = {}
    n_roe_sec: dict[str, int] = {}
    for c, (_, roe, _debt) in stocks.items():
        if roe is None:
            continue
        if divs[c]:
            n_roe_div[divs[c]] = n_roe_div.get(divs[c], 0) + 1
        if secs[c]:
            n_roe_sec[secs[c]] = n_roe_sec.get(secs[c], 0) + 1

    def pick(c: str) -> str:
        if divs[c] and n_roe_div.get(divs[c], 0) >= min_group_size:
            return divs[c]
        if secs[c] and n_roe_sec.get(secs[c], 0) >= min_group_size:
            return secs[c]
        return ALL

    group_of = {c: pick(c) for c in stocks}

    def in_group(c: str, g: str) -> bool:
        return g == ALL or g in (divs[c], secs[c])

    members = {g: [c for c in stocks if in_group(c, g)] for g in set(group_of.values())}

    stats = {}
    for g, codes in members.items():
        roes = [stocks[c][1] for c in codes if stocks[c][1] is not None]
        debts = [stocks[c][2] for c in codes if stocks[c][2] is not None]
        stats[g] = (roes, debts)

    out = {}
    for c, g in group_of.items():
        roes, debts = stats[g]
        _, roe, debt = stocks[c]
        out[c] = IndustryInfo(
            group_code=g, group_name=_name(g), size=len(members[g]),
            roe_median=statistics.median(roes) if roes else None,
            roe_rank_pct=None if roe is None else _rank_pct(roe, roes, True),
            debt_median=statistics.median(debts) if debts else None,
            debt_rank_pct=None if debt is None else _rank_pct(debt, debts, False))
    return out


def effective_criteria(base: Criteria, induty_code: str | None,
                       overrides: dict[str, dict[str, float]]) -> Criteria:
    div = division(induty_code)
    over = overrides.get(div) or overrides.get(section(div))
    return replace(base, **over) if over else base


def extra_gate1(info: IndustryInfo | None, s: IndustrySettings) -> str | None:
    if not s.use_in_verdict:
        return None
    if info is None or info.roe_rank_pct is None:
        return "입력 필요"
    return "통과" if info.roe_rank_pct <= s.roe_top_percent else "탈락"


def industry_inputs(inputs: StockInputs) -> tuple[Num, Num]:
    """(ROE 5년 평균, 최근 해 부채비율). 엑셀 B78·B79와 같은 뜻이에요."""
    roes = [y.roe for y in inputs.years if y.roe is not None]
    return (sum(roes) / len(roes) if roes else None), inputs.years[-1].debt_ratio
