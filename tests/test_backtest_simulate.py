"""백테스트 시뮬레이션 (2026-11-24 백테스트 설계 3장). 묶음·시세를 직접 만들어요 (DART·KRX 없음)."""
from dataclasses import replace
from datetime import date, timedelta

import pytest
from vsf.backtest.model import Verdict, Vintage
from vsf.backtest.simulate import Rules, simulate
from vsf.data.store import PriceRow

RULES = Rules(monthly=1_300_000.0, max_holdings=5, cost_rate=0.0025, min_trade=10_000.0)
V = "지금 규칙"
EARLY = date(2019, 12, 1)


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def vin(code, fair, *, buy=None, valid_from=EARLY, corp=None, gate1="통과", gate2="통과", uncomputable=False,
        year=2018, dps=None, shares=1e6):
    if buy is None and fair is not None:
        buy = fair * 0.75
    return Vintage(code=code, corp_code=corp or f"C{code}", name=f"종목{code}", common_code=None, year=year,
                   filed=valid_from, valid_from=valid_from, shares=shares, dps=dps, substitute=False,
                   verdicts={V: Verdict(gate1, gate2, fair, buy, "A 이론", uncomputable)})


def market(table: dict[date, dict[str, float]], shares: dict[str, float] | None = None):
    """{날: {코드: 종가}} → stocks(day). 상장주식수는 shares(없으면 100만 주)."""
    def stocks(day):
        return {c: PriceRow(day, c, f"종목{c}", "KOSPI", p, (shares or {}).get(c, 1e6))
                for c, p in table.get(day, {}).items()}
    return stocks


def flat(ds, closes: dict[str, float]) -> dict[date, dict[str, float]]:
    return {d: dict(closes) for d in ds}


def run(ds, table, vintages, *, rules=RULES, cma=lambda a, b: 1.0, month_starts=None, listed=None, shares=None):
    codes = {c for row in table.values() for c in row}
    return simulate(ds, market(table, shares), vintages, V, rules, cma,
                    listed or (lambda d: codes), set(month_starts or {ds[0]}))


def trade(result, code):
    return next(t for t in result.trades if t.code == code)


def test_monthly_deposit_goes_to_cma_and_earns_interest():
    ds = weekdays(date(2020, 1, 2), 25)                      # 1월 2일 ~ 2월 5일
    feb = next(d for d in ds if d.month == 2)
    r = run(ds, {}, {}, cma=lambda a, b: 1.001, month_starts={ds[0], feb})
    assert r.deposits == [(ds[0], 1_300_000.0), (feb, 1_300_000.0)]
    assert r.cash[0] == 1_300_000.0 and r.cash[1] == pytest.approx(1_300_000.0 * 1.001)
    assert r.value == r.cash and r.trades == []


def test_buys_cheapest_up_to_five_with_equal_split():
    closes = dict(zip("ABCDEFG", (50.0, 52.0, 54.0, 56.0, 58.0, 60.0, 62.0)))
    ds = weekdays(date(2020, 1, 2), 3)
    r = run(ds, flat(ds, closes), {c: [vin(c, 100.0)] for c in closes})
    held = {t.code: t for t in r.trades}
    assert sorted(held) == list("ABCDE")
    for c in "ABCDE":
        assert held[c].invested == pytest.approx(260_000.0)
        assert held[c].shares == pytest.approx(260_000.0 * 0.9975 / closes[c])
    assert r.cash[0] == pytest.approx(0.0, abs=1e-6)


def test_new_money_also_goes_to_held_stocks_that_are_still_cheap():
    ds = weekdays(date(2020, 1, 30), 4)                      # 1월 30·31일, 2월 3·4일
    feb = date(2020, 2, 3)
    closes = dict(zip("ABCDE", (50.0, 52.0, 54.0, 56.0, 58.0)))
    r = run(ds, flat(ds, closes), {c: [vin(c, 100.0)] for c in closes}, month_starts={ds[0], feb})
    assert all(t.invested == pytest.approx(520_000.0) for t in r.trades)


def test_sells_at_fair_value_and_switches_the_same_day():
    ds = weekdays(date(2020, 1, 2), 4)
    table = flat(ds, {"A": 50.0, "B": 60.0})
    table[ds[2]] = {"A": 100.0, "B": 60.0}                    # 셋째 날 A가 적정가 도달
    one = Rules(monthly=1_300_000.0, max_holdings=1, cost_rate=0.0025, min_trade=10_000.0)
    r = run(ds, table, {"A": [vin("A", 100.0)], "B": [vin("B", 100.0)]}, rules=one)
    a, b = trade(r, "A"), trade(r, "B")
    assert (a.reason, a.sell_date, a.sell_price) == ("적정가 도달", ds[2], 100.0)
    assert a.proceeds == pytest.approx(a.shares * 100.0 * 0.9975)
    assert b.first_buy == ds[2] and b.invested == pytest.approx(a.proceeds)


