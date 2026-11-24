"""비교 기준: 같은 날 같은 돈을 ETF·지수에 넣어 끝까지 들고 있는 경우 (2026-11-24 백테스트 설계 5장)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from vsf.backtest.simulate import Rules, SimResult


def benchmark(days: list[date], close: Callable[[date], float | None], rules: Rules,
              month_starts: set[date]) -> SimResult:
    """달 첫 거래일에 monthly × (1 − cost_rate) ÷ 종가만큼 단위를 사서 끝까지 들고 있어요.

    그날 종가가 없으면(그 상품이 아직 없거나 휴장) 돈을 들고 있다가 다음에 종가가 있는 날 사요.
    분배금은 KRX 자료에 없어서 빠져 있어요.
    """
    units, waiting, last = 0.0, 0.0, None
    value: list[float] = []
    cash: list[float] = []
    deposits: list[tuple[date, float]] = []
    for d in days:
        if d in month_starts:
            waiting += rules.monthly
            deposits.append((d, rules.monthly))
        price = close(d)
        if price:
            last = price
            if waiting > 0:
                units += waiting * (1 - rules.cost_rate) / price
                waiting = 0.0
        value.append(units * (last or 0.0) + waiting)
        cash.append(waiting)
    return SimResult(days=list(days), value=value, cash=cash, deposits=deposits, trades=[], flags=[])
