import pytest
from helpers import load_oracle

from vsf.config import IndustrySettings
from vsf.industry import (IndustryInfo, build_industry, division, effective_criteria,
                          extra_gate1, group_names, industry_inputs, section)
from vsf.model import Criteria


def info(**kw):
    base = dict(group_code="30", group_name="x", size=9, roe_median=None, roe_rank_pct=None,
                debt_median=None, debt_rank_pct=None)
    return IndustryInfo(**(base | kw))


def test_names_anchor():
    n = group_names()
    assert n["30"] == "자동차 및 트레일러 제조업" and n["64"] == "금융업" and n["C"] == "제조업"
    assert sum(1 for k in n if k.isdigit()) == 77 and sum(1 for k in n if k.isalpha() and k != "ALL") == 21
    assert n["ALL"] == "전체 시장" and n["01"] == "농업"


def test_division_section():
    assert division("30121") == "30" and division("") == "" and division(None) == ""
    assert section("35") == "D" and section("20") == "C" and section("04") == "" and section("40") == ""


def test_small_division_falls_back_to_section():
    st = {f"A{i}": ("20111", 10.0 + i, 100.0) for i in range(6)} | {"B0": ("21000", 30.0, 50.0), "B1": ("21000", 5.0, 80.0)}
    t = build_industry(st, 5)
    assert t["A0"].group_code == "20" and t["B0"].group_code == "C" and t["B0"].roe_rank_pct == 12.5
    assert t["A5"].roe_rank_pct == round(1 / 6 * 100, 1) and t["A0"].roe_median == 12.5
    assert t["B0"].size == 8 and t["B0"].group_name == "제조업"


def test_debt_rank_lower_is_better():
    st = {f"A{i}": ("20111", 10.0, 100.0 + i) for i in range(5)}
    t = build_industry(st, 5)
    assert t["A0"].debt_rank_pct == 20.0 and t["A4"].debt_rank_pct == 100.0 and t["A0"].debt_median == 102.0


def test_ties_share_better_rank():
    st = {"a": ("20", 10.0, 1.0), "b": ("20", 10.0, 1.0), "c": ("20", 5.0, 2.0)}
    t = build_industry(st, 3)
    assert t["a"].roe_rank_pct == t["b"].roe_rank_pct == round(1 / 3 * 100, 1)
    assert t["c"].roe_rank_pct == 100.0 and t["a"].debt_rank_pct == t["b"].debt_rank_pct == round(1 / 3 * 100, 1)


def test_missing_values_keep_group_but_no_rank():
    st = {f"A{i}": ("20111", 10.0 + i, 100.0) for i in range(5)} | {"N": ("20111", None, None)}
    t = build_industry(st, 5)
    assert t["N"].group_code == "20" and t["N"].roe_rank_pct is None and t["N"].debt_rank_pct is None
    assert t["N"].size == 6 and t["A4"].roe_rank_pct == 20.0


def test_unknown_or_empty_code_goes_to_all():
    st = {"u": ("04001", 5.0, 1.0), "e": ("", 6.0, 2.0), "n": (None, 7.0, 3.0), "k": ("40100", 8.0, 4.0)}
    t = build_industry(st, 5)
    assert all(t[c].group_code == "ALL" and t[c].group_name == "전체 시장" and t[c].size == 4 for c in st)
    assert t["n"].roe_rank_pct == 50.0


def test_unlisted_division_name():
    st = {f"A{i}": ("04001", 1.0 + i, 1.0) for i in range(5)}
    assert build_industry(st, 1)["A0"].group_name == "업종코드 04"


def test_overrides_division_then_section():
    assert effective_criteria(Criteria(), "35110", {"35": {"roe_min": 6.0}}).roe_min == 6.0
    assert effective_criteria(Criteria(), "35110", {"D": {"roe_min": 5.0}}).roe_min == 5.0
    assert effective_criteria(Criteria(), "30121", {"35": {"roe_min": 6.0}}).roe_min == 8.0
    assert effective_criteria(Criteria(), "35110", {"35": {"roe_min": 6.0}, "D": {"roe_min": 5.0}}).roe_min == 6.0
    assert effective_criteria(Criteria(), None, {"D": {"roe_min": 5.0}}).roe_min == 8.0


@pytest.mark.parametrize("on,rank,want", [(False, 10.0, None), (True, None, "입력 필요"), (True, 50.0, "통과"), (True, 50.1, "탈락")])
def test_extra_gate1(on, rank, want):
    assert extra_gate1(info(roe_rank_pct=rank), IndustrySettings(use_in_verdict=on)) == want


def test_extra_gate1_no_info():
    assert extra_gate1(None, IndustrySettings(use_in_verdict=True)) == "입력 필요"


@pytest.mark.parametrize("name", ["kia_full_pass", "kia_cov999_no_debt"])
def test_industry_inputs_matches_b78_b79(name):
    inputs, _, cells = load_oracle(name)
    roe, debt = industry_inputs(inputs)
    assert roe == pytest.approx(cells["B78"], abs=0.005) and debt == cells["B79"]
