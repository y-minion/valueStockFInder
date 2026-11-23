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


def test_criteria_changes_skip_missing_financial_section():
    assert criteria_changes({"criteria": {"required_return": 0.1}},
                            {"criteria": {"required_return": 0.1}, "financial": {"include": True}}) == []
    a = {"criteria": {}, "financial": {"include": True}}
    b = {"criteria": {}, "financial": {"include": False}}
    assert criteria_changes(a, b) == [{"key": "include", "label": "금융회사 포함", "old": True, "new": False}]


def test_change_cause_uses_sector_verdict():
    from dataclasses import replace
    from helpers import _kia_inputs
    from vsf.engine import compute, is_near, summarize, watch_state
    from vsf.evaluate import StockResult, evaluation_flags, state_of
    from vsf.financial import FinancialGate
    from vsf.snapshot import SnapStock
    gate = FinancialGate("은행", None, 9.0)
    rep = ReportSettings()
    loss = _kia_inputs(60000.0)
    years = list(loss.years)
    years[0] = replace(years[0], net_income=-100.0)
    loss = replace(loss, years=tuple(years))
    assert state_of(loss, Criteria(), None, rep, gate) == "out"
    assert state_of(loss, Criteria(), None, rep) == "buy"
    prev0 = snap(kia_price=60000)
    prev = replace(prev0, stocks={"000270": SnapStock(name="기아", inputs=loss, criteria=Criteria(),
                                                      extra_gate1=None, state="out", near=False,
                                                      financial=gate)})
    r = run(kia_price=60000)
    cur = r.results["000270"]
    cells = compute(cur.assembled.inputs, Criteria(), None, financial=gate)
    summary = summarize(cells)
    state = watch_state(summary, rep)
    res = replace(cur, cells=cells, summary=summary, state=state, financial=gate,
                  near=state != "out" and is_near(summary, rep))
    assert state == "buy"
    ch = detect_changes(prev, replace(r, results={"000270": res}), rep)
    assert ch == [Change("000270", "기아", "new_buy", ("재무 갱신",))]


def _financial_run(r, gate, rep):
    from dataclasses import replace

    from vsf.engine import compute, is_near, summarize, watch_state
    cur = r.results["000270"]
    cells = compute(cur.assembled.inputs, Criteria(), None, financial=gate)
    summary = summarize(cells)
    state = watch_state(summary, rep)
    res = replace(cur, cells=cells, summary=summary, state=state, financial=gate,
                  near=state != "out" and is_near(summary, rep))
    return replace(r, results={"000270": res}), state


def _prev_with(gate, state):
    from dataclasses import replace

    from helpers import _kia_inputs
    from vsf.snapshot import SnapStock
    prev0 = snap(kia_price=60000)
    return replace(prev0, stocks={"000270": SnapStock(
        name="기아", inputs=_kia_inputs(60000.0), criteria=Criteria(), extra_gate1=None,
        state=state, near=False, financial=gate)})


def test_capital_min_change_is_criteria_cause():
    from vsf.financial import CapitalRatio, FinancialGate
    rep = ReportSettings()
    cap = CapitalRatio(140.0, "2026-06", "x")
    old, new = FinancialGate("보험", cap, 130.0), FinancialGate("보험", cap, 150.0)
    _, s_old = _financial_run(run(kia_price=60000), old, rep)
    cur, s_new = _financial_run(run(kia_price=60000), new, rep)
    assert s_old == "buy" and s_new == "out"
    ch = detect_changes(_prev_with(old, s_old), cur, rep)
    assert ch == [Change("000270", "기아", "left", ("기준 변경",))]


def test_previous_week_without_financial_uses_current_gate():
    from vsf.financial import CapitalRatio, FinancialGate
    rep = ReportSettings()
    gate = FinancialGate("보험", CapitalRatio(100.0, "2026-06", "x"), 130.0)
    cur, state = _financial_run(run(kia_price=60000), gate, rep)
    assert state == "out"
    prev = snap(kia_price=60000)
    assert prev.stocks["000270"].financial is None and prev.stocks["000270"].state == "buy"
    assert detect_changes(prev, cur, rep) == [Change("000270", "기아", "left", ("기준 변경",))]


def test_score_setting_changes_are_listed_per_item():
    from vsf.changes import criteria_changes
    from vsf.config import ItemRule, ScoreSettings, Settings, settings_fingerprint
    from helpers import settings_with
    base = settings_with()
    cur = Settings(**{**base.__dict__, "score": ScoreSettings(
        top_n=30, items={**ScoreSettings().items, "per": ItemRule(20, ((5, 20),))})})
    got = criteria_changes(settings_fingerprint(base), settings_fingerprint(cur))
    labels = {c["label"]: (c["old"], c["new"]) for c in got}
    assert labels["점수 순위 첫 화면 개수"] == (50, 30)
    assert labels["점수 PER"] == ("10점: 5배 미만 10 · 8배 미만 7 · 10배 미만 5 · 15배 미만 2", "20점: 5배 미만 20")
    assert criteria_changes(settings_fingerprint(base), settings_fingerprint(base)) == []
