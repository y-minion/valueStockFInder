"""예시 비교 도구의 순수 함수 확인 (네트워크·keys.toml 안 씀)."""
from datetime import date

from tools.compare_examples import (CompanyReport, Row, align_years, build_report, compare_cells,
                                    compare_inputs, diff_pct, over_threshold, render_markdown)
from vsf.model import Criteria, StockInputs, YearRow


def _inp(years, price=100.0, **kw):
    rows = tuple(YearRow(year=y, eps=e, net_income=n) for y, e, n in years)
    return StockInputs(price=price, years=rows, **kw)


EX = _inp([(2021, 100, 10), (2022, 200, None), (2023, 0, 5), (2024, 400, 5), (2025, 500, 5)])
AU = _inp([(2022, 210, 7), (2023, 5, 5), (2024, 400, None), (2025, 700, 5), (2026, 800, 5)], price=None)


def test_diff_pct_edges():
    assert diff_pct(100, 110) == 10
    assert diff_pct(None, 1) is None and diff_pct(1, None) is None
    assert diff_pct(0, 5) is None
    assert diff_pct(-100, -90) == 10


def test_align_by_year_value():
    pairs, only_ex, only_au = align_years(EX, AU)
    assert [e.year for e, _ in pairs] == [2022, 2023, 2024, 2025]
    assert only_ex == [2021] and only_au == [2026]


def test_compare_inputs_rows_and_sources():
    rows = compare_inputs(EX, AU, {"E27": "DART 2025"})  # 자동 최신 2026 → 2025는 E열
    eps = {r.year: r for r in rows if r.item == "EPS"}
    assert set(eps) == {2022, 2023, 2024, 2025}
    assert eps[2022].diff_pct == 5.0 and eps[2025].source == "DART 2025"
    assert eps[2023].diff_pct is None          # 예시 0
    ni = {r.year: r for r in rows if r.item == "순이익"}
    assert ni[2022].diff_pct is None and ni[2024].auto is None
    price = next(r for r in rows if r.item == "주가")
    assert price.auto is None and price.diff_pct is None


def test_prior_dps_aligned_by_year():
    ex = StockInputs(years=EX.years, prior_years=(2016, 2017, None, None, None), prior_dps=(100.0, 200.0, None, None, None))
    au = StockInputs(years=AU.years, prior_years=(2017, None, None, None, None), prior_dps=(210.0, None, None, None, None))
    rows = [r for r in compare_inputs(ex, au, {}) if r.item == "이전 DPS"]
    assert [(r.year, r.auto) for r in rows] == [(2016, None), (2017, 210.0)]
    assert rows[1].diff_pct == 5.0


def test_over_threshold():
    rows = [Row("a", 1, 100, 106, 6.0), Row("b", 1, 100, 105, 5.0), Row("c", 1, 100, 90, -10.0), Row("d", 1, None, 1, None)]
    assert [r.item for r in over_threshold(rows)] == ["a", "c"]


def test_compare_cells_text_and_number():
    rows = compare_cells({"D82": "통과", "B105": 100.0, "B106": "C"}, {"D82": "탈락", "B105": 120.0})
    by = {r.item.split("(")[1][:-1]: r for r in rows}
    assert by["B105"].diff_pct == 20.0 and by["D82"].diff_pct is None and by["B106"].auto is None


def test_markdown_contains_tables_and_list():
    rep = build_report("기아", "000270", EX, Criteria(), {"D82": "통과"}, AU, {})
    fail = build_report("제일기획", "030000", EX, Criteria(), {}, None, {}, "한도 초과")
    md = render_markdown([rep, fail], date(2026, 11, 16))
    assert "## 기아 (000270)" in md and "## 제일기획 (030000)" in md
    assert "| 항목 | 연도 | 예시값 | 자동값 | 차이% | 출처 |" in md
    assert "5% 넘게 차이 나는 칸" in md and "판정 비교" in md
    assert "예시 500 → 자동 700 (+40.0%)" in md
    assert "한도 초과" in md and "—" in md
    assert "자동 쪽에 없는 예시 연도: 2021" in md and "예시에 없는 자동 연도: 2026" in md
