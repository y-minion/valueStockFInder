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


def test_industry_override_is_judged_with_effective_criteria():
    s = settings_with({"30": {"roe_min": 9.0}})
    r = _result("000001", "가", _roe(_kia_inputs(60000.0), 9.5), s)
    assert r.criteria.roe_min == 9.0
    row = _row(criteria_check({"000001": r}, s, False), "일반 회사", "roe_min")
    assert row["pass_now"] == 1 and row["threshold"] == 8.0
    # 설정값(8+1=9)으로 보면 통과지만, 이 종목의 실제 기준(9+1=10)으로는 탈락이어야 해요
    assert row["stricter"]["threshold"] == 9.0 and row["stricter"]["pass"] == 0
    assert row["looser"]["pass"] == 1


def test_upper_bound_keys_move_the_other_way():
    s = settings_with()
    res = {"000001": _result("000001", "가", replace(_kia_inputs(60000.0), years=tuple(
        replace(y, debt_ratio=210.0) for y in _kia_inputs(60000.0).years)), s)}
    row = _row(criteria_check(res, s, False), "일반 회사", "debt_ratio_max")
    assert row["threshold"] == 200.0 and row["pass_now"] == 0
    assert row["stricter"]["threshold"] == 175.0 and row["stricter"]["pass"] == 0
    assert row["looser"]["threshold"] == 225.0 and row["looser"]["pass"] == 1
    b88 = res["000001"].cells["B88"]
    pct = round(b88 * 100)
    s2 = Settings(**{**s.__dict__, "criteria": Criteria(payout_max=(pct + 2) / 100)})
    res2 = {"000001": _result("000001", "가", _kia_inputs(60000.0), s2)}
    p = _row(criteria_check(res2, s2, False), "일반 회사", "payout_max")
    assert p["pass_now"] == 1
    assert p["stricter"]["threshold"] == pct + 2 - 5 and p["stricter"]["pass"] == 0
    assert p["looser"]["threshold"] == pct + 2 + 5 and p["looser"]["pass"] == 1


def test_capital_variants_use_step_and_flip_pass():
    s = settings_with()

    def row(value):
        res = {"105560": _result("105560", "은행", _kia_inputs(60000.0), s, "은행",
                                 capital=CapitalRatio(value, "2026-09", "x"))}
        return _row(criteria_check(res, s, False), "금융회사", "bank_cet1_min")
    r = row(13.2)
    assert r["threshold"] == 9.0 and r["stricter"]["threshold"] == 10.0 and r["looser"]["threshold"] == 8.0
    r = row(9.5)
    assert r["pass_now"] == 1 and r["stricter"]["pass"] == 0 and r["looser"]["pass"] == 1


def test_industry_list_dedupes_and_sorts():
    from vsf.industry import IndustryInfo
    s = settings_with()

    def info(code, name, size):
        return IndustryInfo(code, name, size, 9.0, None, None, None)
    res = {}
    for code, ind in (("000001", info("A", "가업", 5)), ("000002", info("A", "가업", 5)),
                      ("000003", info("B", "나업", 9)), ("000004", info("C", "다업", 5))):
        res[code] = replace(_result(code, code, _kia_inputs(60000.0), s), industry=ind)
    out = criteria_check(res, s, False)["industry"]
    assert [i["group_name"] for i in out] == ["나업", "가업", "다업"]
    assert out[0] == {"group_name": "나업", "size": 9, "roe_median": 9.0}
