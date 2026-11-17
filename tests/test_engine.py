import re

import pytest
from helpers import ORACLE_NAMES, assert_cells_match, load_oracle

from vsf.engine import compute
from vsf.model import FORMULA_CELLS


def row(addr: str) -> int:
    return int(re.sub(r"[A-Z]+", "", addr))


PART_A = [a for a in FORMULA_CELLS if 43 <= row(a) <= 55 or 78 <= row(a) <= 100]


@pytest.mark.parametrize("name", ORACLE_NAMES)
def test_part_a_matches_oracle(name):
    inputs, criteria, want = load_oracle(name)
    assert_cells_match(compute(inputs, criteria), want, PART_A)


def test_extra_gate1_is_a_fifth_item_of_d82():
    inputs, criteria, want = load_oracle(ORACLE_NAMES[0])
    assert compute(inputs, criteria, extra_gate1="탈락")["D82"] == "탈락"
    assert compute(inputs, criteria, extra_gate1=None)["D82"] == want["D82"]


from dataclasses import replace  # noqa: E402

from vsf.config import ReportSettings  # noqa: E402
from vsf.engine import is_near, summarize, watch_state  # noqa: E402


@pytest.mark.parametrize("name", ORACLE_NAMES)
def test_all_cells_match_oracle(name):
    inputs, criteria, want = load_oracle(name)
    got = compute(inputs, criteria)
    assert set(got) == set(FORMULA_CELLS)
    assert_cells_match(got, want, FORMULA_CELLS)


def test_extra_gate1_fail_propagates():
    inputs, c, _ = load_oracle("kia_full_pass")
    got = compute(inputs, c, extra_gate1="탈락")
    assert got["D82"] == "탈락" and got["B7"] == "탈락" and got["B15"].startswith("관문 ①에서 탈락했어요")


def test_extra_gate1_missing_makes_check_needed():
    inputs, c, _ = load_oracle("kia_full_pass")
    assert compute(inputs, c, extra_gate1="입력 필요")["D82"] == "확인 필요"


@pytest.mark.parametrize("price,state,near", [(97000, "out", False), (80000, "watch", False),
                                              (75000, "watch", True), (60000, "buy", True)])
def test_watch_state(price, state, near):
    inputs, c, _ = load_oracle("kia_full_pass")
    s = summarize(compute(replace(inputs, price=float(price)), c))
    assert watch_state(s, ReportSettings()) == state and is_near(s, ReportSettings()) is near


def test_gate2_fail_is_out_even_if_cheap():
    inputs, c, _ = load_oracle("kia_zero_dps")
    s = summarize(compute(replace(inputs, price=10000.0), c))
    assert s.gate2 == "탈락" and watch_state(s, ReportSettings()) == "out"
