"""점수 계산 (점수 순위 설계 5장)."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from vsf.config import ItemRule, ScoreSettings
from vsf.data.score_facts import ScoreFacts
from vsf.model import StockInputs, YearRow
from vsf.score import JUDGMENT, dividend_streak, eligible, grade, rank, score_stock, step_points

EPS = (3000.0, 3200.0, 3500.0, 3600.0, 4000.0)
DPS = (1000.0, 1100.0, 1100.0, 1200.0, 1300.0)
PRIOR = (None, 700.0, 800.0, 800.0, 900.0)


def stock(eps=EPS, dps=DPS, prior=PRIOR, price=30000.0, pbr=0.5, b108=0.7, b78=12.0, b115=0.055,
          quick_fail=False):
    years = tuple(YearRow(year=2021 + i, eps=e, dps=d) for i, (e, d) in enumerate(zip(eps, dps)))
    inputs = StockInputs(name="가", code="000001", price=price, pbr=pbr, years=years,
                         prior_years=(2016, 2017, 2018, 2019, 2020), prior_dps=prior)
    return SimpleNamespace(assembled=SimpleNamespace(quick_fail=quick_fail, inputs=inputs, latest_year=2025),
                           cells={"B108": b108, "B78": b78, "B115": b115})


FACTS = ScoreFacts(ttm_eps=4200.0, ttm_label="2025년 4분기~2026년 3분기", payout_per_year=4,
                   issued=1_000_000.0, treasury=0.0, buyback_years=(True, True, True), cancelled=16_300.0,
                   subsidiaries=())


def item(s: dict, key: str) -> dict:
    return next(i for i in s["items"] if i["key"] == key)


def test_step_points_each_op():
    per = ItemRule(15, ((5, 15), (8, 11), (10, 7), (15, 3)))
    assert [step_points(v, per, "lt") for v in (4.9, 5, 7.9, 14.9, 15, 40)] == [15, 11, 11, 3, 0, 0]
    ratio = ItemRule(15, ((0.75, 15), (0.9, 10), (1.0, 6), (1.2, 3)))
    assert step_points(0.75, ratio, "le") == 15 and step_points(0.76, ratio, "le") == 10
    roe = ItemRule(10, ((15, 10), (10, 7), (8, 5), (5, 2)))
    assert [step_points(v, roe, "ge") for v in (15, 14.9, 8, 4.9)] == [10, 7, 5, 0]
    yld = ItemRule(10, ((7, 10), (5, 7), (3, 5), (0, 2)))
    assert [step_points(v, yld, "gt") for v in (7.01, 7, 0.1, 0)] == [10, 7, 2, 0]


def test_dividend_streak_counts_raises_and_skips_freezes():
    assert dividend_streak((100, 100, 120, 120, 130), (130, 150, 150, 160, 170)) == 5
    assert dividend_streak((None,) * 5, (100, 90, 100, 110, 120)) == 3
    assert dividend_streak((None,) * 5, (100, 100, 100, 100, None)) is None
    assert dividend_streak((None,) * 5, (100, 100, 100, 100, 100)) == 0


def test_score_full_example():
    s = score_stock(stock(), FACTS, ScoreSettings())
    # PER 7.5 → 11, PBR 0.5 → 4, 주가÷적정가 0.7 → 15 / ROE 12 → 7, 적자 없음 5, 4분기 4200÷4000 → 5
    # 배당 5.5% → 7, 연속 인상 6년 → 4, 분기 → 5, 매년 자사주 → 7, 소각 1.6% → 5, 자사주 0주 → 5 / 상장 자회사 없음 5
    assert s["groups"] == {"cheap": 30, "steady": 17, "return": 33, "other": 5}
    assert s["total"] == 85 and s["max"] == 100 and s["grade"] == "A" and s["missing"] == 0
    assert item(s, "per")["value"] == "7.5배" and item(s, "per")["points"] == 11
    assert item(s, "streak")["value"] == "6년"
    assert item(s, "treasury")["value"] == "없음" and item(s, "freq")["value"] == "분기"
    assert item(s, "per")["rule"] == "5배 미만 15 · 8배 미만 11 · 10배 미만 7 · 15배 미만 3"
    assert item(s, "yield")["rule"] == "7% 초과 10 · 5% 초과 7 · 3% 초과 5 · 0% 초과 2"
    assert all(i["status"] == "ok" for i in s["items"])


def test_loss_year_gives_zero_not_error():
    s = score_stock(stock(eps=EPS[:4] + (-100.0,)), replace(FACTS, ttm_eps=50.0), ScoreSettings())
    assert item(s, "per")["points"] == 0 and item(s, "per")["value"] == "적자" and item(s, "per")["status"] == "ok"
    assert item(s, "ttm")["points"] == 0 and item(s, "no_loss")["points"] == 0


def test_annual_is_latest_gives_full_ttm():
    s = score_stock(stock(), replace(FACTS, ttm_eps=None, ttm_label=None, ttm_is_annual=True), ScoreSettings())
    assert item(s, "ttm")["points"] == 5 and "가장 최신" in item(s, "ttm")["value"]


def test_missing_facts_are_no_data_and_counted():
    s = score_stock(stock(), None, ScoreSettings())
    keys = {i["key"] for i in s["items"] if i["status"] == "no_data"}
    assert keys == {"ttm", "freq", "buyback", "cancel", "treasury", "subsidiary"}
    assert s["missing"] == 5 + 5 + 7 + 8 + 5 + 5 and s["total"] == 30 + 12 + 11


def test_partial_buyback_years_is_no_data_and_a_gap_is_zero():
    assert item(score_stock(stock(), replace(FACTS, buyback_years=(True, None, True)), ScoreSettings()),
                "buyback")["status"] == "no_data"
    assert item(score_stock(stock(), replace(FACTS, buyback_years=(True, False, True)), ScoreSettings()),
                "buyback")["points"] == 0


def test_listed_subsidiary_takes_the_points_and_names_it():
    s = score_stock(stock(), replace(FACTS, subsidiaries=(("우리은행", 100.0),)), ScoreSettings())
    i = item(s, "subsidiary")
    assert i["points"] == 0 and "우리은행" in i["value"] and "틀릴 수" in i["value"]


def test_missing_cells_are_no_data():
    s = score_stock(stock(pbr=None, b108=None), FACTS, ScoreSettings())
    assert item(s, "pbr")["status"] == "no_data" and item(s, "ratio")["status"] == "no_data"
    assert s["missing"] == 20


def test_not_eligible_when_quick_fail_or_no_latest_dividend():
    assert eligible(stock()) and not eligible(stock(quick_fail=True))
    assert not eligible(stock(dps=DPS[:4] + (0.0,))) and not eligible(stock(dps=DPS[:4] + (None,)))
    assert score_stock(stock(quick_fail=True), FACTS, ScoreSettings()) is None


def test_settings_change_points_and_max():
    cfg = ScoreSettings()
    cfg = replace(cfg, items={**cfg.items, "per": ItemRule(20, ((5, 20), (8, 12)))})
    s = score_stock(stock(), FACTS, cfg)
    assert item(s, "per")["points"] == 12 and s["max"] == 105


def test_grade_boundaries_are_strict():
    cfg = ScoreSettings()
    assert [grade(x, cfg) for x in (80.5, 80, 70.5, 70, 50.5, 50)] == ["A", "B", "B", "C", "C", "D"]


def test_rank_order():
    scores = {"a": {"total": 60}, "b": {"total": 70}, "c": {"total": 60}, "d": {"total": 60}}
    assert rank(scores, {"a": 0.9, "b": 1.2, "c": None, "d": 0.8}) == ["b", "d", "a", "c"]


def test_judgment_items_are_four_with_go_ava_points():
    assert [j[0] for j in JUDGMENT] == ["sustain", "growth", "management", "brand"]
    assert sum(max(j[3]) for j in JUDGMENT) == 30
    assert all(len(j[2]) == len(j[3]) for j in JUDGMENT)
