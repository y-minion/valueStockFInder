"""계산기 입력 조립. 녹화 자료 테스트(recorded) 말고는 모두 합성 회사로 돌아요."""
import math
from dataclasses import replace
from datetime import date

import pytest

from helpers import (ORIGINAL_OLD_EPS, SYN_SHARES, div_rows, fin_row, load_company, load_divs, load_fin,
                     load_oracle, load_price, load_year_end, synthetic_company)
from vsf.data.assemble import (ROE_END_NOTE, Assembled, assemble, assemble_quick_fail, dps_by_year,
                               dps_from_report, quick_fail_check)
from vsf.data.splits import RESTATE_FLAG, SPLIT_FLAG
from vsf.data.store import PriceRow
from vsf.engine import compute, summarize
from vsf.model import Criteria, to_cells

# 합성 기아(가짜 고유번호 99000270)와 현재가 97,000원. D = 2026-11-13
KIA_CO, _, _, _, _, _, PRICE, D = synthetic_company()

YEARS = [2021, 2022, 2023, 2024, 2025]
FIN_FIELDS = ("eps", "per", "roe", "debt_ratio", "interest_coverage", "net_income", "ocf", "capex",
              "dividends_paid")
EQUITY_PARENT = "ifrs-full_EquityAttributableToOwnersOfParent"
# 합성 회사의 두 사업보고서 (출처 글 앞부분)
A_REPORT = "2025 사업보고서(연결, 접수번호 20260310000123)"
B_REPORT = "2023 사업보고서(연결, 접수번호 20240310000123)"


def _set_amount(fin, account_id: str, period: str, text: str):
    """FinRows에서 한 계정 줄의 한 기간 금액만 바꾼 사본."""
    return replace(fin, rows=[{**r, f"{period}_amount": text} if r["account_id"] == account_id else r
                              for r in fin.rows])


def _filled(inputs) -> set[str]:
    return {addr for addr, v in to_cells(inputs).items() if v is not None}


def _numbers(inputs) -> list:
    return [v for v in to_cells(inputs).values() if isinstance(v, (int, float))]


# ---- 녹화 자료 (tests/fixtures/dart/recorded + krx/recorded가 있어야 돌아요) ----

@pytest.fixture
def recorded_kia():
    """녹화한 기아 회사 정보와 2026-11-13 종가. 녹화 테스트 안에서만 불러요."""
    return load_company("kia"), load_price("kia", date(2026, 11, 13))


@pytest.mark.recorded
def test_kia_close_to_example_sheet(recorded_kia):
    kia_co, price = recorded_kia
    a = assemble(kia_co, 2025, load_fin("kia_2025_cfs"), load_fin("kia_2023_cfs"), load_divs("kia"),
                 load_year_end("kia"), price, date(2026, 11, 13))
    y = a.inputs.years
    assert [r.eps for r in y[2:]] == [22168, 24893, 19382]
    assert [r.dps for r in y] == [3000, 3500, 5600, 6500, 6800]
    assert all(math.isclose(r.net_income, w, rel_tol=0.005)
               for r, w in zip(y, (47604.5, 54094.29, 87769.7, 97729.57, 75609.83)))
    # 2023–2025는 두 연말 자본이 항상 있음
    assert all(abs(r.roe - w) <= 0.5 for r, w in zip(y[2:], (20.44, 19.09, 12.91)))
    assert all(abs(r.debt_ratio - w) <= 0.5 for r, w in zip(y, (91.48, 87.35, 73.18, 66.11, 61.76)))
    assert all(r.capex is not None and r.capex > 0 for r in y)
    assert a.inputs.prior_dps == (1100.0, 800.0, 900.0, 1150.0, 1000.0) and a.flags == ()


@pytest.mark.recorded
def test_missing_older_report_leaves_blanks(recorded_kia):
    kia_co, price = recorded_kia
    a = assemble(kia_co, 2025, load_fin("kia_2025_cfs"), None, load_divs("kia"), load_year_end("kia"),
                 price, D)
    assert a.inputs.years[0].eps is None and a.inputs.years[1].ocf is None


# ---- DART 녹화 자료만으로 (KRX 키 없이) 예시 시트와 맞춰 보기 ----

DART_ONLY_PRICE_DATE = date(2026, 11, 13)


def _dart_only(name: str):
    """녹화한 DART 자료 + 예시 시트의 종가로 조립한 입력, 그리고 예시 시트(입력·기준·칸 값)."""
    example, criteria, cells = load_oracle(name)
    co = load_company(name)
    price = PriceRow(DART_ONLY_PRICE_DATE, co.code, co.name, co.market, close=example.price, shares=None)
    a = assemble(co, 2025, load_fin(f"{name}_2025_cfs"), load_fin(f"{name}_2023_cfs"), load_divs(name),
                 {}, price, DART_ONLY_PRICE_DATE)
    return a, example, criteria, cells


def _close(got, want, rel: float) -> bool:
    return got is not None and math.isclose(got, want, rel_tol=rel)


@pytest.mark.recorded("dart")
@pytest.mark.parametrize("name", ["kia", "cheil"])
def test_dart_inputs_match_example_sheet(name):
    a, example, _, _ = _dart_only(name)
    got, want = a.inputs.years, example.years
    assert [r.eps for r in got] == [r.eps for r in want]
    assert [r.dps for r in got] == [r.dps for r in want]
    assert a.inputs.prior_dps == example.prior_dps
    # ROE는 제일기획 2023–2025년 예시 값이 평균 자본 계산과 0.5–0.7% 벌어져서 1%로 봐요 (2021년은 0.4%).
    for field, rel in (("net_income", 0.005), ("debt_ratio", 0.005), ("roe", 0.01), ("ocf", 0.01)):
        bad = [(r.year, getattr(r, field), getattr(w, field)) for r, w in zip(got, want)
               if not _close(getattr(r, field), getattr(w, field), rel)]
        assert not bad, f"{field}: {bad}"
    assert _close(got[0].roe, want[0].roe, 0.005)   # 2021년(자본변동표 기초자본을 쓰는 해)은 0.5% 안
    assert all(r.capex is not None and r.capex > 0 for r in got)
    assert all(r.dividends_paid is not None and r.dividends_paid > 0 for r in got)
    assert a.flags == ()
    assert ROE_END_NOTE.format(y=2021) not in a.notes


@pytest.mark.recorded("dart")
@pytest.mark.parametrize("name", ["kia", "cheil"])
def test_dart_inputs_give_example_verdicts(name):
    a, example, criteria, _ = _dart_only(name)
    # PER은 KRX 연말 종가가 있어야 해서, 예시 시트 값을 그대로 가져와요.
    years = tuple(replace(r, per=w.per) for r, w in zip(a.inputs.years, example.years))
    inputs = replace(a.inputs, years=years, price=example.price, price_date=example.price_date,
                     pbr=example.pbr)
    got, want = compute(inputs, criteria), compute(example, criteria)
    for addr in ("D82", "D90", "D110", "B105", "B106", "B107", "B15"):
        assert got[addr] == want[addr], addr


# ---- 계획서의 합성 자료 테스트 ----

def test_interest_proxy_and_999():
    a = assemble(*synthetic_company(interest_expense=None, interest_paid=0))
    assert a.inputs.years[4].interest_coverage == 999 and any("이자의 지급" in n for n in a.notes)


def test_ofs_note():
    assert "별도 재무제표 기준이에요" in assemble(*synthetic_company(fs="OFS")).notes


def test_non_krw_flagged():
    assert any("원화가 아닌" in f for f in assemble(*synthetic_company(currency="USD")).flags)


def test_quick_fail_detection():
    assert quick_fail_check(div_rows(thstrm="-", frmtrm="1,000", lwfr="900"), 2025)


def test_quick_fail_only_when_latest_year_has_no_dividend():
    assert quick_fail_check(div_rows("-", "1,000", "900"), 2025) is True       # 최근 해 0
    assert quick_fail_check(div_rows("1,000", "-", "900"), 2025) is False      # 전 해만 0이면 끝까지 계산


