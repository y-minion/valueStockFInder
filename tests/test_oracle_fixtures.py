import pytest
from engine_cases import CASES, CHEIL, KIA
from helpers import (ORACLE_NAMES, approx_cells, assert_cells_match, input_values, load_oracle,
                     stored_values)
from tools.dump_formulas import formula_addresses
from vsf.model import FORMULA_CELLS, to_cells


def test_every_case_has_fixture():
    assert sorted(ORACLE_NAMES) == sorted(CASES)
    for name in CASES:
        inputs, criteria, cells = load_oracle(name)
        assert (inputs, criteria) == CASES[name]
        assert set(cells) == set(FORMULA_CELLS) and len(FORMULA_CELLS) == 152


@pytest.mark.template
def test_formula_cells_match_template(template_path):
    assert list(FORMULA_CELLS) == formula_addresses(template_path)


@pytest.mark.template
def test_example_inputs_match_template(template_path):
    for sheet, inputs in (("예시_제일기획", CHEIL), ("예시_기아", KIA)):
        want = approx_cells(to_cells(inputs), exclude={"B23"})
        assert input_values(template_path, sheet, exclude={"B23"}) == want


@pytest.mark.template
def test_oracle_vs_stored_example_values(template_path):
    for sheet, case in (("예시_제일기획", "cheil"), ("예시_기아", "kia")):
        assert_cells_match(load_oracle(case)[2], stored_values(template_path, sheet), FORMULA_CELLS)
