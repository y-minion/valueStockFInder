"""백테스트 수익률 계산 (2026-11-24 백테스트 설계 6장)."""
from __future__ import annotations

from datetime import date

_LOW, _HIGH = -0.99, 10.0


def _npv(flows: list[tuple[date, float]], r: float) -> float:
    t0 = flows[0][0]
    return sum(cf / (1 + r) ** ((d - t0).days / 365) for d, cf in flows)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """돈을 넣은 날을 반영한 연 수익률. 입금은 음수, 끝날 평가액은 양수예요.

    −99% ~ +1000% 사이를 반씩 좁혀 찾아요. 흐름의 부호가 한쪽뿐이거나 그 사이에 답이 없으면 None이에요.
    """
    flows = sorted((d, cf) for d, cf in flows if cf)
    if not flows or all(cf > 0 for _, cf in flows) or all(cf < 0 for _, cf in flows):
        return None
    lo, hi = _LOW, _HIGH
    f_lo, f_hi = _npv(flows, lo), _npv(flows, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _npv(flows, mid)
        if f_mid == 0 or hi - lo < 1e-12:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def unit_values(value: list[float], deposits_by_day: list[float]) -> list[float]:
    """입금을 뺀 시간가중 지수예요. 첫 입금일이 1.0이고, 그 전날까지도 1.0이에요.

    그날 수익률 = (그날 평가액 − 그날 입금) ÷ 전날 평가액 − 1 (입금은 그날 아침에 들어온다고 봐요).
    """
    out: list[float] = []
    index, prev = 1.0, 0.0
    for v, dep in zip(value, deposits_by_day, strict=True):
        if prev > 0:
            index *= (v - dep) / prev
        out.append(index)
        prev = v
    return out


def max_drawdown(days: list[date], units: list[float]) -> tuple[float, date | None]:
    """가장 크게 빠졌던 비율(음수)과 그 바닥 날. 한 번도 빠지지 않았으면 (0.0, None)."""
    peak, worst, bottom = 0.0, 0.0, None
    for d, u in zip(days, units, strict=True):
        peak = max(peak, u)
        if peak > 0 and u / peak - 1 < worst:
            worst, bottom = u / peak - 1, d
    return worst, bottom


def yearly_returns(days: list[date], units: list[float]) -> dict[int, float]:
    """해마다 수익률 (시간가중). 첫해·끝해는 시작·끝 날까지만이에요."""
    out: dict[int, float] = {}
    start = units[0] if units else None
    last_of: dict[int, float] = {}
    for d, u in zip(days, units, strict=True):
        last_of[d.year] = u
    for year in sorted(last_of):
        if start:
            out[year] = last_of[year] / start - 1
        start = last_of[year]
    return out


def cash_share(value: list[float], cash: list[float]) -> float:
    """평가액이 0보다 큰 날마다 현금(CMA) 비중의 평균."""
    shares = [c / v for v, c in zip(value, cash, strict=True) if v > 0]
    return sum(shares) / len(shares) if shares else 0.0