def test_quick_fail_inputs():
    a = assemble_quick_fail(KIA_CO, 2025, {2025: div_rows("1,000", "-", "900")}, PRICE, D)
    assert a.quick_fail and a.inputs.years[3].dps == 0.0 and a.inputs.years[4].roe is None


def test_special_dividend_note():
    assert any("특별배당 의심" in n for n in assemble(*synthetic_company(dps=3000, eps=2000)).notes)


def test_split_adjusts_older_eps_and_flags():
    a = assemble(*synthetic_company(split_ratio=2))
    assert a.inputs.years[0].eps == ORIGINAL_OLD_EPS / 2 and SPLIT_FLAG in a.flags


# ---- 이상한 점 없는 합성 회사 하나로 모든 칸 고정 (손으로 계산한 값) ----

@pytest.fixture(scope="module")
def base() -> Assembled:
    return assemble(*synthetic_company())


def test_year_rows_every_field(base):
    y = base.inputs.years
    assert [r.year for r in y] == YEARS
    assert [r.eps for r in y] == [11874, 13495, 22168, 24893, 19382]   # 2021·2022는 B(2023) 보고서, 나머지는 A(2025)
    # 연말 종가 ÷ EPS: 82,600/11,874  59,200/13,495  100,000/22,168  100,800/24,893  121,700/19,382
    assert [r.per for r in y] == [6.96, 4.39, 4.51, 4.05, 6.28]
    assert [r.dps for r in y] == [3000, 3500, 5600, 6500, 6800]
    # 지배주주 순이익 ÷ 연말 지배주주 자본 평균 × 100 (조 원):
    #   2021: 4.76045 ÷ 32.4 (2020년 말 자본이 없어 기말 자본만)
    #   2022: 5.409429 ÷ ((32.4 + 37.9) / 2)                  B 전전기·전기
    #   2023: 8.77697 ÷ ((37.9 + 45.0) / 2)                   2022년 말은 B 전기, 2023년 말은 A 전전기
    #   2024: 9.772957 ÷ ((45.0 + 53.5) / 2)   2025: 7.560983456789 ÷ ((53.5 + 58.0) / 2)
    assert [r.roe for r in y] == [14.69, 15.39, 21.17, 19.84, 13.56]
    # 부채총계 ÷ 자본총계 × 100: 29.70/32.46  33.15/37.96  32.98/45.06  35.41/53.56  35.86/58.06
    assert [r.debt_ratio for r in y] == [91.5, 87.33, 73.19, 66.11, 61.76]
    # 영업이익 ÷ 이자비용 (십억 원): 5,065.7/170.4  7,233.1/234.5  11,607.9/184.2  12,667.1/104.5  9,078/78.56
    assert [r.interest_coverage for r in y] == [29.73, 30.84, 63.02, 121.22, 115.55]
    # 억 원 = 원 ÷ 1e8, 엑셀 ROUND(·, 2)
    assert [r.net_income for r in y] == [47604.5, 54094.29, 87769.7, 97729.57, 75609.83]  # 75,609.83456789
    assert [r.ocf for r in y] == [74000, 93000, 113000, 126000, 91000.13]   # 91,000.125는 반쪽이라 위로
    assert [r.capex for r in y] == [19123, 20500, 25111, 23456.79, 30333]   # 보고서의 음수를 양수로
    assert [r.dividends_paid for r in y] == [4000, 12030, 14025, 22450, 26000]
    assert not any(r.exclude_avg or r.exclude_div for r in y)


def test_ten_dps_values_and_year_labels(base):
    i = base.inputs
    assert [r.year for r in i.years] == YEARS and [r.dps for r in i.years] == [3000, 3500, 5600, 6500, 6800]
    assert i.prior_years == (2016, 2017, 2018, 2019, 2020) and i.prior_dps == (1100, 800, 900, 1150, 1000)
    cells = to_cells(i)
    assert [cells[f"{c}26"] for c in "BCDEF"] == ["2021", "2022", "2023", "2024", "2025"]
    assert [cells[f"{c}41"] for c in "BCDEF"] == ["2016", "2017", "2018", "2019", "2020"]
    assert [cells[f"{c}42"] for c in "BCDEF"] == [1100, 800, 900, 1150, 1000]


def test_roe_year_end_equity_a_first_then_b():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    b_differs = _set_amount(fin_b, EQUITY_PARENT, "thstrm", "46,000,000,000,000")   # B의 2023년 말 자본만 46조
    a = assemble(co, L, fin_a, b_differs, divs, ye, price, d)
    assert [r.roe for r in a.inputs.years[2:4]] == [21.17, 19.84]                # 두 보고서에 다 있으면 A(45조)
    a = assemble(co, L, _set_amount(fin_a, EQUITY_PARENT, "bfefrmtrm", ""), b_differs, divs, ye, price, d)
    # A에 없으면 B(46조): 8.77697 ÷ ((37.9 + 46) / 2), 9.772957 ÷ ((46 + 53.5) / 2)
    assert [r.roe for r in a.inputs.years[2:4]] == [20.92, 19.64]
    assert a.notes == ("2021년 ROE는 기말 자본 기준이에요", "PBR은 추정값이에요")


SCE_PARENT = "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]"


def _with_sce_begin(fin, thstrm: str, frmtrm: str, bfefrmtrm: str):
    """자본변동표 지배기업 지분 기초자본 줄을 덧붙인 사본."""
    row = fin_row("SCE", "dart_EquityAtBeginningOfPeriod", "기초자본", thstrm, frmtrm, bfefrmtrm, ord=90,
                  account_detail=SCE_PARENT)
    return replace(fin, rows=[*fin.rows, row])


# 합성 B 보고서(2023)의 지배주주 자본: 2021 32.4조, 2022 37.9조, 2023 45.0조. 2020년 말은 29.0조라고 해요.
_B_BEGIN = ("37,900,000,000,000", "32,400,000,000,000", "29,000,000,000,000")


def test_oldest_roe_uses_sce_beginning_equity_when_report_is_consistent():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, _with_sce_begin(fin_b, *_B_BEGIN), divs, ye, price, d)
    assert a.inputs.years[0].roe == round(4.76045 / ((32.4 + 29.0) / 2) * 100, 2)
    assert "자본변동표 기초자본" in a.sources["B30"]
    assert a.sources["B30"].startswith(B_REPORT)
    assert ROE_END_NOTE.format(y=2021) not in a.notes


def test_oldest_roe_keeps_year_end_equity_when_sce_is_off_by_2_percent():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    off = (_B_BEGIN[0], "33,050,000,000,000", _B_BEGIN[2])   # 전기 기초가 2022년 말(=2021 기말) 32.4조와 2% 어긋나요
    a = assemble(co, L, fin_a, _with_sce_begin(fin_b, *off), divs, ye, price, d)
    assert a.inputs.years[0].roe == round(4.76045 / 32.4 * 100, 2)
    assert ROE_END_NOTE.format(y=2021) in a.notes and "자본변동표" not in a.sources["B30"]


def test_oldest_roe_keeps_year_end_equity_when_only_one_pair_is_comparable():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, _with_sce_begin(fin_b, _B_BEGIN[0], "", ""), divs, ye, price, d)
    assert a.inputs.years[0].roe == round(4.76045 / 32.4 * 100, 2)
    assert ROE_END_NOTE.format(y=2021) in a.notes


def test_pbr_estimate(base):
    # 97,000 ÷ (58조 ÷ (7,560,983,456,789 ÷ 19,382)) = 0.652…
    assert base.inputs.pbr == 0.65 and "PBR은 추정값이에요" in base.notes
    assert base.sources["B22"] == f"2026-11-13 종가 ÷ 추정 BPS({A_REPORT} · 자본 ÷ (순이익 ÷ EPS))"


