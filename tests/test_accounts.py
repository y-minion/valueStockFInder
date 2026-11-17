import math

import pytest

from helpers import fin_row, load_fin, synthetic
from vsf.data.accounts import PERIODS, Sourced, extract, parse_amount

FIELDS = {"net_income_parent", "net_income_nci", "profit_loss", "eps", "equity_parent", "equity_total",
          "liabilities", "current_assets", "operating_income", "interest_expense", "interest_paid", "ocf", "capex",
          "dividends_paid", "equity_begin_parent", "equity_begin_total"}
CONT = "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"
DISC = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"
NO_ID = "-표준계정코드 미사용-"


@pytest.mark.recorded
def test_kia_2025_core_accounts():
    e = extract(load_fin("kia_2025_cfs"), "thstrm")
    assert e["eps"].value == 19382
    assert math.isclose(e["net_income_parent"].value / 1e8, 75609.83, rel_tol=0.005)
    assert e["ocf"].value > 0 and e["capex"].value > 0 and e["capex"].how in ("id", "name")


@pytest.mark.recorded
def test_cheil_2025_core_accounts():
    e = extract(load_fin("cheil_2025_cfs"), "thstrm")
    assert e["eps"].value == 2049 and math.isclose(e["net_income_parent"].value / 1e8, 2075.46, rel_tol=0.005)


def test_name_fallback():   # account_id "-표준계정코드 미사용-"인 합성 행
    assert extract(synthetic(capex_name="유형자산의 취득"), "thstrm")["capex"].how == "name"


def test_common_share_eps_preferred():
    assert extract(synthetic(eps_rows=[("우선주기본주당이익", 110), ("보통주기본주당이익", 100)]), "thstrm")["eps"].value == 100


def test_missing_interest_expense_is_none():
    assert extract(synthetic(), "thstrm")["interest_expense"].value is None


@pytest.mark.parametrize("s,want", [("1,234", 1234.0), ("-1,234", -1234.0), ("", None), ("-", None), (None, None),
                                    (" 1,234 ", 1234.0), ("abc", None), ("nan", None)])
def test_parse_amount(s, want):
    assert parse_amount(s) == want


def test_all_fields_and_not_found_shape():
    e = extract(synthetic(), "thstrm")
    assert set(e) == FIELDS and PERIODS == ("thstrm", "frmtrm", "bfefrmtrm")
    assert e["interest_paid"] == Sourced(None, "", "id")


def test_periods_pick_matching_amount_column():
    fin = synthetic()
    assert [extract(fin, p)["liabilities"].value for p in PERIODS] == [8e6, 7e6, 6e6]


def test_sourced_account_holds_id_or_name():
    e = extract(synthetic(capex_name="유형자산의 취득"), "thstrm")
    assert e["liabilities"] == Sourced(8e6, "ifrs-full_Liabilities", "id")
    assert e["capex"].account == "유형자산의 취득"


def test_capex_and_dividends_are_absolute():
    e = extract(synthetic(), "thstrm")
    assert e["capex"].value == 3e6 and e["dividends_paid"].value == 1.5e6
    assert e["ocf"].value == 10e6


def test_id_match_beats_name_match():
    fin = synthetic(defaults=False, extra=[
        fin_row("BS", NO_ID, "자본총계", "111", ord=1),
        fin_row("BS", "ifrs-full_Equity", "이름이 다른 자본", "222", ord=2)])
    e = extract(fin, "thstrm")["equity_total"]
    assert (e.value, e.how) == (222, "id")


def test_is_preferred_over_cis():
    fin = synthetic(defaults=False, extra=[
        fin_row("CIS", "dart_OperatingIncomeLoss", "영업이익", "1", ord=1),
        fin_row("IS", "dart_OperatingIncomeLoss", "영업이익", "2", ord=2)])
    assert extract(fin, "thstrm")["operating_income"].value == 2
    cis_only = synthetic(defaults=False, extra=[fin_row("CIS", "dart_OperatingIncomeLoss", "영업이익", "1")])
    assert extract(cis_only, "thstrm")["operating_income"].value == 1


def test_cf_and_bs_items_only_from_their_statement():
    fin = synthetic(defaults=False, extra=[
        fin_row("IS", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "5"),
        fin_row("CF", "ifrs-full_Liabilities", "부채총계", "6"),
        fin_row("CF", NO_ID, "유동자산", "7")])
    e = extract(fin, "thstrm")
    assert e["ocf"].value is None and e["liabilities"].value is None and e["current_assets"].value is None


