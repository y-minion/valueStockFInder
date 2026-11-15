import json
from dataclasses import replace

from helpers import _kia_inputs
from vsf.config import FinancialSettings
from vsf.engine import compute
from vsf.financial import (CAPITAL_HELP, FIN_CELLS, CapitalRatio, FinancialGate, financial_gate,
                           gate_from_dict, gate_to_dict)
from vsf.model import Criteria

BANK = FinancialGate(kind="은행", capital=None, capital_min=9.0)


def _with_net_income(inputs, values):              # {year: value or None}
    years = tuple(replace(y, net_income=values.get(y.year, y.net_income)) for y in inputs.years)
    return replace(inputs, years=years)


def test_general_compute_is_unchanged():
    i = _kia_inputs(60000.0)
    assert not set(FIN_CELLS) & set(compute(i, Criteria()))


def test_sector_rows_replace_general_rows():
    v = compute(_kia_inputs(60000.0), Criteria(), financial=BANK)
    assert [v[a] for a in ("D79", "D80", "D81", "D89")] == ["해당 없음"] * 4
    assert v["F_LOSS_D"] == "통과" and v["F_CAP_D"] == "직접 확인" and v["F_CAP_SRC"] == CAPITAL_HELP
    assert v["D82"] == "확인 필요" and v["B7"] == "확인 필요"
    assert [v[a] for a in ("B79", "B80", "B81", "B89")] == [None] * 4
    assert [v[a] for a in ("C79", "C80", "C81", "C89")] == ["해당 없음"] * 4
    assert v["F_LOSS_B"] == 0.0 and v["F_LOSS_C"] == "5년 모두 흑자" and v["F_CAP_B"] is None
    assert v["F_CAP_C"] == "≥ 9%"


def test_capital_ratio_pass_and_fail():
    ok = replace(BANK, capital=CapitalRatio(13.2, "2026-09", "FISIS 국내은행 자본비율"))
    v = compute(_kia_inputs(60000.0), Criteria(), financial=ok)
    assert (v["F_CAP_C"], v["F_CAP_D"], v["D82"]) == ("≥ 9%", "통과", "통과") and v["F_CAP_B"] == 13.2
    assert v["F_CAP_SRC"] == "FISIS 국내은행 자본비율 (2026-09 기준)"
    low = replace(ok, capital=replace(ok.capital, value=8.5))
    assert compute(_kia_inputs(60000.0), Criteria(), financial=low)["D82"] == "탈락"


def test_loss_year_fails_and_blank_year_needs_input():
    loss = _with_net_income(_kia_inputs(60000.0), {2023: -100.0})
    lv = compute(loss, Criteria(), financial=BANK)
    assert lv["F_LOSS_D"] == "탈락" and lv["F_LOSS_B"] == 1.0
    mixed = _with_net_income(_kia_inputs(60000.0), {2021: None, 2023: -100.0})
    assert compute(mixed, Criteria(), financial=BANK)["F_LOSS_D"] == "탈락"
    blank = _with_net_income(_kia_inputs(60000.0), {y.year: None for y in loss.years})
    assert compute(blank, Criteria(), financial=BANK)["F_LOSS_B"] is None
    v = compute(_with_net_income(_kia_inputs(60000.0), {2021: None}), Criteria(), financial=BANK)
    assert v["F_LOSS_D"] == "입력 필요" and v["D82"] == "확인 필요"


def test_gate2_drops_fcf_and_glance_follows_new_gates():
    # capex far above OCF: the general FCF check fails, the sector gate ignores it
    # (the example sheet leaves capex and dividends_paid blank, so set both)
    i = _kia_inputs(60000.0)
    heavy = replace(i, years=tuple(replace(y, capex=(y.ocf or 0) * 10, dividends_paid=1000.0) for y in i.years))
    assert compute(heavy, Criteria())["D90"] == "탈락"
    v = compute(heavy, Criteria(), financial=BANK)
    assert v["D90"] == "통과" and "관문 ②에서 탈락" not in v["B15"]


def test_extra_gate1_still_counts():
    ok = replace(BANK, capital=CapitalRatio(13.2, "2026-09", "x"))
    assert compute(_kia_inputs(60000.0), Criteria(), "탈락", financial=ok)["D82"] == "탈락"


def test_card_capital_has_no_automatic_check():
    g = financial_gate("카드·캐피탈", None, FinancialSettings())
    v = compute(_kia_inputs(60000.0), Criteria(), financial=g)
    assert g.capital_min is None and (v["F_CAP_C"], v["F_CAP_D"]) == ("기준 없음", "직접 확인")


def test_financial_gate_thresholds_and_round_trip():
    fs = FinancialSettings()
    assert [financial_gate(k, None, fs).capital_min for k in ("금융지주", "은행", "보험", "증권")] == [9.0, 9.0, 130.0, 100.0]
    assert financial_gate(None, None, fs) is None
    g = FinancialGate("보험", CapitalRatio(180.5, "2026-06", "FISIS"), 130.0)
    assert gate_from_dict(json.loads(json.dumps(gate_to_dict(g)))) == g and gate_from_dict(None) is None


def test_gate4_hints_for_financials():
    v = compute(_kia_inputs(60000.0), Criteria(), financial=BANK)
    assert v["C131"] == "참고: 금융회사는 부채비율·이자보상배율 대신 자본비율을 봐요 (보통주자본비율 직접 확인)"
    assert v["C132"].startswith("참고: 배당성향 평균 ") and "잉여현금흐름÷배당 ?" not in v["C132"]
    assert v["C132"].endswith("(금융회사라 잉여현금흐름÷배당은 보지 않아요)")
    ok = replace(BANK, capital=CapitalRatio(13.2, "2026-09", "x"))
    v = compute(_kia_inputs(60000.0), Criteria(), financial=ok)
    assert v["C131"].endswith("(보통주자본비율 13.2%, 2026-09 기준)")