def test_pbr_and_per_need_positive_eps():
    a = assemble(*synthetic_company(eps=-500))
    assert a.inputs.years[4].per is None and a.inputs.pbr is None
    assert "PBR은 추정값이에요" not in a.notes and "B22" not in a.sources and "F28" not in a.sources


def test_sources_examples(base):
    s = base.sources
    assert s["F27"] == "2025 사업보고서(연결, 접수번호 20260310000123) · ifrs-full_BasicEarningsLossPerShare"
    assert s["B27"] == f"{B_REPORT} · ifrs-full_BasicEarningsLossPerShare"
    assert s["B28"] == "2021-12-30 종가 ÷ EPS"                         # KRX 종가에는 접수번호가 없어요
    assert s["F29"] == "2025 사업보고서 배당에 관한 사항(보통주, 접수번호 20260310000123)"
    # 2023년 DPS는 두 배당 보고서에 있고 최근 것이 먼저예요
    assert s["D29"] == "2025 사업보고서 배당에 관한 사항(보통주, 접수번호 20260310000123)"
    assert s["C29"] == "2023 사업보고서 배당에 관한 사항(보통주, 접수번호 20240310000123)"
    assert s["F42"] == "2021 사업보고서 배당에 관한 사항(보통주, 접수번호 20220310000123)"
    assert s["D30"] == f"{A_REPORT}, {B_REPORT} · 순이익 ÷ 2022·2023년 말 평균 자본"
    assert s["B30"] == f"{B_REPORT} · 순이익 ÷ 2021년 말 자본"
    assert s["F31"] == f"{A_REPORT} · 부채총계 ÷ 자본총계"
    assert s["F32"] == f"{A_REPORT} · 영업이익 ÷ 이자비용"
    assert s["F33"] == f"{A_REPORT} · ifrs-full_ProfitLossAttributableToOwnersOfParent"
    assert s["B35"] == (f"{B_REPORT} · "
                       "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
    assert s["B20"] == "KRX 2026-11-13 종가" and s["B18"] == "KRX 종목 목록 · DART 고유번호 99000270"


def test_receipt_number_left_out_when_missing():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    divs = {**divs, 2025: [{k: v for k, v in r.items() if k != "rcept_no"} for r in divs[2025]]}
    a = assemble(co, L, replace(fin_a, rcept_no=""), fin_b, divs, ye, price, d)
    assert a.sources["F27"] == "2025 사업보고서(연결) · ifrs-full_BasicEarningsLossPerShare"
    assert a.sources["D30"] == f"2025 사업보고서(연결), {B_REPORT} · 순이익 ÷ 2022·2023년 말 평균 자본"
    assert a.sources["F29"] == a.sources["D29"] == "2025 사업보고서 배당에 관한 사항(보통주)"
    assert a.sources["C29"] == "2023 사업보고서 배당에 관한 사항(보통주, 접수번호 20240310000123)"


def test_every_filled_input_cell_has_a_source(base):
    assert set(base.sources) == _filled(base.inputs)


def test_memo_text(base):
    assert base.inputs.memo == ("자동 수집 2026-11-13: DART 사업보고서 2025·2023, 배당 2017·2019·2021·2023·2025, "
                                "주가 KRX 2026-11-13 종가.")


def test_clean_company_has_no_flags_and_untouched_cells_stay_blank(base):
    assert base.flags == () and base.quick_fail is False and base.latest_year == 2025
    assert base.notes == ("2021년 ROE는 기말 자본 기준이에요", "PBR은 추정값이에요")
    i = base.inputs
    assert (i.name, i.code, i.price, i.price_date) == ("기아", "000270", 97000, date(2026, 11, 13))
    cells = to_cells(i)
    untouched = ["B95", "B125", *(f"{c}{r}" for c in "BCDEF" for r in (37, 38)),
                 *(f"B{r}" for r in range(129, 135))]
    assert [cells[a] for a in untouched] == [None] * len(untouched)
    assert 0 not in _numbers(i)


# ---- 빈 값, 대신 쓰는 값, 확인 표시 ----

def test_missing_data_stays_none_not_zero():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    ye = {y: row for y, row in ye.items() if y != 2024}                            # 2024년 연말 종가 없음
    divs = {**divs, 2023: [r for r in divs[2023] if r["stock_knd"] != "보통주"]}    # 2022년 DPS는 2023 보고서에만 있어요
    a = assemble(co, L, fin_a, None, divs, ye, replace(price, close=None), d)
    y = a.inputs.years
    assert all(getattr(r, f) is None for r in y[:2] for f in FIN_FIELDS)            # B 보고서가 없는 해
    assert y[3].per is None and y[3].eps == 24893
    assert [r.dps for r in y] == [3000, None, 5600, 6500, 6800]
    assert y[2].roe == 19.5 and "2023년 ROE는 기말 자본 기준이에요" in a.notes        # 8.77697 ÷ 45 (2022년 말 자본 없음)
    assert a.inputs.price is None and a.inputs.pbr is None and "PBR은 추정값이에요" not in a.notes
    assert a.inputs.memo.startswith("자동 수집 2026-11-13: DART 사업보고서 2025, 배당 2017·")
    assert 0 not in _numbers(a.inputs) and set(a.sources) == _filled(a.inputs)


def test_without_latest_report_only_dps_and_labels_are_filled():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, None, fin_b, divs, ye, price, d)
    y = a.inputs.years
    assert [r.year for r in y] == YEARS and [r.dps for r in y] == [3000, 3500, 5600, 6500, 6800]
    assert all(getattr(r, f) is None for r in y for f in FIN_FIELDS) and a.inputs.pbr is None
    assert a.flags == () and a.notes == () and "DART 사업보고서 자료 없음" in a.inputs.memo
    assert set(a.sources) == _filled(a.inputs)


def test_interest_paid_proxy_values_and_notes():
    a = assemble(*synthetic_company(interest_expense=None, interest_paid=0))
    # 이자비용 줄이 없어 '이자의 지급' 절댓값으로: 5,065.7/165  7,233.1/230  11,607.9/180  12,667.1/100, 2025는 0이라 999
    assert [r.interest_coverage for r in a.inputs.years] == [30.7, 31.45, 64.49, 126.67, 999]
    assert [n for n in a.notes if "이자의 지급" in n] == [
        f"{y}년 이자보상배율은 '이자의 지급'으로 계산했어요" for y in YEARS]
    assert a.sources["F32"] == f"{A_REPORT} · 영업이익 ÷ 이자의 지급(0이라 999)"


def test_interest_expense_zero_and_missing_parts():
    a = assemble(*synthetic_company(interest_expense=0))
    assert a.inputs.years[4].interest_coverage == 999 and not any("이자의 지급" in n for n in a.notes)
    a = assemble(*synthetic_company(interest_expense=None, interest_paid=None))
    assert [r.interest_coverage for r in a.inputs.years] == [None] * 5
    assert not any("이자의 지급" in n for n in a.notes)
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    no_income = _set_amount(fin_a, "dart_OperatingIncomeLoss", "thstrm", "")
    a = assemble(co, L, no_income, fin_b, divs, ye, price, d)
    assert a.inputs.years[4].interest_coverage is None and a.inputs.years[3].interest_coverage == 121.22


def test_ofs_uses_separate_statement_accounts():
    a = assemble(*synthetic_company(fs="OFS"))
    y = a.inputs.years
    assert [r.net_income for r in y] == [47900, 54400, 88100, 98100, 76000]    # 당기순이익
    assert [r.roe for r in y] == [14.76, 15.45, 21.22, 19.89, 13.62]           # ÷ 연말 자본총계 평균
    assert a.inputs.pbr == 0.66 and a.flags == ()
    assert a.notes == ("별도 재무제표 기준이에요", "2021년 ROE는 기말 자본 기준이에요", "PBR은 추정값이에요")
    assert a.sources["F33"] == "2025 사업보고서(별도, 접수번호 20260310000123) · ifrs-full_ProfitLoss"


