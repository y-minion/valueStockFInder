"""백테스트: 수익률·최대 하락·비교 기준 (2026-11-24 백테스트 설계 5·6장)."""
from datetime import date

import pytest
from vsf.backtest.benchmark import benchmark
from vsf.backtest.metrics import cash_share, max_drawdown, unit_values, xirr, yearly_returns
from vsf.backtest.simulate import Rules

RULES = Rules(monthly=1_300_000.0, max_holdings=5, cost_rate=0.0025, min_trade=10_000.0)


def _npv(flows, r):
    t0 = flows[0][0]
    return sum(cf / (1 + r) ** ((d - t0).days / 365) for d, cf in flows)


def test_xirr_simple_year():
    assert xirr([(date(2020, 1, 1), -100.0), (date(2021, 1, 1), 110.0)]) == pytest.approx(0.10, abs=0.001)


def test_xirr_monthly_deposits():
    flows = [(date(2020, m, 1), -100.0) for m in range(1, 13)] + [(date(2020, 12, 31), 1_300.0)]
    r = xirr(flows)
    assert r is not None and r > 0 and _npv(flows, r) == pytest.approx(0.0, abs=1e-6)


def test_xirr_with_one_sign_is_none():
    assert xirr([(date(2020, 1, 1), -100.0), (date(2020, 6, 1), -100.0)]) is None


def test_unit_values_ignore_deposits():
    assert unit_values([100.0, 200.0, 300.0], [100.0, 100.0, 100.0]) == [1.0, 1.0, 1.0]
    got = unit_values([0.0, 100.0, 110.0, 220.0], [0.0, 100.0, 0.0, 100.0])
    assert got[:3] == [1.0, 1.0, pytest.approx(1.1)] and got[3] == pytest.approx(1.1 * 120 / 110)


def test_max_drawdown_and_bottom_day():
    days = [date(2020, 1, d) for d in (2, 3, 6, 7, 8)]
    assert max_drawdown(days, [1.0, 1.2, 0.9, 1.0, 1.3]) == (pytest.approx(-0.25), date(2020, 1, 6))
    assert max_drawdown(days, [1.0, 1.1, 1.2, 1.3, 1.4]) == (0.0, None)


def test_yearly_returns_split_by_calendar_year():
    days = [date(2020, 12, 30), date(2020, 12, 31), date(2021, 1, 4), date(2021, 12, 30)]
    got = yearly_returns(days, [1.0, 1.1, 1.21, 1.331])
    assert got == {2020: pytest.approx(0.1), 2021: pytest.approx(0.21)}


def test_cash_share():
    assert cash_share([0.0, 100.0, 200.0], [0.0, 50.0, 0.0]) == pytest.approx(0.25)


def test_benchmark_buys_monthly_and_holds():
    days = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 2, 3), date(2020, 2, 4)]
    prices = {days[0]: 100.0, days[1]: 100.0, days[2]: 110.0, days[3]: 121.0}
    r = benchmark(days, prices.get, RULES, {days[0], days[2]})
    units = 1_300_000.0 * 0.9975 / 100.0 + 1_300_000.0 * 0.9975 / 110.0
    assert r.value[-1] == pytest.approx(units * 121.0) and r.trades == []
    assert r.deposits == [(days[0], 1_300_000.0), (days[2], 1_300_000.0)] and r.cash[-1] == 0.0


def test_benchmark_waits_for_the_first_price():
    days = [date(2020, 7, 1), date(2020, 7, 2), date(2020, 7, 3)]
    prices = {days[1]: 50.0, days[2]: 55.0}
    r = benchmark(days, prices.get, RULES, {days[0]})
    assert r.value[0] == 1_300_000.0 and r.cash[0] == 1_300_000.0
    assert r.value[-1] == pytest.approx(1_300_000.0 * 0.9975 / 50.0 * 55.0)
