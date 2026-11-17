from vsf.boundary import Boundary, boundaries, near_miss_state
from vsf.config import ReportSettings
from vsf.financial import CapitalRatio, FinancialGate
from vsf.model import Criteria


def test_roe_just_below_is_a_failed_boundary():
    cells = {"B78": 7.6, "D78": "탈락"}
    assert boundaries(cells, Criteria(), None) == (Boundary("D78", "ROE 5년 평균", 7.6, 8.0, -0.4, "%p", False),)


def test_payout_compared_after_rounding():
    (b,) = boundaries({"B88": 0.595, "D88": "통과"}, Criteria(), None)
    assert (b.cell, b.threshold, b.gap, b.passed) == ("D88", 60.0, 0.0, True)


def test_far_values_and_unjudged_items_are_ignored():
    cells = {"B78": 12.0, "D78": "통과", "B79": None, "D79": "입력 필요", "D80": "해당 없음"}
    assert boundaries(cells, Criteria(), None) == ()


def test_capital_boundary_uses_kind_step():
    g = FinancialGate("보험", CapitalRatio(125.0, "2026-06", "FISIS"), 130.0)
    (b,) = boundaries({"F_CAP_B": 125.0, "F_CAP_D": "탈락"}, Criteria(), g)
    assert (b.label, b.gap, b.passed) == ("지급여력비율(K-ICS)", -5.0, False)


def test_text_ocf_is_not_a_boundary():
    assert boundaries({"B81": "순이익 합계 0 이하", "D81": "탈락"}, Criteria(), None) == ()


def test_near_miss_requires_every_failure_borderline():
    cells = {"B78": 7.6, "D78": "탈락", "B79": 300.0, "D79": "탈락", "D82": "탈락", "D90": "통과",
             "D110": "통과", "B109": 0.0}
    assert near_miss_state(cells, boundaries(cells, Criteria(), None), ReportSettings()) is None
    cells.update({"D79": "통과", "B79": 100.0})
    assert near_miss_state(cells, boundaries(cells, Criteria(), None), ReportSettings()) == "buy"


def test_near_miss_watch_and_out():
    cells = {"B78": 7.6, "D78": "탈락", "D82": "탈락", "D110": "탈락", "B109": 0.15}
    b = boundaries(cells, Criteria(), None)
    assert near_miss_state(cells, b, ReportSettings()) == "watch"
    cells["B109"] = 0.5
    assert near_miss_state(cells, b, ReportSettings()) == "out"


def test_near_miss_is_none_when_industry_verdict_failed():
    cells = {"B78": 7.6, "D78": "탈락", "D82": "탈락", "D110": "통과", "B109": 0.0}
    b = boundaries(cells, Criteria(), None)
    assert near_miss_state(cells, b, ReportSettings()) == "buy"
    assert near_miss_state(cells, b, ReportSettings(), extra_gate1="탈락") is None
    assert near_miss_state(cells, b, ReportSettings(), extra_gate1="통과") == "buy"
