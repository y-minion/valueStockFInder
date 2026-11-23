from dataclasses import replace

import pytest
from helpers import collected_with_kia, settings_with, synthetic_company
from vsf.config import ReportSettings
from vsf.data.assemble import assemble
from vsf.evaluate import FAIR_VALUE_FLAG, evaluate, evaluate_one, evaluation_flags, state_of
from vsf.financial import CapitalRatio, FinancialGate


def test_evaluate_applies_override_and_extra_gate():
    s = settings_with(overrides={"30": {"roe_min": 20.0}}, use_in_verdict=True)      # 기아 induty "30121", 종목 1개
    r = evaluate(collected_with_kia(), s).results["000270"]
    assert r.criteria.roe_min == 20.0 and r.cells["D78"] == "탈락"
    assert r.industry.group_code == "ALL" and r.extra_gate1 == "탈락"     # 1개뿐 → 전체 시장, 순위 100% > 50%


def test_evaluate_defaults_buy_and_fingerprint():
    run = evaluate(collected_with_kia(), settings_with())
    r = run.results["000270"]
    assert r.state == "buy" and r.near and r.extra_gate1 is None
    assert round(r.summary.buy_line, 1) == 69713.6
    assert run.settings_fp["criteria"]["safety_margin"] == 0.25


def test_evaluate_one_without_industry():
    company, assembled = collected_with_kia().records["000270"]
    assert evaluate_one(company, assembled, settings_with(), None).extra_gate1 is None
    r = evaluate_one(company, assembled, settings_with(use_in_verdict=True), None)
    assert r.extra_gate1 == "입력 필요"


# ---- 적정가 B·C가 빠지면 '숫자 확인 필요' (연말 PER이 비면 A만 남아 매수선이 높아져요) ----

def _kia(price: float, **year_fields):
    """기아 정답 입력을 price로, 다섯 해 모두 year_fields 값으로 바꾼 수집 결과."""
    collected = collected_with_kia(price)
    company, assembled = collected.records["000270"]
    inputs = assembled.inputs
    inputs = replace(inputs, years=tuple(replace(y, **year_fields) for y in inputs.years))
    if "dps" in year_fields:
        inputs = replace(inputs, prior_dps=(None,) * 5)
    collected.records["000270"] = (company, replace(assembled, inputs=inputs, flags=("기존 표시",)))
    return collected


BC_FLAG = "적정가 세 방법 중 B·C를 계산하지 못했어요(연말 PER·배당 자료 부족). 숫자를 확인해 주세요."


def test_blank_year_end_per_flags_a_buy():
    # 97,000원은 A·B·C가 다 있으면 'out'이에요. PER이 비면 A만 남아 'buy'가 되니 표시가 꼭 붙어야 해요.
    r = evaluate(_kia(97000.0, per=None), settings_with()).results["000270"]
    assert r.cells["B103"] is None and r.cells["B104"] is None and r.cells["B106"] == "A 이론"
    assert r.state == "buy"
    assert r.flags == ("기존 표시", BC_FLAG)
    assert r.assembled.flags == ("기존 표시",)                     # 조립 단계 표시는 그대로


def test_evaluate_one_applies_the_same_guard():
    company, assembled = _kia(150000.0, per=None).records["000270"]
    r = evaluate_one(company, assembled, settings_with(), None)
    assert r.state == "watch" and r.flags[-1] == BC_FLAG


def test_missing_c_only_names_c():
    r = evaluate(_kia(60000.0, dps=None), settings_with()).results["000270"]
    assert r.cells["B103"] is not None and r.cells["B104"] is None and r.state == "buy"
    assert r.flags[-1] == "적정가 세 방법 중 C를 계산하지 못했어요(연말 PER·배당 자료 부족). 숫자를 확인해 주세요."


def test_clean_case_has_no_evaluation_flag():
    r = evaluate(collected_with_kia(), settings_with()).results["000270"]
    assert r.state == "buy" and r.flags == () and r.eval_flags == ()


def test_out_stock_with_blank_b_c_is_not_flagged():
    r = evaluate(_kia(1e7, per=None), settings_with()).results["000270"]
    assert r.state == "out" and r.cells["B103"] is None and r.flags == ("기존 표시",)


