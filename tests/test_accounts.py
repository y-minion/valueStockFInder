import math

import pytest

from helpers import fin_row, load_fin, synthetic
from vsf.data.accounts import PERIODS, Sourced, extract, parse_amount

FIELDS = {"net_income_parent", "profit_loss", "eps", "equity_parent", "equity_total", "liabilities",
          "current_assets", "operating_income", "interest_expense", "interest_paid", "ocf", "capex",
          "dividends_paid"}
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
