"""예시 시트(기아·제일기획)와 실제 자료로 자동 입력한 값을 칸별로 비교해 한국어 보고서를 써요.

실행: uv run python tools/compare_examples.py [--today 2026-11-16] [--data-dir DIR] [--out FILE]
키(keys.toml)는 읽기만 하고 어디에도 출력하거나 쓰지 않아요.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vsf.config import ConfigError, load_keys, load_settings  # noqa: E402
from vsf.data.assemble import _COLS  # noqa: E402
from vsf.data.dart import DartClient  # noqa: E402
from vsf.data.fisis import FisisClient  # noqa: E402
from vsf.data.krx import KrxClient  # noqa: E402
from vsf.data.store import Store  # noqa: E402
from vsf.engine import compute  # noqa: E402
from vsf.model import Criteria, StockInputs, YearRow, inputs_from_dict  # noqa: E402

ORACLE_DIR = ROOT / "tests" / "fixtures" / "oracle"
THRESHOLD = 5.0
BLANK = "—"
COMPANIES = (("000270", "kia", "기아"), ("030000", "cheil", "제일기획"))

# 1번 표 행 번호와 이름
YEAR_ITEMS: tuple[tuple[str, str, int], ...] = (
    ("eps", "EPS", 27), ("per", "PER", 28), ("dps", "DPS", 29), ("roe", "ROE", 30),
    ("debt_ratio", "부채비율", 31), ("interest_coverage", "이자보상배율", 32),
    ("net_income", "순이익", 33), ("ocf", "영업현금흐름", 34), ("capex", "설비투자", 35),
    ("dividends_paid", "배당금 지급", 36),
)
VERDICT_CELLS: tuple[tuple[str, str], ...] = (
    ("D82", "관문 ① 판정"), ("D90", "관문 ② 판정"), ("D110", "관문 ③ 판정"),
    ("B105", "적정가"), ("B106", "적정가 방법"), ("B107", "매수선"), ("B15", "한 줄 결론"),
)


@dataclass(frozen=True)
class Row:
    item: str
    year: int | None
    example: object
    auto: object
    diff_pct: float | None
    source: str = ""


def diff_pct(example, auto) -> float | None:
    """(자동 − 예시) ÷ |예시| × 100. 한쪽이 없거나 예시가 0이면 None."""
    if not _num(example) or not _num(auto) or example == 0:
        return None
    return (auto - example) / abs(example) * 100


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _auto_addr(year: int, latest: int, row: int) -> str:
    return f"{_COLS[year - latest + 4]}{row}"


def align_years(example: StockInputs, auto: StockInputs) -> tuple[list[tuple[YearRow, YearRow]], list[int], list[int]]:
    """연도 값으로 짝지어요. (짝 목록, 예시에만 있는 연도, 자동에만 있는 연도)."""
    ex = {r.year: r for r in example.years if r.year is not None}
    au = {r.year: r for r in auto.years if r.year is not None}
    pairs = [(ex[y], au[y]) for y in sorted(ex) if y in au]
    return pairs, sorted(set(ex) - set(au)), sorted(set(au) - set(ex))


def _latest(auto: StockInputs) -> int | None:
    years = [r.year for r in auto.years if r.year is not None]
    return max(years) if years else None


def compare_inputs(example: StockInputs, auto: StockInputs, sources: dict[str, str]) -> list[Row]:
    """입력 칸 비교. 연도별 항목은 연도 값으로 맞추고, 가격·PBR·이전 DPS를 덧붙여요."""
    rows: list[Row] = []
    latest = _latest(auto)
    pairs, _, _ = align_years(example, auto)
    for attr, label, row in YEAR_ITEMS:
        for ex, au in pairs:
            src = sources.get(_auto_addr(au.year, latest, row), "") if latest is not None else ""
            e, a = getattr(ex, attr), getattr(au, attr)
            rows.append(Row(label, ex.year, e, a, diff_pct(e, a), src))
    rows.append(Row("주가", None, example.price, auto.price, diff_pct(example.price, auto.price), sources.get("B20", "")))
    rows.append(Row("PBR", None, example.pbr, auto.pbr, diff_pct(example.pbr, auto.pbr), sources.get("B22", "")))
    ex_prior = {y: d for y, d in zip(example.prior_years, example.prior_dps) if y is not None}
    au_prior = {y: d for y, d in zip(auto.prior_years, auto.prior_dps) if y is not None}
    for y in sorted(ex_prior):
        if y in au_prior and latest is not None:
            src = sources.get(f"{_COLS[y - latest + 9]}42", "") if 0 <= y - latest + 9 < len(_COLS) else ""
            rows.append(Row("이전 DPS", y, ex_prior[y], au_prior[y], diff_pct(ex_prior[y], au_prior[y]), src))
        else:
            rows.append(Row("이전 DPS", y, ex_prior[y], None, None, ""))
    return rows


def compare_cells(example_cells: dict, auto_cells: dict) -> list[Row]:
    rows = []
    for addr, label in VERDICT_CELLS:
        e, a = example_cells.get(addr), auto_cells.get(addr)
        rows.append(Row(f"{label} ({addr})", None, e, a, diff_pct(e, a)))
    return rows


def over_threshold(rows: list[Row], threshold: float = THRESHOLD) -> list[Row]:
    return [r for r in rows if r.diff_pct is not None and abs(r.diff_pct) > threshold]


def _fmt(x) -> str:
    if x is None or x == "":
        return BLANK
    if _num(x):
        return f"{x:,.0f}" if float(x).is_integer() or abs(x) >= 1000 else f"{x:,.2f}"
    return str(x).replace("|", "\\|").replace("\n", " ")


def _fmt_diff(d: float | None) -> str:
    return BLANK if d is None else f"{d:+.1f}%"


def _table(rows: list[Row]) -> list[str]:
    out = ["| 항목 | 연도 | 예시값 | 자동값 | 차이% | 출처 |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r.item} | {r.year if r.year is not None else BLANK} | {_fmt(r.example)} | "
                   f"{_fmt(r.auto)} | {_fmt_diff(r.diff_pct)} | {_fmt(r.source)} |")
    return out


@dataclass(frozen=True)
class CompanyReport:
    name: str
    code: str
    rows: list[Row]
    verdicts: list[Row]
    only_example: list[int]
    only_auto: list[int]
    note: str = ""        # 받기 실패 등


def render_markdown(reports: list[CompanyReport], today: date, threshold: float = THRESHOLD) -> str:
    lines = [f"# 실제 자료 확인 ({today.isoformat()})", "",
             f"예시 시트의 노란 칸과 자동으로 채운 값을 비교해요. 차이% = (자동 − 예시) ÷ |예시|. "
             f"빈 칸({BLANK})은 한쪽이 없다는 뜻이에요.", ""]
    for rep in reports:
        lines += [f"## {rep.name} ({rep.code})", ""]
        if rep.note:
            lines += [f"자동값을 받지 못했어요: {rep.note}", ""]
        if rep.only_example:
            lines += ["자동 쪽에 없는 예시 연도: " + ", ".join(map(str, rep.only_example)), ""]
        if rep.only_auto:
            lines += ["예시에 없는 자동 연도: " + ", ".join(map(str, rep.only_auto)), ""]
        lines += _table(rep.rows) + [""]
        lines += [f"### {rep.name}: {threshold:g}% 넘게 차이 나는 칸", ""]
        big = over_threshold(rep.rows, threshold)
        if big:
            lines += [f"- {r.item}" + (f" {r.year}년" if r.year is not None else "")
                      + f": 예시 {_fmt(r.example)} → 자동 {_fmt(r.auto)} ({_fmt_diff(r.diff_pct)})" for r in big]
        else:
            lines.append("없어요.")
        lines += ["", f"### {rep.name}: 판정 비교", ""] + _table(rep.verdicts) + [""]
    return "\n".join(lines)


def load_example(stem: str) -> tuple[StockInputs, Criteria, dict]:
    doc = json.loads((ORACLE_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    return inputs_from_dict(doc["inputs"]), Criteria(**doc["criteria"]), doc["cells"]


def build_report(name: str, code: str, example: StockInputs, criteria: Criteria, example_cells: dict,
                 auto: StockInputs | None, sources: dict[str, str], note: str = "") -> CompanyReport:
    if auto is None:
        return CompanyReport(name, code, [], [], [], [], note)
    _, only_ex, only_au = align_years(example, auto)
    return CompanyReport(name, code, compare_inputs(example, auto, sources),
                         compare_cells(example_cells, compute(auto, criteria)), only_ex, only_au, note)


def main(argv: list[str] | None = None) -> int:
    from vsf.collect import collect_one
    from vsf.evaluate import evaluate_one

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", type=Path, default=Path("settings.toml"))
    ap.add_argument("--keys", type=Path, default=Path("keys.toml"))
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    today = args.today or date.today()
    try:
        settings = load_settings(args.settings)
        keys = load_keys(args.keys)
    except ConfigError as e:
        print(f"설정을 읽지 못했어요: {e}")
        return 1
    store = Store((args.data_dir or settings.data_dir) / "vsf.sqlite3")
    dart = DartClient(keys.dart, store, daily_budget=settings.dart_daily_budget)
    krx = KrxClient(keys.krx, store)
    fisis = FisisClient(keys.fisis, store) if keys.fisis else None
    reports = []
    for code, stem, name in COMPANIES:
        example, criteria, cells = load_example(stem)
        got = collect_one(dart, krx, store, today, code, include_financial=settings.financial.include, fisis=fisis)
        if isinstance(got, str):
            reports.append(build_report(name, code, example, criteria, cells, None, {}, got))
            continue
        company, assembled = got
        evaluate_one(company, assembled, settings, None)  # 평가가 오류 없이 도는지도 함께 확인
        reports.append(build_report(name, code, example, criteria, cells, assembled.inputs, assembled.sources))
    out = args.out or ROOT / "docs" / "validation" / f"{today.isoformat()}-real-data-check.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(reports, today), encoding="utf-8")
    print(f"보고서를 썼어요: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
