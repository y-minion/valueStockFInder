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