def test_currency_flag_text_and_memo():
    a = assemble(*synthetic_company(currency="USD"))
    assert a.flags == ("원화가 아닌 재무제표예요(통화: USD). 숫자를 확인해 주세요.",)
    assert a.inputs.memo.endswith("KRX 2026-11-13 종가. 원화가 아닌 재무제표예요(통화: USD). 숫자를 확인해 주세요.")


def test_special_dividend_note_names_the_year():
    a = assemble(*synthetic_company(dps=3000, eps=2000))    # 3,000 ÷ 2,000 = 1.5
    assert [n for n in a.notes if "특별배당" in n] == ["2025년 배당성향이 100%를 넘어요(특별배당 의심)"]


def test_split_puts_old_eps_and_closes_on_one_basis(base):
    a = assemble(*synthetic_company(split_ratio=2))
    assert [r.eps for r in a.inputs.years] == [5937, 6747.5, 11084, 12446.5, 9691]
    assert [r.per for r in a.inputs.years] == [r.per for r in base.inputs.years]   # 종가도 같은 기준으로 바꿔요
    assert a.flags == (SPLIT_FLAG,) and a.inputs.pbr == base.inputs.pbr
    assert a.sources["B27"] == f"{B_REPORT} · ifrs-full_BasicEarningsLossPerShare ÷ 2(액면분할 조정)"
    assert a.sources["B28"] == "2021-12-30 종가 × 0.5(주식 수 변화 반영) ÷ EPS"
    assert a.inputs.memo.endswith(f"종가. {SPLIT_FLAG}")


def test_restated_overlap_eps_is_flagged_not_adjusted():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    fin_b = _set_amount(fin_b, "ifrs-full_BasicEarningsLossPerShare", "thstrm", "23,500")   # A의 22,168과 6% 차이
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert a.flags == (RESTATE_FLAG,) and a.inputs.years[0].eps == ORIGINAL_OLD_EPS


def test_share_jump_in_older_dps_years_is_flagged():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    ye = {**ye, 2017: PriceRow(date(2017, 12, 28), "000270", "기아", "KOSPI", 33_400.0, SYN_SHARES / 2)}
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert a.flags == (SPLIT_FLAG,) and [r.eps for r in a.inputs.years] == [11874, 13495, 22168, 24893, 19382]


def test_share_jump_after_latest_year_without_price_move_is_flagged_not_adjusted(base):
    # 유상증자처럼 주식 수만 늘고 주가는 그대로면 분할로 보지 않아요: 숫자는 그대로, 확인 표시만 달아요.
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, fin_b, divs, ye, replace(price, shares=SYN_SHARES * 10.0), d)
    assert a.flags == (SPLIT_FLAG,)
    assert a.inputs.years == base.inputs.years and a.inputs.prior_dps == base.inputs.prior_dps
    assert not any("주식 수 기준으로 나눴어요" in n for n in a.notes)


def _split_after_latest(r: float) -> tuple:
    """L년(2025) 말 뒤에 r:1 액면분할한 합성 회사: 현재가 ÷r, 현재 주식 수 ×r. 연말 자료는 옛 기준 그대로예요."""
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    return co, L, fin_a, fin_b, divs, ye, replace(price, close=price.close / r, shares=price.shares * r), d


def test_split_after_latest_year_rebases_per_share_values(base):
    a = assemble(*_split_after_latest(10))
    assert [r.eps for r in a.inputs.years] == [r.eps / 10 for r in base.inputs.years]
    assert [r.dps for r in a.inputs.years] == [r.dps / 10 for r in base.inputs.years]
    assert list(a.inputs.prior_dps) == [v / 10 for v in base.inputs.prior_dps]
    assert [r.per for r in a.inputs.years] == [r.per for r in base.inputs.years]   # PER은 주식 수 기준과 무관해요
    assert a.inputs.pbr == base.inputs.pbr == 0.65                                   # BPS도 지금 기준이에요
    assert a.flags == () and SPLIT_FLAG not in a.inputs.memo
    assert "2025년 말 뒤 주식 수가 10배가 돼서 EPS·배당을 지금 주식 수 기준으로 나눴어요" in a.notes
    tail = " ÷ 10(액면분할·무상증자 조정, 2025년 말 뒤)"
    for addr in ("B27", "F27", "B29", "F29", "B42", "F42"):
        assert a.sources[addr] == base.sources[addr] + tail
    assert a.sources["F28"] == base.sources["F28"]


YE_CLOSE_2025 = 121_700.0   # 합성 회사 2025년 말 종가


def _after_latest(r: float, price_moves: bool = True, before: float | None = None, **knobs) -> tuple:
    """L년 말 뒤 주식 수 ×r. before: 분할 전 주가(기본은 합성 현재가 97,000원).

    price_moves=False면 주가는 before 그대로예요 (유상증자 모양).
    """
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company(**knobs)
    before = price.close if before is None else before
    close = before / r if price_moves else before
    return co, L, fin_a, fin_b, divs, ye, replace(price, close=close, shares=price.shares * r), d


def test_small_share_jump_with_unchanged_price_is_flagged_not_adjusted(base):
    a = assemble(*_after_latest(1.5, price_moves=False, before=YE_CLOSE_2025))
    assert a.flags == (SPLIT_FLAG,) and a.inputs.years == base.inputs.years
    assert a.inputs.prior_dps == base.inputs.prior_dps


def test_small_split_with_price_move_is_adjusted(base):
    a = assemble(*_after_latest(1.5, before=YE_CLOSE_2025))
    assert a.flags == () and [r.eps for r in a.inputs.years] == [r.eps / 1.5 for r in base.inputs.years]
    assert "2025년 말 뒤 주식 수가 1.5배가 돼서 EPS·배당을 지금 주식 수 기준으로 나눴어요" in a.notes


def test_split_ratio_is_rounded_for_display(base):
    r = 1.5123456
    a = assemble(*_after_latest(r, before=YE_CLOSE_2025))
    assert "2025년 말 뒤 주식 수가 1.51배가 돼서 EPS·배당을 지금 주식 수 기준으로 나눴어요" in a.notes
    assert a.sources["F27"] == base.sources["F27"] + " ÷ 1.51(액면분할·무상증자 조정, 2025년 말 뒤)"
    assert a.inputs.years[4].eps == base.inputs.years[4].eps / r          # 계산은 반올림하지 않은 배수로


def test_reverse_split_after_latest_year_multiplies(base):
    a = assemble(*_after_latest(0.2))                                      # 5주를 1주로 병합
    assert a.flags == ()
    assert "2025년 말 뒤 주식 수가 1/5로 줄어서 EPS·배당을 지금 주식 수 기준으로 곱했어요" in a.notes
    assert a.sources["F27"] == base.sources["F27"] + " × 5(주식 병합 조정, 2025년 말 뒤)"
    assert [r.eps for r in a.inputs.years] == pytest.approx([r.eps * 5 for r in base.inputs.years])
    assert [r.per for r in a.inputs.years] == [r.per for r in base.inputs.years]


def test_split_already_in_report_eps_is_not_divided_again(base):
    # 사업보고서 승인 전에 분할이 끝나 A 보고서 EPS가 이미 새 주식 수 기준이에요 (순이익 ÷ EPS ≈ 지금 주식 수).
    a = assemble(*_after_latest(10, eps=1938.2))
    assert a.flags == (SPLIT_FLAG,) and not any("주식 수 기준으로" in n for n in a.notes)
    assert a.inputs.years[4].eps == 1938.2 and a.inputs.years[0].eps == base.inputs.years[0].eps
    assert [r.dps for r in a.inputs.years] == [r.dps for r in base.inputs.years]


def test_split_without_report_share_basis_is_flagged_not_adjusted(base):
    a = assemble(*_after_latest(10, eps=None))                             # EPS가 없으면 기준을 확인할 수 없어요
    assert SPLIT_FLAG in a.flags and not any("주식 수 기준으로" in n for n in a.notes)
    assert [r.dps for r in a.inputs.years] == [r.dps for r in base.inputs.years]


