import json
from datetime import date

from engine_cases import KIA, replace_year
from vsf.model import Criteria, criteria_to_cells, inputs_from_dict, inputs_to_dict, to_cells


def test_to_cells_mapping():
    c = to_cells(KIA)
    assert c["B19"] == "000270" and c["F27"] == 19382 and c["B42"] == 1100 and c["B21"] == date(2026, 11, 9)
    assert c["B37"] is None and to_cells(replace_year(KIA, 2, exclude_avg=True))["D37"] == "X"


def test_criteria_to_cells():
    assert criteria_to_cells(Criteria()) == {"B5": 0.10, "B6": 0.25, "B7": 8.0, "B8": 200.0, "B9": 3.0,
        "B10": 1.0, "B11": 0.20, "B12": 0.60, "B13": 1.0, "B14": 0.5, "B15": 0.10}


def test_dict_roundtrip():
    assert inputs_from_dict(json.loads(json.dumps(inputs_to_dict(KIA)))) == KIA
