from vsf.changes import Change, criteria_changes, detect_changes
from vsf.config import ReportSettings
from vsf.model import Criteria
from helpers import fp, run, run_only, snap, snap_only


def test_price_drop_is_price_cause():
    ch = detect_changes(snap(kia_price=97000), run(kia_price=60000), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("주가",))]
def test_criteria_only_change():          # 안전마진 0.10 → 매수선 83,656원 > 72,000원
    ch = detect_changes(snap(kia_price=72000), run(kia_price=72000, criteria=Criteria(safety_margin=0.10)), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("기준 변경",))]
def test_financial_update_cause():        # 최근 해 EPS 40,000 → 보수적 적정가(C) 약 110,580원 → 매수선 약 82,940원
    ch = detect_changes(snap(kia_price=72000), run(kia_price=72000, latest_eps=40000), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("재무 갱신",))]
def test_combined_causes_in_order():      # 97,000원·기본 기준(out) → 기준만 바꾸면 watch → 주가까지 바꾸면 buy
    ch = detect_changes(snap(kia_price=97000), run(kia_price=72000, criteria=Criteria(safety_margin=0.10)), ReportSettings())
    assert ch[0].kind == "new_buy" and ch[0].causes == ("기준 변경","주가")
def test_new_and_missing_stocks():        # 지난번엔 030000(watch)만, 이번엔 000270(buy)만
    ch = detect_changes(snap_only("030000", state="watch"), run_only("000270", kia_price=60000), ReportSettings())
    assert Change("030000","제일기획","left",("이번에 분석 안 됨",)) in ch
    assert Change("000270","기아","new_buy",("새로 분석됨",)) in ch
def test_first_run_no_changes(): assert detect_changes(None, run(kia_price=60000), ReportSettings()) == []
def test_criteria_changes_labels():
    assert criteria_changes(fp(0.10), fp(0.09)) == [{"key":"required_return","label":"요구수익률","old":0.10,"new":0.09}]


def test_no_change_when_state_same():
    assert detect_changes(snap(kia_price=60000), run(kia_price=60000), ReportSettings()) == []


def test_missing_stock_that_was_out_is_not_reported():
    assert detect_changes(snap_only("030000", state="out"), run_only("000270", kia_price=97000), ReportSettings()) == []


def test_override_change_uses_overrides_label():
    a, b = fp(0.10), fp(0.10)
    b["industry"]["overrides"] = {"30": {"roe_min": 20.0}}
    assert criteria_changes(a, b) == [{"key": "overrides", "label": "업종별 기준 덮어쓰기",
                                       "old": {}, "new": {"30": {"roe_min": 20.0}}}]