@pytest.mark.parametrize("cells,state,want", [
    ({"B96": 100.0, "B103": None, "B104": 5.0}, "buy", "B"),
    ({"B96": 100.0, "B103": 5.0, "B104": None}, "watch", "C"),
    ({"B96": 100.0, "B103": None, "B104": None}, "watch", "B·C"),
    ({"B96": 100.0, "B103": 5.0, "B104": 6.0}, "buy", None),
    ({"B96": 100.0, "B103": None, "B104": None}, "out", None),
    ({"B96": 0.0, "B103": None, "B104": None}, "buy", None),       # 정상 EPS ≤ 0은 '계산 불가'라 따로 탈락해요
    ({"B96": None, "B103": None, "B104": None}, "buy", None),
])
def test_evaluation_flags_rule(cells, state, want):
    got = evaluation_flags(cells, state)
    assert got == (() if want is None else (FAIR_VALUE_FLAG.format(missing=want),))


def test_evaluate_one_uses_sector_verdict_for_financials():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    bank = replace(co, financial_kind="은행")
    a = assemble(bank, L, fin_a, fin_b, divs, ye, price, d)
    r = evaluate_one(bank, a, settings_with(), None)
    assert r.financial == FinancialGate("은행", None, 9.0) and r.cells["D79"] == "해당 없음"
    assert state_of(a.inputs, r.criteria, None, ReportSettings(), financial=r.financial) == r.state


def test_state_of_follows_financial_gate():
    from helpers import _kia_inputs
    from vsf.model import Criteria
    i = _kia_inputs(60000.0)
    loss = replace(i, years=tuple(replace(y, net_income=-100.0) if y.year == 2023 else y for y in i.years))
    bank = FinancialGate("은행", None, 9.0)
    assert state_of(loss, Criteria(), None, ReportSettings(), financial=None) == "buy"
    assert state_of(loss, Criteria(), None, ReportSettings(), financial=bank) == "out"


def test_evaluate_uses_capital():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    bank = replace(co, financial_kind="은행")
    cap = CapitalRatio(13.2, "2026-06", "금감원 금융통계정보시스템 SA014·보통주자본비율")
    a = assemble(bank, L, fin_a, fin_b, divs, ye, price, d, cap)
    assert a.capital == cap
    r = evaluate_one(bank, a, settings_with(), None)
    assert r.financial == FinancialGate("은행", cap, 9.0)
    assert r.cells["F_CAP_D"] == "통과" and r.cells["D82"] != "확인 필요"


# ---- 우선주: 같은 회사를 두 번 세지 않아요 (2026-11-24) ----

def _with_preferred_run():
    from dataclasses import replace as _r

    from fakes import D as _D
    from fakes import FakeDart, FakeKrx, mem_store, noop
    from helpers import _SYN_DPS, div_rows, settings_with
    from vsf.collect import collect
    from vsf.config import IndustrySettings
    plus = lambda v: v if v.strip() in ("-", "") else f"{int(v.replace(',', '')) + 50:,}"   # noqa: E731
    divs = {y: div_rows(*v, year=y, pref=tuple(plus(x) for x in v)) for y, v in _SYN_DPS.items()}
    dart = FakeDart({"000270": FakeDart.entry(dividends=divs), "030000": FakeDart.entry()})
    c = collect(dart, FakeKrx.with_preferred(), mem_store(), _D, progress=noop)
    settings = _r(settings_with(), industry=IndustrySettings(min_group_size=1))
    return evaluate(c, settings), settings


def test_industry_counts_common_only():
    run, _ = _with_preferred_run()
    common, pref = run.results["000270"], run.results["000275"]
    assert common.industry is not None and common.industry.size == 2      # 기아·제일기획, 기아우는 빼요
    assert pref.industry == common.industry                                # 우선주는 보통주 업종 정보를 그대로


def test_criteria_check_skips_preferred():
    from vsf.criteria_check import criteria_check
    run, settings = _with_preferred_run()
    got = criteria_check(run.results, settings, partial=False)
    assert got["groups"][0]["n"] == 2