def test_split_after_latest_year_keeps_state_and_ratio(base):
    from vsf.config import ReportSettings
    from vsf.engine import watch_state

    want, got = (summarize(compute(x.inputs, Criteria())) for x in (base, assemble(*_split_after_latest(10))))
    assert (got.gate1, got.gate2, got.gate3, got.gate4) == (want.gate1, want.gate2, want.gate3, want.gate4)
    assert watch_state(got, ReportSettings()) == watch_state(want, ReportSettings())
    assert got.ratio == pytest.approx(want.ratio, rel=1e-9) and got.drop == pytest.approx(want.drop, rel=1e-9)
    assert got.fair_value == pytest.approx(want.fair_value / 10, rel=1e-9)


def test_non_positive_equity_leaves_roe_and_debt_blank_with_flag():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    fin_a = _set_amount(fin_a, "ifrs-full_Equity", "thstrm", "-1,000,000,000,000")
    fin_a = _set_amount(fin_a, EQUITY_PARENT, "thstrm", "-60,000,000,000,000")   # 평균 자본 (53.5 − 60) / 2 < 0
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert a.inputs.years[4].roe is None and a.inputs.years[4].debt_ratio is None and a.inputs.pbr is None
    assert a.inputs.years[3].roe == 19.84 and a.inputs.years[3].debt_ratio == 66.11
    assert a.flags == ("2025년 자본이 0 이하예요. ROE·부채비율을 확인해 주세요.",)


def test_name_matched_account_is_marked_in_source():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    rows = [{**r, "account_id": "-표준계정코드 미사용-"} if r["account_nm"] == "유형자산의 취득" else r
            for r in fin_a.rows]
    a = assemble(co, L, replace(fin_a, rows=rows), fin_b, divs, ye, price, d)
    assert a.inputs.years[4].capex == 30333
    assert a.sources["F35"] == f"{A_REPORT} · 유형자산의 취득(이름으로 찾음)"


# ---- 배당 보고서 ----

def test_dps_from_report_common_row_and_dash():
    assert dps_from_report(div_rows("6,800", "-", "5,600"), 2025) == {2025: 6800.0, 2024: 0.0, 2023: 5600.0}


def test_dps_from_report_fallbacks():
    def only(knd: str) -> list[dict]:
        return [{"se": "주당 현금배당금(원)", "stock_knd": knd, "thstrm": "1,000", "frmtrm": "", "lwfr": "-"}]
    blank = {2025: None, 2024: None, 2023: None}
    assert dps_from_report(only(""), 2025) == {2025: 1000.0, 2024: None, 2023: 0.0}   # 종류 표시 없는 줄 하나뿐
    assert dps_from_report(only("우선주"), 2025) == blank                             # 우선주 줄은 쓰지 않아요
    # 종류 칸이 빈 줄이 둘이면 서식 순서대로 첫 줄이 보통주예요 (한국쉘석유·SK텔레콤·오뚜기 등 실제 공시)
    assert dps_from_report(only("") + only("-"), 2025) == {2025: 1000.0, 2024: None, 2023: 0.0}
    assert dps_from_report(only("") * 3, 2025) == blank                                # 셋 이상이면 어느 줄인지 몰라요
    assert dps_from_report(only("-") + only("우선주"), 2025) == blank                    # 하나만 비어 있어도 몰라요
    assert dps_from_report([], 2025) == blank


def test_dps_by_year_newer_report_wins_and_flags_big_gaps():
    values, flags = dps_by_year({2025: div_rows("6,800", "6,500", "5,600"),
                                 2023: div_rows("5,750", "3,500", "3,000")})   # 2023년: 5,600 vs 5,750 (2.7%)
    assert values == {2025: 6800, 2024: 6500, 2023: 5600, 2022: 3500, 2021: 3000}
    assert flags == ("2023년 DPS가 보고서마다 달라요. 확인해 주세요.",)


def test_dps_by_year_small_gap_and_hole_in_newer_report():
    values, flags = dps_by_year({2025: div_rows("6,800", "6,500", "5,600"),
                                 2023: div_rows("5,700", "3,500", "3,000")})   # 1.8%는 괜찮아요
    assert values[2023] == 5600 and flags == ()
    values, flags = dps_by_year({2025: div_rows("6,800", "6,500", ""),
                                 2023: div_rows("5,750", "3,500", "3,000")})   # 최근 보고서에 값이 없으면 옛 보고서
    assert values[2023] == 5750 and flags == ()


@pytest.mark.parametrize("rows,want", [
    (div_rows("-", "1,000", "900"), True), (div_rows("1,000", "-", "900"), False), (div_rows("1,000", "900", "-"), False),
    (div_rows("1,000", "900", "800"), False), (div_rows("1,000", "", "800"), False),   # 빈 값은 '모름'
    ([], False), (None, False)])
def test_quick_fail_check_cases(rows, want):
    assert quick_fail_check(rows, 2025) is want


DASHES = ["-", "－", "–", "—", "‐", "−", " － ", "　—　"]


@pytest.mark.parametrize("dash", DASHES)
def test_dash_variants_mean_no_dividend(dash):
    rows = div_rows("1,000", dash, "900")
    assert dps_from_report(rows, 2025) == {2025: 1000.0, 2024: 0.0, 2023: 900.0}
    assert quick_fail_check(div_rows(dash, "1,000", "900"), 2025) is True
    assert dps_by_year({2025: rows}) == ({2025: 1000.0, 2024: 0.0, 2023: 900.0}, ())


@pytest.mark.parametrize("dash", DASHES[1:])
def test_dash_variant_skipped_year_fails_gate2_like_ascii_dash(dash):
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    price = replace(price, close=60000.0)
    with_dash = assemble(co, L, fin_a, fin_b, {**divs, 2023: div_rows("5,600", dash, "3,000", year=2023)},
                         ye, price, d)
    ascii_dash = assemble(co, L, fin_a, fin_b, {**divs, 2023: div_rows("5,600", "-", "3,000", year=2023)},
                          ye, price, d)
    assert with_dash.inputs == ascii_dash.inputs and with_dash.flags == ascii_dash.flags == ()
    assert with_dash.inputs.years[1].dps == 0.0
    assert summarize(compute(with_dash.inputs, Criteria())).gate2 == "탈락"


def test_unreadable_dps_text_is_blank_and_flagged():
    flag = "2024년 주당 현금배당금 값을 읽지 못했어요('해당없음'). 확인해 주세요."
    rows = div_rows("1,000", " 해당없음 ", "900")
    assert dps_from_report(rows, 2025) == {2025: 1000.0, 2024: None, 2023: 900.0}
    assert quick_fail_check(rows, 2025) is False
    assert dps_by_year({2025: rows}) == ({2025: 1000.0, 2024: None, 2023: 900.0}, (flag,))
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, fin_b, {**divs, 2025: div_rows("6,800", "해당없음", "5,600")}, ye, price, d)
    assert a.inputs.years[3].dps is None and a.flags == (flag,) and a.inputs.memo.endswith(flag)
    q = assemble_quick_fail(KIA_CO, 2025, {2025: div_rows("1,000", "-", "없음")}, PRICE, D)
    assert q.flags == ("2023년 주당 현금배당금 값을 읽지 못했어요('없음'). 확인해 주세요.",)


def test_blank_dps_stays_blank_without_flag():
    assert dps_by_year({2025: div_rows("1,000", "", "  ")}) == ({2025: 1000.0, 2024: None, 2023: None}, ())


