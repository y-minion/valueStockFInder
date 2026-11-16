from dataclasses import replace

from helpers import _kia_inputs, settings_with
from vsf.config import Settings
from vsf.criteria_check import criteria_check
from vsf.data.assemble import Assembled, CompanyInfo
from vsf.evaluate import evaluate_one
from vsf.financial import CapitalRatio, financial_gate
from vsf.model import Criteria


def _roe(inputs, roe):
    return replace(inputs, years=tuple(replace(y, roe=roe) for y in inputs.years))


def _result(code, name, inputs, settings, financial_kind=None, quick_fail=False, capital=None):
    company = CompanyInfo("99" + code, code, name, "KOSPI", "30121", "12", financial_kind)
    r = evaluate_one(company, Assembled(inputs, (), (), {}, quick_fail, 2025), settings, None)
    if capital is not None:
        from vsf.engine import compute, summarize, watch_state
        gate = financial_gate(financial_kind, capital, settings.financial)
        cells = compute(inputs, r.criteria, None, financial=gate)
        r = replace(r, financial=gate, cells=cells, summary=summarize(cells),
                    state=watch_state(summarize(cells), settings.report))
    return r


def _row(check, group, key):
    g = next(g for g in check["groups"] if g["group"] == group)
    return next(r for r in g["rows"] if r["key"] == key)


def test_distribution_and_pass_counts():
    s = settings_with()
    res = {c: _result(c, c, _roe(_kia_inputs(60000.0), v), s) for c, v in (("000001", 6.0), ("000002", 8.5), ("000003", 12.0))}
    row = _row(criteria_check(res, s, False), "일반 회사", "roe_min")
    assert row["dist"]["median"] == 8.5 and row["dist"]["n"] == 3 and row["pass_now"] == 2
    assert row["stricter"]["threshold"] == 9.0 and row["stricter"]["pass"] == 1
    assert row["looser"]["threshold"] == 7.0 and row["looser"]["pass"] == 2
    assert _row(criteria_check(res, s, False), "일반 회사", "required_return")["dist"] is None


def test_watchlist_changes_on_one_step():
    s = settings_with()
    res = {"000001": _result("000001", "경계주", _roe(_kia_inputs(60000.0), 7.6), s)}
    assert res["000001"].state == "out"
    row = _row(criteria_check(res, s, False), "일반 회사", "roe_min")
    assert row["looser"]["watch_in"] == [["000001", "경계주"]] and row["looser"]["watch_out"] == []
    assert row["stricter"]["watch_in"] == []


def test_partial_quick_fail_and_invalid_variant():
    s = settings_with()
    s = Settings(**{**s.__dict__, "criteria": Criteria(payout_min=0.55, payout_max=0.60)})
    res = {"000001": _result("000001", "가", _kia_inputs(60000.0), s),
           "000002": _result("000002", "나", _kia_inputs(60000.0), s, quick_fail=True)}
    check = criteria_check(res, s, True)
    assert check["partial"] is True and check["groups"][0]["n"] == 1
    assert _row(check, "일반 회사", "payout_min")["stricter"] is None
    assert _row(check, "일반 회사", "payout_min")["looser"] is not None


def test_financial_group_rows():
    s = settings_with()
    res = {"105560": _result("105560", "은행", _kia_inputs(60000.0), s, "은행",
                             capital=CapitalRatio(13.2, "2026-09", "x")),
           "000001": _result("000001", "일반", _kia_inputs(60000.0), s)}
    check = criteria_check(res, s, False)
    assert [g["group"] for g in check["groups"]] == ["일반 회사", "금융회사"]
    cap = _row(check, "금융회사", "bank_cet1_min")
    assert cap["pass_now"] == 1 and cap["dist"]["median"] == 13.2
    keys = [r["key"] for r in next(g for g in check["groups"] if g["group"] == "금융회사")["rows"]]
    assert "debt_ratio_max" not in keys and keys[:2] == ["roe_min", "bank_cet1_min"]
    assert "securities_ncr_min" not in keys


def test_empty_group_omitted_and_industry():
    s = settings_with()
    check = criteria_check({}, s, False)
    assert check == {"partial": False, "groups": [], "industry": []}