def test_name_normalization():
    fin = synthetic(defaults=False, extra=[
        fin_row("IS", NO_ID, "당기 순이익(손실)", "10"),
        fin_row("CF", NO_ID, "이자의 지급", "-4"),
        fin_row("IS", NO_ID, "영업 이익(손실)", "9")])
    e = extract(fin, "thstrm")
    assert e["profit_loss"].value == 10 and e["profit_loss"].how == "name"
    assert e["interest_paid"].value == -4 and e["operating_income"].value == 9
    mid = synthetic(defaults=False, extra=[fin_row("IS", NO_ID, "지배기업·소유주지분", "3")])
    assert extract(mid, "thstrm")["net_income_parent"].value == 3


def test_multiple_id_matches_take_first_in_ord_order():
    fin = synthetic(defaults=False, extra=[
        fin_row("IS", "ifrs-full_ProfitLoss", "나중", "2", ord=5),
        fin_row("IS", "ifrs-full_ProfitLoss", "먼저", "1", ord=2)])
    assert extract(fin, "thstrm")["profit_loss"].value == 1


def test_blank_amount_for_period_is_none():
    fin = synthetic(defaults=False, extra=[fin_row("BS", "ifrs-full_Equity", "자본총계", "5", "")])
    assert extract(fin, "frmtrm")["equity_total"].value is None


def test_basic_and_diluted_eps_by_id_and_by_name():
    by_id = synthetic(defaults=False, extra=[
        fin_row("IS", "ifrs-full_BasicAndDilutedEarningsLossPerShare", "기본 및 희석주당이익(손실)", "5,000")])
    assert extract(by_id, "thstrm")["eps"] == Sourced(5000, "ifrs-full_BasicAndDilutedEarningsLossPerShare", "id")
    for name in ("기본및희석주당이익", "기본 및 희석주당이익(손실)", "기본및희석주당순이익", "기본 및 희석 주당순이익(손실)"):
        by_name = synthetic(defaults=False, extra=[fin_row("IS", NO_ID, name, "4,000")])
        assert extract(by_name, "thstrm")["eps"] == Sourced(4000, name, "name"), name


def test_diluted_only_eps_is_not_taken_as_basic():
    fin = synthetic(defaults=False, extra=[
        fin_row("IS", "ifrs-full_DilutedEarningsLossPerShare", "희석주당이익(손실)", "4,900")])
    assert extract(fin, "thstrm")["eps"].value is None


SCE_BEGIN = "dart_EquityAtBeginningOfPeriod"
PARENT_DETAIL = "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]"


def _sce(detail: str, amount, ord: int = 1) -> dict:
    return fin_row("SCE", SCE_BEGIN, "기초자본", amount, "100", "90", ord=ord, account_detail=detail)


def test_sce_beginning_equity_picks_parent_and_total_rows():
    fin = synthetic(extra=[_sce(PARENT_DETAIL + " ", "1,000", 1),
                           _sce("자본 [구성요소]", "1,100", 2),
                           _sce(PARENT_DETAIL + "|이익잉여금 [구성요소]", "300", 3),
                           _sce("연결재무제표 [member]", "9,999", 4)])
    e = extract(fin, "thstrm")
    assert e["equity_begin_parent"] == Sourced(1000.0, SCE_BEGIN, "id")
    assert e["equity_begin_total"] == Sourced(1100.0, SCE_BEGIN, "id")
    assert extract(fin, "frmtrm")["equity_begin_parent"].value == 100.0


def test_sce_component_row_alone_is_not_picked_and_no_name_fallback():
    fin = synthetic(extra=[_sce(PARENT_DETAIL + "|이익잉여금 [구성요소]", "300"),
                           fin_row("SCE", NO_ID, "기초자본", "5", account_detail=PARENT_DETAIL)])
    e = extract(fin, "thstrm")
    assert e["equity_begin_parent"] == Sourced(None, "", "id")
    assert e["equity_begin_total"].value is None


def test_sce_two_matching_rows_with_different_amounts_is_not_found():
    differ = synthetic(extra=[_sce(PARENT_DETAIL, "1,000", 1), _sce(PARENT_DETAIL, "1,200", 2)])
    assert extract(differ, "thstrm")["equity_begin_parent"] == Sourced(None, "", "id")
    same = synthetic(extra=[_sce(PARENT_DETAIL, "1,000", 1), _sce(PARENT_DETAIL, "1,000", 2)])
    assert extract(same, "thstrm")["equity_begin_parent"].value == 1000.0