def test_report_without_common_dps_row_is_flagged():
    flag = "2025년 사업보고서 배당 표에서 보통주 주당 현금배당금을 찾지 못했어요. 확인해 주세요."
    preferred_only = [r for r in div_rows("6,800", "6,500", "5,600") if r["stock_knd"] != "보통주"]
    blank = {2025: None, 2024: None, 2023: None}
    assert dps_by_year({2025: preferred_only}) == (blank, (flag,))
    assert dps_by_year({2025: []}) == (blank, (flag,))                     # 표가 비어 있어도 마찬가지
    three_unknown = [{"se": "주당 현금배당금(원)", "stock_knd": "", "thstrm": "1", "frmtrm": "1", "lwfr": "1"}] * 3
    assert dps_by_year({2025: three_unknown}) == (blank, (flag,))          # 어느 줄인지 모르면
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    divs = {**divs, 2023: [r for r in divs[2023] if r["stock_knd"] != "보통주"]}
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert a.flags == ("2023년 사업보고서 배당 표에서 보통주 주당 현금배당금을 찾지 못했어요. 확인해 주세요.",)
    assert a.inputs.years[1].dps is None                                     # 2022년은 2023 보고서에만 있어요


def test_quick_fail_fills_only_basics():
    a = assemble_quick_fail(KIA_CO, 2025, {2025: div_rows("1,000", "-", "900")}, PRICE, D)
    i = a.inputs
    assert (i.name, i.code, i.price, i.price_date) == ("기아", "000270", 97000, D)
    assert [r.year for r in i.years] == YEARS and i.prior_years == (2016, 2017, 2018, 2019, 2020)
    assert [r.dps for r in i.years] == [None, None, 900, 0.0, 1000]
    assert all(getattr(r, f) is None for r in i.years for f in FIN_FIELDS)
    assert i.memo == "" and i.pbr is None and i.prior_dps == (None,) * 5
    assert a.notes == ("최근 해에 배당을 주지 않아 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요.",)
    assert a.flags == () and a.latest_year == 2025 and set(a.sources) == _filled(i)
    assert a.sources["E29"] == "2025 사업보고서 배당에 관한 사항(보통주, 접수번호 20260310000123)"


# ---- 스펙 6.6 자동 숫자 확인 ----

NI_PARENT = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
OCF = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
EPS_ID = "ifrs-full_BasicEarningsLossPerShare"


def _with_2025_close(close: float):
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    ye = {**ye, 2025: replace(ye[2025], close=close)}
    return assemble(co, L, fin_a, fin_b, divs, ye, price, d)


def test_sign_mismatch_flag_text_and_clean_case(base):
    assert base.flags == ()
    a = assemble(*synthetic_company(eps=-100))
    assert a.flags == ("2025년 EPS와 순이익의 부호가 달라요. 숫자를 확인해 주세요.",)
    assert a.inputs.years[4].eps == -100 and a.inputs.years[4].per is None


def test_sign_mismatch_uses_row_33_income_and_skips_zero():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, _set_amount(fin_a, NI_PARENT, "frmtrm", "-5,000,000,000"), fin_b, divs, ye, price, d)
    assert a.flags == ("2024년 EPS와 순이익의 부호가 달라요. 숫자를 확인해 주세요.",)
    assert assemble(*synthetic_company(eps=0)).flags == ()      # 0은 부호가 없어요


def test_ofs_sign_check_uses_profit_loss():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company(fs="OFS")
    a = assemble(co, L, _set_amount(fin_a, "ifrs-full_ProfitLoss", "thstrm", "-1,000,000,000"),
                 fin_b, divs, ye, price, d)
    assert a.flags == ("2025년 EPS와 순이익의 부호가 달라요. 숫자를 확인해 주세요.",)


@pytest.mark.parametrize("close,flag", [
    (1500 * 19382, "2025년 연말 PER이 1500배로 비정상적이에요(단위 오류 가능성). 숫자를 확인해 주세요."),
    (999 * 19382, None),
    (0.4 * 19382, "2025년 연말 PER이 0.4배로 비정상적이에요(단위 오류 가능성). 숫자를 확인해 주세요."),
])
def test_unit_error_per_flag(close, flag):
    a = _with_2025_close(close)
    assert a.flags == (() if flag is None else (flag,))
    assert a.inputs.years[4].per == round(close / 19382, 2)      # PER은 그대로 둬요


def test_overlap_net_income_and_ocf_mismatch_flags():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    ni_3pct = _set_amount(fin_b, NI_PARENT, "thstrm", "9,040,279,100,000")    # A 8,776,970,000,000의 3%↑
    a = assemble(co, L, fin_a, ni_3pct, divs, ye, price, d)
    assert a.flags == ("2023년 순이익이(가) 보고서마다 달라요(정정·재작성 가능성). 확인해 주세요.",)
    ocf_3pct = _set_amount(fin_b, OCF, "thstrm", "11,639,000,000,000")        # A 11,300,000,000,000의 3%↑
    a = assemble(co, L, fin_a, ocf_3pct, divs, ye, price, d)
    assert a.flags == ("2023년 영업활동현금흐름이(가) 보고서마다 달라요(정정·재작성 가능성). 확인해 주세요.",)
    assert a.inputs.years[2].ocf == 113000                                     # A 값을 써요


def test_overlap_small_difference_and_missing_values_do_not_flag():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    fin_b = _set_amount(fin_b, NI_PARENT, "thstrm", "8,864,739,700,000")      # 1%↑
    fin_b = _set_amount(fin_b, OCF, "thstrm", "11,413,000,000,000")           # 1%↑
    assert assemble(co, L, fin_a, fin_b, divs, ye, price, d).flags == ()
    fin_b = _set_amount(fin_b, NI_PARENT, "thstrm", "")
    fin_b = _set_amount(fin_b, OCF, "thstrm", "0")
    assert assemble(co, L, fin_a, fin_b, divs, ye, price, d).flags == ()


def test_overlap_year_uses_a_report_values_everywhere():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    base_years = assemble(co, L, fin_a, fin_b, divs, ye, price, d).inputs.years
    for account_id, text in ((EPS_ID, "23,500"), (NI_PARENT, "9,040,279,100,000"),
                             ("ifrs-full_Liabilities", "40,000,000,000,000"),
                             ("ifrs-full_Equity", "50,000,000,000,000"),
                             (OCF, "11,639,000,000,000")):
        fin_b = _set_amount(fin_b, account_id, "thstrm", text)
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert a.inputs.years[2] == base_years[2]                                  # D열은 A 값 그대로
    assert (a.inputs.years[2].eps, a.inputs.years[2].net_income, a.inputs.years[2].ocf,
            a.inputs.years[2].debt_ratio) == (22168, 87769.7, 113000, 73.19)
    assert a.sources["D27"].startswith(A_REPORT) and a.sources["D33"].startswith(A_REPORT)
    assert a.sources["D31"].startswith(A_REPORT) and a.sources["D34"].startswith(A_REPORT)
    assert B_REPORT not in a.sources["D27"] + a.sources["D33"]
    assert set(a.flags) == {RESTATE_FLAG,
                            "2023년 순이익이(가) 보고서마다 달라요(정정·재작성 가능성). 확인해 주세요.",
                            "2023년 영업활동현금흐름이(가) 보고서마다 달라요(정정·재작성 가능성). 확인해 주세요."}


def test_split_after_latest_year_keeps_per_on_base_share_basis(base):
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, fin_b, divs, ye, replace(price, close=19_400.0, shares=SYN_SHARES * 5.0), d)
    assert [r.per for r in a.inputs.years] == [r.per for r in base.inputs.years]
    assert [r.per for r in a.inputs.years] == [6.96, 4.39, 4.51, 4.05, 6.28]
    assert a.flags == () and "2025년 말 뒤 주식 수가 5배가 돼서 EPS·배당을 지금 주식 수 기준으로 나눴어요" in a.notes


def test_cfs_without_parent_net_income_does_not_fall_back_to_profit_loss():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    fin_a = replace(fin_a, rows=[r for r in fin_a.rows if r["account_id"] != NI_PARENT])
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    # 2024·2025는 비어요 (당기순이익으로 대신하지 않아요). 2023은 겹치는 해라 B 보고서의 지배주주 순이익이에요.
    assert [r.net_income for r in a.inputs.years] == [47604.5, 54094.29, 87769.7, None, None]
    assert not {"E33", "F33"} & a.sources.keys() and "C33" in a.sources
    assert a.sources["D33"] == f"{B_REPORT} · {NI_PARENT}"
    assert [r.roe for r in a.inputs.years[2:]] == [21.17, None, None]