def test_uncomputable_fair_value_sells():
    ds = weekdays(date(2020, 1, 2), 4)
    later = vin("A", None, buy=None, valid_from=ds[2], uncomputable=True, year=2019)
    r = run(ds, flat(ds, {"A": 50.0}), {"A": [vin("A", 100.0), later]})
    a = trade(r, "A")
    assert (a.reason, a.sell_date) == ("적정가 계산 불가", ds[2])


def test_missing_fair_value_holds_and_flags_once():
    ds = weekdays(date(2020, 1, 2), 6)
    later = vin("A", None, buy=None, valid_from=ds[2], year=2019)
    r = run(ds, flat(ds, {"A": 50.0}), {"A": [vin("A", 100.0), later]})
    a = trade(r, "A")
    assert a.reason == "보유 중" and a.flags.count("적정가를 구하지 못해 들고 있어요") == 1


def test_one_share_class_per_company():
    ds = weekdays(date(2020, 1, 30), 4)
    feb = date(2020, 2, 3)
    table = flat(ds, {"000270": 50.0, "000275": 40.0})
    vintages = {"000270": [vin("000270", 100.0, corp="K")], "000275": [vin("000275", 100.0, corp="K")]}
    r = run(ds, table, vintages, month_starts={ds[0], feb})
    assert [t.code for t in r.trades] == ["000275"]          # 비율이 낮은 쪽 하나만, 다음 달에도 다른 쪽은 안 사요


def test_small_cash_stays_in_cma():
    ds = weekdays(date(2020, 1, 2), 2)
    small = Rules(monthly=15_000.0, max_holdings=5, cost_rate=0.0025, min_trade=10_000.0)
    r = run(ds, flat(ds, {"A": 50.0, "B": 52.0}), {"A": [vin("A", 100.0)], "B": [vin("B", 100.0)]}, rules=small)
    assert r.trades == [] and r.cash[-1] == 15_000.0


def test_vintage_is_used_only_from_valid_from():
    ds = weekdays(date(2020, 1, 2), 4)
    r = run(ds, flat(ds, {"A": 50.0}), {"A": [vin("A", 100.0, valid_from=ds[2])]})
    assert trade(r, "A").first_buy == ds[2] and r.cash[1] == 1_300_000.0


def test_holdings_at_end_are_listed_as_holding():
    ds = weekdays(date(2020, 1, 2), 2)
    a = trade(run(ds, flat(ds, {"A": 50.0}), {"A": [vin("A", 100.0)]}), "A")
    assert (a.reason, a.sell_date, a.sell_price, a.proceeds) == ("보유 중", None, None, None)
    assert a.basis == "2018 사업보고서 · A 이론 · 적정가 100원 · 매수선 75원"


def test_holding_whose_gates_turn_fail_is_flagged_not_sold():
    ds = weekdays(date(2020, 1, 2), 6)
    later = vin("A", 100.0, valid_from=ds[2], gate2="탈락", year=2019)
    r = run(ds, flat(ds, {"A": 60.0}), {"A": [vin("A", 100.0), later]})
    a = trade(r, "A")
    assert a.reason == "보유 중" and a.flags.count("산 뒤 관문 ①② 탈락으로 바뀌었어요") == 1


# ---- 배당·분할·거래정지·상장폐지 (플랜 Task 9) ----

