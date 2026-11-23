"""점수 자료 받기: DART 정기보고서 항목을 읽고 종목마다 모아요 (점수 순위 설계 6장)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import FakeDart, corp_of
from test_extras import fin_q_eps
from vsf.data.dart import DartError, DartQuotaExceeded
from vsf.data.score_facts import (ScoreFacts, fetch_score_facts, gather_score_facts, interim_payouts,
                                  listed_subsidiaries, normalize_name, parse_stock_total,
                                  parse_treasury_changes, score_facts_from_dict, score_facts_to_dict)

FIX = Path(__file__).parent / "fixtures" / "dart" / "score"


def rows(name: str) -> list[dict]:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["list"]


# ---- 표 읽기 (2026-11-23에 받은 실제 응답) ----

def test_treasury_uses_common_total_row_only():
    # 기아는 직접취득 '소계'와 세부 줄에도 같은 수량이 있어요. 총계만 써야 두 배로 세지 않아요.
    assert parse_treasury_changes(rows("000270_tesstkAcqsDspsSttus_2025_11011")) == (7_259_634, 7_259_634)
    assert parse_treasury_changes(rows("316140_tesstkAcqsDspsSttus_2025_11011")) == (8_515_181, 8_515_181)


def test_other_acquisition_is_not_a_buyback():
    def row(m1: str, acq: str, inc: str = "-") -> dict:
        return {"stock_knd": "보통주", "acqs_mth1": m1, "acqs_mth2": m1, "acqs_mth3": m1,
                "change_qy_acqs": acq, "change_qy_incnr": inc}
    assert parse_treasury_changes([row("기타취득", "1,200"), row("총계", "1,200")]) == (0, 0)


def test_no_treasury_activity_reads_zero():
    # 롯데정밀화학 2025: 표가 '-' 한 줄뿐이에요
    blank = [{"stock_knd": "-", "acqs_mth1": "-", "acqs_mth2": "-", "acqs_mth3": "-",
              "change_qy_acqs": "-", "change_qy_incnr": "-"}]
    assert parse_treasury_changes(blank) == (0, 0)
    assert parse_treasury_changes([]) == (None, None)


def test_stock_total_reads_common_row():
    assert parse_stock_total(rows("000270_stockTotqySttus_2025_11011")) == (390_412_998, 1_810_273)
    voting = [{"se": "의결권 있는 보통주", "istc_totqy": "734,076,320", "tesstk_co": "53,945"},
              {"se": "합계", "istc_totqy": "734,076,320", "tesstk_co": "53,945"}]
    assert parse_stock_total(voting) == (734_076_320, 53_945)
    assert parse_stock_total([{"se": "보통주", "istc_totqy": "100", "tesstk_co": "-"}]) == (100, 0)
    assert parse_stock_total([]) == (None, None)


def test_interim_payouts():
    assert interim_payouts(rows("105560_alotMatter_2026_11013"), None) == 4
    assert interim_payouts(rows("004000_alotMatter_2026_11013"), rows("004000_alotMatter_2026_11012")) == 1
    half_only = [dict(r, thstrm="500") if r["se"].startswith("주당 현금배당금") and r["stock_knd"] == "보통주" else r
                 for r in rows("004000_alotMatter_2026_11012")]
    assert interim_payouts(rows("004000_alotMatter_2026_11013"), half_only) == 2
    assert interim_payouts(None, None) is None


@pytest.mark.parametrize("raw,want", [
    ("㈜우리은행 ", "우리은행"), ("우리금융캐피탈㈜ ", "우리금융캐피탈"), ("㈜우리투자증권 \n주4)", "우리투자증권"),
    ("동양생명보험㈜ \n주5)", "동양생명보험"), ("(주)LG에너지솔루션", "LG에너지솔루션"),
    ("주식회사 카카오뱅크", "카카오뱅크"), ("LOTTE Fine\n Chemical Trading", "LOTTEFineChemicalTrading")])
def test_normalize_name(raw, want):
    assert normalize_name(raw) == want


def test_listed_subsidiaries_match_by_normalized_name():
    r = rows("316140_otrCprInvstmntSttus_2025_11011")
    assert listed_subsidiaries(r, {"우리은행"}, 30.0) == (("우리은행", 100.0),)
    assert listed_subsidiaries(r, {"동양생명보험"}, 80.0) == ()               # 75.34% < 80
    assert listed_subsidiaries(r, set(), 30.0) == ()
    assert listed_subsidiaries(rows("105560_otrCprInvstmntSttus_2025_11011"), {"합계"}, 30.0) == ()


# ---- 종목 하나 모으기 ----

def _entry() -> dict:
    e = FakeDart.entry()
    e["periodic"] = {}
    return e


FULL = {
    ("alotMatter", 2026, "11013"): rows("105560_alotMatter_2026_11013"),
    ("alotMatter", 2026, "11012"): rows("004000_alotMatter_2026_11012"),
    ("stockTotqySttus", 2025, "11011"): rows("000270_stockTotqySttus_2025_11011"),
    ("tesstkAcqsDspsSttus", 2025, "11011"): rows("000270_tesstkAcqsDspsSttus_2025_11011"),
    ("tesstkAcqsDspsSttus", 2024, "11011"): rows("316140_tesstkAcqsDspsSttus_2025_11011"),
    ("tesstkAcqsDspsSttus", 2023, "11011"): rows("000270_tesstkAcqsDspsSttus_2025_11011"),
    ("otrCprInvstmntSttus", 2025, "11011"): rows("316140_otrCprInvstmntSttus_2025_11011"),
}


def test_fetch_score_facts_reads_everything():
    e = _entry()
    e["periodic"] = FULL
    e["quarterly_fin"] = {(2026, "11014"): fin_q_eps("185", "407")}
    dart = FakeDart({"000270": e})
    f = fetch_score_facts(dart, corp_of("000270"), 2025, 674.0, {"우리은행"}, 30.0)
    assert f.ttm_eps == 674 + 185 - 407 and f.ttm_label == "2025년 4분기~2026년 3분기" and not f.ttm_is_annual
    assert f.payout_per_year == 4
    assert (f.issued, f.treasury) == (390_412_998, 1_810_273)
    assert f.buyback_years == (True, True, True) and f.cancelled == 7_259_634
    assert f.subsidiaries == (("우리은행", 100.0),)
    assert set(f.sources) >= {"ttm", "freq", "treasury", "buyback", "cancel", "subsidiary"}


def test_fetch_without_quarter_report_says_annual_is_latest_and_missing_items_are_none():
    dart = FakeDart({"000270": _entry()})
    f = fetch_score_facts(dart, corp_of("000270"), 2025, 674.0, set(), 30.0)
    assert f.ttm_is_annual and f.ttm_eps is None
    assert f.payout_per_year is None and f.issued is None and f.cancelled is None
    assert f.buyback_years == (None, None, None) and f.subsidiaries is None


def test_payouts_fall_back_to_latest_annual_year_when_half_report_is_not_out():
    e = _entry()
    e["periodic"] = {("alotMatter", 2025, "11013"): rows("105560_alotMatter_2026_11013"),
                     ("alotMatter", 2025, "11012"): rows("004000_alotMatter_2026_11012")}
    f = fetch_score_facts(FakeDart({"000270": e}), corp_of("000270"), 2025, 674.0, set(), 30.0)
    assert f.payout_per_year == 4


def _run(*codes):
    results = {c: SimpleNamespace(company=SimpleNamespace(corp_code=corp_of(c)),
                                  assembled=SimpleNamespace(latest_year=2025, inputs=SimpleNamespace(
                                      years=(SimpleNamespace(eps=100.0),)))) for c in codes}
    return SimpleNamespace(results=results)


def test_gather_stops_on_quota_and_marks_partial():
    dart = FakeDart({"000270": _entry(), "030000": _entry()}, quota_after=1)
    facts, partial = gather_score_facts(_run("000270", "030000"), dart, set(), 30.0, ["000270", "030000"])
    assert list(facts) == ["000270"] and partial is True


def test_gather_isolates_other_errors():
    dart = FakeDart({"000270": _entry(), "030000": _entry()}, raise_for={"000270": DartError("100", "x")})
    facts, partial = gather_score_facts(_run("000270", "030000"), dart, set(), 30.0, ["000270", "030000"])
    assert partial is False and facts["000270"].ttm_eps is None and "error" in facts["000270"].sources
    assert facts["030000"].ttm_is_annual


def test_gather_quota_before_start_is_partial_and_empty():
    dart = FakeDart({"000270": _entry()}, raise_for={"000270": DartQuotaExceeded()})
    assert gather_score_facts(_run("000270"), dart, set(), 30.0, ["000270"]) == ({}, True)


def test_facts_round_trip_dict():
    f = ScoreFacts(ttm_eps=1.0, ttm_label="x", payout_per_year=2, issued=10.0, treasury=0.0,
                   buyback_years=(True, False, None), cancelled=1.0, subsidiaries=(("a", 50.0),),
                   sources={"ttm": "s"})
    d = score_facts_to_dict(f)
    json.dumps(d)
    assert score_facts_from_dict(d) == f and score_facts_from_dict(None) is None


def test_quarter_report_without_income_lines_is_not_treated_as_missing():
    """분기 보고서는 있는데 손익 줄을 못 읽으면 '연간이 가장 최신'(만점)이 아니라 자료 없음이어야 해요."""
    from helpers import fin_row
    from vsf.data.dart import FinRows
    row = fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", "기본주당이익")
    row.update({"thstrm_add_amount": "", "frmtrm_add_amount": ""})
    e = _entry()
    e["quarterly_fin"] = {(2026, "11014"): FinRows([row], "CFS", "20261114000001")}
    f = fetch_score_facts(FakeDart({"000270": e}), corp_of("000270"), 2025, 674.0, set(), 30.0)
    assert f.ttm_is_annual is False and f.ttm_eps is None