# ---- 겹치는 해(L−2): A 보고서 전전기 값이 없으면 B 보고서 당기 값 ----

CAPEX_ID = "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
DIV_PAID_ID = "ifrs-full_DividendsPaidClassifiedAsFinancingActivities"


def _a_blank_b_set(account_id: str, b_text: str) -> tuple:
    """A(2025) 보고서의 2023년(전전기) 값을 지우고, B(2023) 보고서의 2023년(당기) 값을 b_text로 바꾼 인자 묶음."""
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    return (co, L, _set_amount(fin_a, account_id, "bfefrmtrm", ""), _set_amount(fin_b, account_id, "thstrm", b_text),
            divs, ye, price, d)


def test_overlap_year_ocf_falls_back_to_b_report():
    a = assemble(*_a_blank_b_set(OCF, "11,639,000,000,000"))
    assert a.inputs.years[2].ocf == 116390                                  # A에 없어서 B 값
    assert a.sources["D34"] == f"{B_REPORT} · {OCF}"
    assert a.flags == ()


@pytest.mark.parametrize("account_id,b_text,field,want,cell,source", [
    (EPS_ID, "23,000", "eps", 23000, "D27", f"{B_REPORT} · {EPS_ID}"),
    (NI_PARENT, "9,000,000,000,000", "net_income", 90000, "D33", f"{B_REPORT} · {NI_PARENT}"),
    (CAPEX_ID, "-2,600,000,000,000", "capex", 26000, "D35", f"{B_REPORT} · {CAPEX_ID}"),
    (DIV_PAID_ID, "-1,500,000,000,000", "dividends_paid", 15000, "D36", f"{B_REPORT} · {DIV_PAID_ID}"),
    # 부채 36조(B) ÷ 자본 45.06조(A) × 100, 부채 32.98조(A) ÷ 자본 50조(B) × 100
    ("ifrs-full_Liabilities", "36,000,000,000,000", "debt_ratio", 79.89, "D31", f"{A_REPORT}, {B_REPORT} · 부채총계 ÷ 자본총계"),
    ("ifrs-full_Equity", "50,000,000,000,000", "debt_ratio", 65.96, "D31", f"{A_REPORT}, {B_REPORT} · 부채총계 ÷ 자본총계"),
    # 영업이익 12조(B) ÷ 이자비용 1,842억(A), 영업이익 11.6079조(A) ÷ 이자비용 2,000억(B)
    ("dart_OperatingIncomeLoss", "12,000,000,000,000", "interest_coverage", 65.15, "D32",
     f"{A_REPORT}, {B_REPORT} · 영업이익 ÷ 이자비용"),
    ("ifrs-full_InterestExpense", "200,000,000,000", "interest_coverage", 58.04, "D32",
     f"{A_REPORT}, {B_REPORT} · 영업이익 ÷ 이자비용"),
])
def test_overlap_year_falls_back_to_b_report_field_by_field(account_id, b_text, field, want, cell, source):
    a = assemble(*_a_blank_b_set(account_id, b_text))
    assert getattr(a.inputs.years[2], field) == want
    assert a.sources[cell] == source
    assert a.flags == () and not any(n.startswith("2023년 이자보상배율") for n in a.notes)


def test_overlap_year_net_income_from_b_feeds_roe():
    a = assemble(*_a_blank_b_set(NI_PARENT, "9,000,000,000,000"))
    assert a.inputs.years[2].roe == 21.71                                    # 9 ÷ ((37.9 + 45.0) / 2) × 100


def test_overlap_year_stays_blank_when_both_reports_are_blank():
    a = assemble(*_a_blank_b_set(OCF, ""))
    assert a.inputs.years[2].ocf is None and "D34" not in a.sources


# ---- 2026-11-15 실제 자료 51곳 기능 시험에서 찾은 모양들 ----

def _dps(knd: str, a: str, b: str, c: str) -> dict:
    return {"se": "주당 현금배당금(원)", "stock_knd": knd, "thstrm": a, "frmtrm": b, "lwfr": c}


def test_dps_common_row_spelled_with_sik_or_left_blank():
    # 클래시스 2025: '보통주식'·'종류주식'
    assert dps_from_report([_dps("보통주식", "1,000", "257", "200"), _dps("종류주식", "-", "-", "-")], 2025) == \
        {2025: 1000.0, 2024: 257.0, 2023: 200.0}
    # 한국쉘석유 2025: 종류 칸이 모두 '-'이고 보통주 줄이 먼저, 우선주 줄은 모두 '-'
    shell = [_dps("-", "36,000", "27,000", "25,000"), _dps("-", "-", "-", "-")]
    assert dps_by_year({2025: shell}) == ({2025: 36000.0, 2024: 27000.0, 2023: 25000.0}, ())


def _no_minority(fin, *, nci: bool = False, same_equity: bool = True):
    """S-Oil 모양: 연결재무제표인데 '지배기업 소유주' 순이익 줄이 없고 지배기업 자본 = 자본총계."""
    from vsf.data.dart import FinRows

    total = next(r for r in fin.rows if r["account_id"] == "ifrs-full_Equity")
    amounts = ("thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount")
    rows = []
    for r in fin.rows:
        if r["account_id"] == "ifrs-full_ProfitLossAttributableToOwnersOfParent":
            continue
        if same_equity and r["account_id"] == "ifrs-full_EquityAttributableToOwnersOfParent":
            r = {**r, **{k: total[k] for k in amounts}}
        rows.append(r)
    if nci:
        rows.append(fin_row("IS", "ifrs-full_ProfitLossAttributableToNonControllingInterests", "비지배지분",
                            "30,000,000,000", "30,000,000,000", "30,000,000,000"))
    return FinRows(rows=rows, fs=fin.fs, rcept_no=fin.rcept_no)


def test_consolidated_without_minority_uses_total_net_income():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, _no_minority(fin_a), _no_minority(fin_b), divs, ye, price, d)
    profit = (4_790_000_000_000, 5_440_000_000_000, 8_810_000_000_000, 9_810_000_000_000, 7_600_000_000_000)
    assert [y.net_income for y in a.inputs.years] == [v / 1e8 for v in profit]
    assert all(y.roe is not None for y in a.inputs.years) and a.flags == ()
    assert "비지배지분 없음" in a.sources["F33"]
    # 비지배 순이익 줄이 있거나, 지배기업 자본이 자본총계와 다르면 지금처럼 비워요
    for kw in ({"nci": True}, {"same_equity": False}):
        b = assemble(co, L, _no_minority(fin_a, **kw), _no_minority(fin_b, **kw), divs, ye, price, d)
        assert all(y.net_income is None for y in b.inputs.years), kw


def test_financial_company_leaves_sector_mismatched_numbers_blank():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(replace(co, financial_kind="은행"), L, fin_a, fin_b, divs, ye, price, d)
    for y in a.inputs.years:
        assert (y.debt_ratio, y.interest_coverage, y.ocf, y.capex) == (None, None, None, None)
        assert None not in (y.eps, y.roe, y.net_income, y.dividends_paid)
    assert not any(cell[1:] in ("31", "32", "34", "35") for cell in a.sources)
    assert not any("이자보상배율" in n for n in a.notes)
    assert a.flags == ()
    assert assemble(co, L, fin_a, fin_b, divs, ye, price, d).inputs.years[0].debt_ratio is not None


def test_financial_company_has_no_cash_flow_overlap_flag():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    ocf_3pct = _set_amount(fin_b, OCF, "thstrm", "11,639,000,000,000")
    bank = assemble(replace(co, financial_kind="은행"), L, fin_a, ocf_3pct, divs, ye, price, d)
    assert not any("영업활동현금흐름" in f for f in bank.flags)
    general = assemble(co, L, fin_a, ocf_3pct, divs, ye, price, d)
    assert any("영업활동현금흐름" in f for f in general.flags)