def span(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_dividend_from_year_end_holdings_is_paid_when_the_report_is_filed():
    ds = span(date(2019, 12, 27), date(2020, 4, 3))
    pay_day = date(2020, 3, 30)
    vintages = {"A": [vin("A", 100.0, year=2018, dps=4.0), vin("A", 100.0, valid_from=pay_day, year=2019, dps=5.0)]}
    r = run(ds, flat(ds, {"A": 50.0}), vintages, month_starts={ds[0]})
    a = trade(r, "A")
    held_at_year_end = 1_300_000.0 * 0.9975 / 50.0
    assert a.dividends == pytest.approx(held_at_year_end * 5.0)
    before = ds.index(pay_day) - 1
    assert r.value[before] == pytest.approx(held_at_year_end * 50.0)            # 공시 전에는 배당이 없어요
    assert a.invested == pytest.approx(1_300_000.0 + held_at_year_end * 5.0)    # 받은 배당도 다시 사요


def test_dividend_is_paid_even_after_selling_if_held_at_year_end():
    ds = span(date(2019, 12, 27), date(2020, 4, 3))
    table = flat(ds, {"A": 50.0})
    for d in ds:
        if d >= date(2020, 2, 10):
            table[d] = {"A": 100.0}                                              # 2월 10일 적정가 도달
    vintages = {"A": [vin("A", 100.0, year=2018), vin("A", 100.0, valid_from=date(2020, 3, 30), year=2019, dps=5.0)]}
    r = run(ds, table, vintages, month_starts={ds[0]})
    a = trade(r, "A")
    assert a.reason == "적정가 도달" and a.sell_date == date(2020, 2, 10)
    assert a.dividends == pytest.approx(1_300_000.0 * 0.9975 / 50.0 * 5.0)
    assert r.cash[-1] == pytest.approx(a.proceeds + a.dividends)


def test_split_multiplies_shares_and_scales_fair_value():
    ds = span(date(2020, 1, 2), date(2020, 1, 10))
    split_day = date(2020, 1, 7)
    table = {d: ({"A": 50.0, "C": 100.0} if d < split_day else {"A": 10.0, "C": 20.0}) for d in ds}

    def shares_of(day):
        return {"A": 1e6 if day < split_day else 5e6, "C": 1e6 if day < split_day else 5e6}

    def stocks(day):
        return {c: PriceRow(day, c, f"종목{c}", "KOSPI", p, shares_of(day)[c]) for c, p in table[day].items()}

    vintages = {"A": [vin("A", 100.0)], "C": [vin("C", 100.0)]}
    one = Rules(monthly=1_300_000.0, max_holdings=5, cost_rate=0.0025, min_trade=10_000.0)
    r = simulate(ds, stocks, vintages, V, one, lambda a, b: 1.0, lambda d: {"A", "C"}, {ds[0], split_day})
    a = trade(r, "A")
    first = 1_300_000.0 * 0.9975 / 50.0
    assert a.reason == "보유 중" and a.shares > first * 5 - 1                    # 분할 배수만큼 주식 수가 늘었어요
    assert [t.code for t in r.trades] == ["A"]                                    # C는 분할로 싸 보여도 사지 않아요
    assert r.value[ds.index(split_day)] == pytest.approx(first * 5 * 10.0 + 1_300_000.0 * 0.9975, rel=1e-6)


def test_rights_offering_is_not_a_split():
    ds = span(date(2020, 1, 2), date(2020, 1, 8))
    issue_day = date(2020, 1, 6)

    def stocks(day):
        return {"A": PriceRow(day, "A", "종목A", "KOSPI", 50.0, 1.6e6 if day >= issue_day else 1e6)}

    r = simulate(ds, stocks, {"A": [vin("A", 100.0)]}, V, RULES, lambda a, b: 1.0, lambda d: {"A"}, {ds[0]})
    assert trade(r, "A").shares == pytest.approx(1_300_000.0 * 0.9975 / 50.0)


def test_trading_halt_holds_at_last_close():
    ds = span(date(2020, 1, 2), date(2020, 3, 31))
    table = {d: ({"A": 50.0} if d == ds[0] or d >= date(2020, 3, 2) else {}) for d in ds}
    r = run(ds, table, {"A": [vin("A", 100.0)]}, listed=lambda d: {"A"}, month_starts={ds[0]})
    shares = 1_300_000.0 * 0.9975 / 50.0
    assert all(v == pytest.approx(shares * 50.0) for v in r.value[:40])
    assert trade(r, "A").reason == "보유 중"


def test_delisted_stock_is_sold_at_last_close():
    ds = span(date(2020, 1, 2), date(2020, 2, 7))
    table = {d: ({"A": 40.0} if d.month == 1 else {}) for d in ds}
    table[ds[0]] = {"A": 50.0}
    feb = date(2020, 2, 3)
    r = run(ds, table, {"A": [vin("A", 100.0)]}, listed=lambda d: {"A"} if d.month == 1 else set(),
            month_starts={ds[0], feb})
    a = trade(r, "A")
    assert (a.reason, a.sell_date, a.sell_price) == ("상장폐지", feb, 40.0)
    assert a.proceeds == pytest.approx(a.shares * 40.0 * 0.9975)


def test_big_drop_is_flagged():
    ds = span(date(2020, 1, 2), date(2020, 1, 8))
    table = flat(ds, {"A": 50.0})
    for d in ds[2:]:
        table[d] = {"A": 25.0}
    a = trade(run(ds, table, {"A": [vin("A", 100.0)]}), "A")
    assert a.flags.count("하루에 40% 넘게 떨어졌어요(분할·합병 확인 필요)") == 1

def test_blocked_bundle_is_not_bought():
    # 주당 숫자를 믿기 어려운 묶음(연말 뒤 주식 수가 크게 바뀜)으로는 사지 않아요.
    ds = weekdays(date(2020, 1, 6), 3)
    v = replace(vin("000270", 10_000.0), blocked=True)
    r = run(ds, flat(ds, {"000270": 5_000.0}), {"000270": [v]})
    assert r.trades == [] and r.cash[-1] == RULES.monthly
