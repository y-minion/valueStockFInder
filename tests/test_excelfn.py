from datetime import date

import pytest

from vsf.excelfn import average, count, excel_round, excel_text, is_num


@pytest.mark.parametrize("x,d,want", [(0.605, 2, 0.61), (0.6015870660805305, 2, 0.6), (2.5, 0, 3.0),
                                      (-2.5, 0, -3.0), (0.27531662509536, 2, 0.28)])
def test_excel_round(x, d, want):
    assert excel_round(x, d) == want


@pytest.mark.parametrize("x,fmt,want", [
    (0.269692307692308, "0%", "27%"), (0.281303020851005, "0%", "28%"), (0.6015870660805305, "0%", "60%"),
    (69713.6069774525, "#,##0", "69,714"), (14241, "#,##0", "14,241"), (1 - 0.25, "0.00", "0.75"),
    (22.32, "#,##0.0", "22.3"), (115.56, "#,##0.0", "115.6"), (125.93, "0", "126"), (8, "0", "8"),
    (3, "0.0", "3.0"), (1.0, "0.0", "1.0"), (date(2026, 11, 9), "yyyy-mm-dd", "2026-11-09")])
def test_excel_text(x, fmt, want):
    assert excel_text(x, fmt) == want


def test_excel_text_unknown_format():
    with pytest.raises(ValueError):
        excel_text(1, "0.000")


def test_is_num_count_average_skip_non_numbers():
    vals = [1, None, "x", True, 3.0]
    assert is_num(1) and not is_num(True) and not is_num("1")
    assert count(vals) == 2
    assert average(vals) == 2.0
    assert average([None, "x"]) is None