# ---- 옛 배당 보고서의 액면분할 (주당액면가액으로 지금 기준에 맞춰요) ----

_F100 = ("100", "100", "100")
_F5000 = ("5,000", "5,000", "5,000")


def _samsung_like_divs() -> dict[int, list[dict]]:
    """2018년에 50:1 액면분할한 회사(삼성전자 실제 공시 모양): 2017 보고서는 액면가 5,000원 기준, 그 뒤는 100원 기준."""
    return {2025: div_rows("1,668", "1,446", "1,444", year=2025, face=_F100),
            2023: div_rows("1,444", "1,444", "1,444", year=2023, face=_F100),
            2021: div_rows("1,444", "2,994", "1,416", year=2021, face=_F100),
            2019: div_rows("1,416", "1,416", "850", year=2019, face=_F100),
            2017: div_rows("42,500", "28,500", "21,000", year=2017, face=_F5000)}


def test_older_report_on_old_face_value_is_scaled_to_current_basis():
    values, flags = dps_by_year(_samsung_like_divs())
    assert values[2016] == 570 and values[2015] == 420     # 28,500 × 100/5,000, 21,000 × 100/5,000
    assert values[2017] == 850 and values[2020] == 2994
    assert flags == ()                                      # 2017년 42,500 ÷ 50 = 850: 두 보고서가 맞아요


def test_face_value_is_read_per_column_within_one_report():
    # 한 보고서 안에서 해마다 액면가를 따로 적은 실제 공시 모양: 전전기만 옛 액면가 기준이에요.
    values, flags = dps_by_year({2025: div_rows("400", "350", "3,000", face=("500", "500", "5,000"))})
    assert values == {2025: 400, 2024: 350, 2023: 300} and flags == ()


@pytest.mark.parametrize("old_face", [("-", "-", "-"), ("", "", ""), ("무액면", "무액면", "무액면")])
def test_unknown_face_value_leaves_dps_unchanged(old_face):
    values, _ = dps_by_year({2025: div_rows("1,668", "1,446", "1,444", face=_F100),
                             2023: div_rows("1,444", "28,500", "21,000", year=2023, face=old_face)})
    assert values[2022] == 28500 and values[2021] == 21000


def test_unknown_current_face_value_leaves_dps_unchanged():
    values, _ = dps_by_year({2025: div_rows("1,668", "1,446", "1,444", face=("-", "-", "-")),
                             2023: div_rows("1,444", "28,500", "21,000", year=2023, face=_F5000)})
    assert values[2022] == 28500


def test_face_value_scaling_is_noted_and_sourced():
    co, L, fin_a, fin_b, _, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, fin_b, _samsung_like_divs(), ye, price, d)
    assert a.inputs.prior_dps == (570, 850, 1416, 1416, 2994)   # 2016–2020년
    assert "액면가 5,000원 기준이라 지금 액면가 100원 기준으로 맞췄어요" in " ".join(a.notes)
    assert a.sources["B42"].endswith(" × 100/5,000(액면분할 조정)")   # 2016년: 2017 보고서 값
    assert "액면" not in a.sources["C42"]                               # 2017년: 2019 보고서(100원 기준) 값


def test_old_share_jump_explained_by_face_value_is_not_flagged():
    # 2018년 50:1 분할: 2016·2017년 말 주식 수는 1/50이지만 액면가 변화로 설명돼요.
    co, L, fin_a, fin_b, _, ye, price, d = synthetic_company()
    old = {y: PriceRow(date(y, 12, 28), "000270", "기아", "KOSPI", 2_000_000.0, SYN_SHARES / 50)
           for y in (2016, 2017)}
    a = assemble(co, L, fin_a, fin_b, _samsung_like_divs(), {**ye, **old}, price, d)
    assert SPLIT_FLAG not in a.flags


def test_old_share_jump_without_face_value_change_is_still_flagged():
    co, L, fin_a, fin_b, _, ye, price, d = synthetic_company()
    divs = {y: div_rows("1,000", "1,000", "1,000", year=y, face=_F100) for y in (2025, 2023, 2021, 2019, 2017)}
    old = {2017: PriceRow(date(2017, 12, 28), "000270", "기아", "KOSPI", 2_000_000.0, SYN_SHARES / 50)}
    a = assemble(co, L, fin_a, fin_b, divs, {**ye, **old}, price, d)
    assert SPLIT_FLAG in a.flags


def test_recent_share_jump_stays_flagged_even_with_face_value_change():
    # 최근 5년 안의 분할은 EPS도 걸려 있어서, 액면가로 배당을 맞춰도 확인 표시는 그대로예요.
    co, L, fin_a, fin_b, _, ye, price, d = synthetic_company()
    divs = _samsung_like_divs()
    divs[2023] = div_rows("1,444", "1,444", "72,200", year=2023, face=("100", "100", "5,000"))
    ye = {**ye, 2021: replace(ye[2021], shares=SYN_SHARES / 50)}
    a = assemble(co, L, fin_a, fin_b, divs, ye, price, d)
    assert SPLIT_FLAG in a.flags and a.inputs.years[0].dps == 1444


# ---- 우선주 (2026-11-24 우선주 설계 4장) ----

from vsf.data.assemble import PREF_NOTE, PreferredShare  # noqa: E402
from vsf.data.store import PriceRow as _PR  # noqa: E402


def _plus50(v: str) -> str:
    return v if v.strip() in ("-", "") else f"{int(v.replace(',', '')) + 50:,}"


def preferred_case(pref_dps: bool = True):
    """합성 회사의 우선주: 배당은 보통주 + 50원, 주가는 보통주의 60%."""
    from helpers import _SYN_DPS
    company, L, fa, fb, divs, ye, price, d = synthetic_company()
    pdivs = {y: div_rows(*v, year=y, pref=tuple(_plus50(x) for x in v) if pref_dps else ("-", "-", "-"))
             for y, v in _SYN_DPS.items()}
    p_ye = {y: _PR(r.date, "000275", "기아우", "KOSPI", r.close * 0.6, 1_000_000.0) for y, r in ye.items()}
    pref = PreferredShare(code="000275", name="기아우", price=_PR(d, "000275", "기아우", "KOSPI", price.close * 0.6, 1e6),
                          year_end=p_ye)
    info = replace(company, code="000275", name="기아우", common_code="000270")
    common = assemble(company, L, fa, fb, pdivs, ye, price, d)
    got = assemble(info, L, fa, fb, pdivs, ye, price, d, preferred=pref)
    return common, got


def test_preferred_uses_its_own_dividends_price_and_year_end_per():
    common, got = preferred_case()
    ci, pi = common.inputs, got.inputs
    assert (pi.name, pi.code) == ("기아우", "000275") and pi.price == ci.price * 0.6
    assert [y.dps for y in pi.years] == [None if v is None else v + 50 for v in (y.dps for y in ci.years)]
    assert [v for v in pi.prior_dps] == [None if v is None else v + 50 for v in ci.prior_dps]
    for cy, py in zip(ci.years, pi.years, strict=True):
        assert py.eps == cy.eps and py.roe == cy.roe and py.net_income == cy.net_income   # 같은 회사 재무
        if cy.per is not None:
            assert abs(py.per - cy.per * 0.6) < 0.02                                         # 우선주 연말 종가 ÷ EPS
    assert abs(pi.pbr - ci.pbr * 0.6) < 0.02
    assert "우선주" in got.sources["E29"] and pi.memo.startswith("우선주: 재무는 보통주(000270) 것")
    assert PREF_NOTE in got.notes


def test_preferred_without_dividend_row_is_flagged():
    _, got = preferred_case(pref_dps=False)
    assert all(y.dps in (None, 0.0) for y in got.inputs.years)


def test_quick_fail_check_by_share_kind():
    rows = div_rows("1,000", "900", "800", pref=("-", "950", "850"))
    assert quick_fail_check(rows, 2025) is False
    assert quick_fail_check(rows, 2025, kind="우선") is True
