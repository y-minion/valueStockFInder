"""계산기 입력 조립. 녹화 자료 테스트(recorded) 말고는 모두 합성 회사로 돌아요."""
import math
from dataclasses import replace
from datetime import date

import pytest

from helpers import (ORIGINAL_OLD_EPS, SYN_SHARES, div_rows, load_company, load_divs, load_fin,
                     load_price, load_year_end, synthetic_company)
from vsf.data.assemble import (Assembled, assemble, assemble_quick_fail, dps_by_year,
                               dps_from_report, quick_fail_check)
from vsf.data.splits import RESTATE_FLAG, SPLIT_FLAG
from vsf.data.store import PriceRow
from vsf.model import to_cells

# 합성 기아(가짜 고유번호 99000270)와 현재가 97,000원. D = 2026-11-13
KIA_CO, _, _, _, _, _, PRICE, D = synthetic_company()

YEARS = [2021, 2022, 2023, 2024, 2025]
FIN_FIELDS = ("eps", "per", "roe", "debt_ratio", "interest_coverage", "net_income", "ocf", "capex",
              "dividends_paid")
EQUITY_PARENT = "ifrs-full_EquityAttributableToOwnersOfParent"


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


# ---- 계획서의 합성 자료 테스트 ----

def test_interest_proxy_and_999():
    a = assemble(*synthetic_company(interest_expense=None, interest_paid=0))
    assert a.inputs.years[4].interest_coverage == 999 and any("이자의 지급" in n for n in a.notes)


def test_ofs_note():
    assert "별도 재무제표 기준이에요" in assemble(*synthetic_company(fs="OFS")).notes


def test_non_krw_flagged():
    assert any("원화가 아닌" in f for f in assemble(*synthetic_company(currency="USD")).flags)


def test_quick_fail_detection():
    assert quick_fail_check(div_rows(thstrm="1,000", frmtrm="-", lwfr="900"), 2025)


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


def test_pbr_estimate(base):
    # 97,000 ÷ (58조 ÷ (7,560,983,456,789 ÷ 19,382)) = 0.652…
    assert base.inputs.pbr == 0.65 and "PBR은 추정값이에요" in base.notes
    assert base.sources["B22"] == "2026-11-13 종가 ÷ 추정 BPS(2025 사업보고서(연결) · 자본 ÷ (순이익 ÷ EPS))"


def test_pbr_and_per_need_positive_eps():
    a = assemble(*synthetic_company(eps=-500))
    assert a.inputs.years[4].per is None and a.inputs.pbr is None
    assert "PBR은 추정값이에요" not in a.notes and "B22" not in a.sources and "F28" not in a.sources


def test_sources_examples(base):
    s = base.sources
    assert s["F27"] == "2025 사업보고서(연결) · ifrs-full_BasicEarningsLossPerShare"
    assert s["B27"] == "2023 사업보고서(연결) · ifrs-full_BasicEarningsLossPerShare"
    assert s["B28"] == "2021-12-30 종가 ÷ EPS"
    assert s["F29"] == "2025 사업보고서 배당에 관한 사항(보통주)"
    assert s["D29"] == "2025 사업보고서 배당에 관한 사항(보통주)"    # 2023년은 두 보고서에 있고 최근 것이 먼저
    assert s["C29"] == "2023 사업보고서 배당에 관한 사항(보통주)"
    assert s["F42"] == "2021 사업보고서 배당에 관한 사항(보통주)"
    assert s["D30"] == "2025·2023 사업보고서(연결) · 순이익 ÷ 2022·2023년 말 평균 자본"
    assert s["B30"] == "2023 사업보고서(연결) · 순이익 ÷ 2021년 말 자본"
    assert s["F31"] == "2025 사업보고서(연결) · 부채총계 ÷ 자본총계"
    assert s["F32"] == "2025 사업보고서(연결) · 영업이익 ÷ 이자비용"
    assert s["F33"] == "2025 사업보고서(연결) · ifrs-full_ProfitLossAttributableToOwnersOfParent"
    assert s["B35"] == ("2023 사업보고서(연결) · "
                       "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
    assert s["B20"] == "KRX 2026-11-13 종가" and s["B18"] == "KRX 종목 목록 · DART 고유번호 99000270"


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
    assert a.sources["F32"] == "2025 사업보고서(연결) · 영업이익 ÷ 이자의 지급(0이라 999)"


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
    assert a.sources["F33"] == "2025 사업보고서(별도) · ifrs-full_ProfitLoss"


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
    assert a.sources["B27"] == "2023 사업보고서(연결) · ifrs-full_BasicEarningsLossPerShare ÷ 2(액면분할 조정)"
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


def test_split_after_latest_year_is_flagged():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fin_a, fin_b, divs, ye, replace(price, close=19_400.0, shares=SYN_SHARES * 5.0), d)
    assert a.flags == (SPLIT_FLAG,)   # 현재가는 새 주식 수 기준인데 EPS는 옛 기준이에요


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
    assert a.sources["F35"] == "2025 사업보고서(연결) · 유형자산의 취득(이름으로 찾음)"


# ---- 배당 보고서 ----

def test_dps_from_report_common_row_and_dash():
    assert dps_from_report(div_rows("6,800", "-", "5,600"), 2025) == {2025: 6800.0, 2024: 0.0, 2023: 5600.0}


def test_dps_from_report_fallbacks():
    def only(knd: str) -> list[dict]:
        return [{"se": "주당 현금배당금(원)", "stock_knd": knd, "thstrm": "1,000", "frmtrm": "", "lwfr": "-"}]
    blank = {2025: None, 2024: None, 2023: None}
    assert dps_from_report(only(""), 2025) == {2025: 1000.0, 2024: None, 2023: 0.0}   # 종류 표시 없는 줄 하나뿐
    assert dps_from_report(only("우선주"), 2025) == blank                             # 우선주 줄은 쓰지 않아요
    assert dps_from_report(only("") + only("-"), 2025) == blank                        # 어느 줄인지 모르면 비워요
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
    (div_rows("1,000", "-", "900"), True), (div_rows("1,000", "900", "-"), True),
    (div_rows("1,000", "900", "800"), False), (div_rows("1,000", "", "800"), False),   # 빈 값은 '모름'
    ([], False), (None, False)])
def test_quick_fail_check_cases(rows, want):
    assert quick_fail_check(rows, 2025) is want


def test_quick_fail_fills_only_basics():
    a = assemble_quick_fail(KIA_CO, 2025, {2025: div_rows("1,000", "-", "900")}, PRICE, D)
    i = a.inputs
    assert (i.name, i.code, i.price, i.price_date) == ("기아", "000270", 97000, D)
    assert [r.year for r in i.years] == YEARS and i.prior_years == (2016, 2017, 2018, 2019, 2020)
    assert [r.dps for r in i.years] == [None, None, 900, 0.0, 1000]
    assert all(getattr(r, f) is None for r in i.years for f in FIN_FIELDS)
    assert i.memo == "" and i.pbr is None and i.prior_dps == (None,) * 5
    assert a.notes == ("최근 3년 중 배당을 안 준 해가 있어 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요.",)
    assert a.flags == () and a.latest_year == 2025 and set(a.sources) == _filled(i)
    assert a.sources["E29"] == "2025 사업보고서 배당에 관한 사항(보통주)"