def test_sce_blank_amount_is_not_found():
    fin = synthetic(extra=[_sce(PARENT_DETAIL, "")])
    assert extract(fin, "thstrm")["equity_begin_parent"].value is None


# ---- 2026-11-15 실제 자료 51곳 기능 시험에서 찾은 이름들 ----

def test_eps_names_with_slash_or_son_ik():
    # LG: 우선주 줄과 함께 "보통주 기본/희석주당순이익" (표준계정코드 없음)
    lg = synthetic(defaults=False, extra=[fin_row("IS", NO_ID, "구형우선주 기본/희석주당순이익", "4,830"),
                                          fin_row("IS", NO_ID, "보통주 기본/희석주당순이익", "4,780")])
    assert extract(lg, "thstrm")["eps"] == Sourced(4780, "보통주 기본/희석주당순이익", "name")
    # KT&G 2023 보고서: "기본및희석주당손익"
    ktng = synthetic(defaults=False, extra=[fin_row("CIS", NO_ID, "기본및희석주당손익", "7,843")])
    assert extract(ktng, "thstrm")["eps"] == Sourced(7843, "기본및희석주당손익", "name")


def test_son_ik_reads_as_profit_in_other_names():
    fin = synthetic(defaults=False, extra=[fin_row("IS", NO_ID, "영업손익", "9"), fin_row("IS", NO_ID, "당기순손익", "7")])
    e = extract(fin, "thstrm")
    assert e["operating_income"].value == 9 and e["profit_loss"].value == 7


def test_eps_from_continuing_plus_discontinued_when_no_total_row():
    # 카카오 2025 보고서: 전체 EPS 줄 없이 계속영업·중단영업만 있어요.
    # 2023년 −2,254 + −61 = −2,315 는 2023 보고서에 적힌 전체 EPS와 같아요.
    fin = synthetic(defaults=False, extra=[
        fin_row("CIS", CONT, "계속영업 기본주당순이익", "1,138", "242", "-2,254"),
        fin_row("CIS", DISC, "중단영업 기본주당순이익", "-20", "-116", "-61"),
        fin_row("CIS", "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations", "계속영업희석주당이익(손실)",
                "1,134", "208", "-2,254")])
    got = [extract(fin, p)["eps"] for p in PERIODS]
    assert [g.value for g in got] == [1118, 126, -2315]
    assert {g.how for g in got} == {"derived"}
    # NAVER 2023 보고서: 그해 중단영업 칸이 비어 있으면 계속영업 값 그대로예요.
    naver = synthetic(defaults=False, extra=[
        fin_row("CIS", CONT, "계속영업기본주당순이익", "6,661", "5,007", "9,977"),
        fin_row("CIS", DISC, "중단영업기본주당순이익", "", "", "100,877")])
    assert [extract(naver, p)["eps"].value for p in PERIODS] == [6661, 5007, 110854]


def test_total_eps_row_beats_continuing_plus_discontinued():
    fin = synthetic(defaults=False, extra=[fin_row("CIS", "ifrs-full_BasicEarningsLossPerShare", "기본주당손익", "10,220"),
                                           fin_row("CIS", CONT, "계속영업 기본주당이익", "10,228"),
                                           fin_row("CIS", DISC, "중단영업 기본주당손실", "-8")])
    assert extract(fin, "thstrm")["eps"] == Sourced(10220, "ifrs-full_BasicEarningsLossPerShare", "id")


def test_discontinued_eps_alone_is_not_eps():
    fin = synthetic(defaults=False, extra=[fin_row("CIS", DISC, "중단영업 기본주당손실", "-8")])
    assert extract(fin, "thstrm")["eps"].value is None


def test_combined_ppe_and_investment_property_capex_name():
    # KT·대한항공: "유형자산및투자부동산의 취득" (표준계정코드 없음)
    for name in ("유형자산및투자부동산의 취득", "유형자산 및 투자부동산의 취득"):
        fin = synthetic(defaults=False, extra=[fin_row("CF", NO_ID, name, "-3,596")])
        assert extract(fin, "thstrm")["capex"] == Sourced(3596, name, "name"), name


def test_minority_interest_net_income_field():
    nci = "ifrs-full_ProfitLossAttributableToNonControllingInterests"
    fin = synthetic(defaults=False, extra=[fin_row("IS", nci, "비지배지분", "7")])
    assert extract(fin, "thstrm")["net_income_nci"] == Sourced(7, nci, "id")
