"""백테스트 시뮬레이션 (2026-11-24 백테스트 설계 3장).

매 거래일 종가로 이 순서대로 처리해요: CMA 이자 → 입금 → 배당 → 팔기 → 사기 → 평가.
살 때는 한 종목이 전체 평가액의 max_weight를 넘지 않게 하고, 20일 평균 거래대금이 기준보다 적은 종목은 사지 않아요.
판정은 회사×사업연도 판정 묶음(Vintage)에서 그날 쓸 수 있는 마지막 묶음만 봐요 (valid_from ≤ 그날).
자료(DART·KRX)는 부르지 않는 순수 계산이라, 시세와 묶음을 넘겨주면 돼요.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

from vsf.backtest.model import Verdict, Vintage
from vsf.data.splits import confirmed_split
from vsf.data.store import PriceRow

SOLD_FAIR = "적정가 도달"
SOLD_UNCOMPUTABLE = "적정가 계산 불가"
SOLD_DELISTED = "상장폐지"
SOLD_GATES = "관문 ①② 탈락"
HOLDING = "보유 중"
FLAG_NO_FAIR = "적정가를 구하지 못해 들고 있어요"
FLAG_GATES = "산 뒤 관문 ①② 탈락으로 바뀌었어요"
FLAG_DROP = "하루에 40% 넘게 떨어졌어요(분할·합병 확인 필요)"
DROP_RATIO = 0.6
LIQUIDITY_DAYS = 20       # 거래대금 평균을 내는 거래일 수


@dataclass(frozen=True)
class Rules:
    monthly: float
    max_holdings: int
    cost_rate: float
    min_trade: float
    max_weight: float = 1.0           # 살 때 한 종목이 전체 평가액에서 넘지 않을 비중 (1이면 제한 없음)
    min_trading_value: float = 0.0    # 20일 평균 거래대금이 이보다 적으면 사지 않아요 (0이면 보지 않음)
    sell_on_gate_fail: bool = False   # 산 뒤 관문 ①②가 탈락으로 바뀌면 팔아요


@dataclass(frozen=True)
class Trade:
    code: str
    name: str
    first_buy: date
    last_buy: date
    invested: float           # 비용 포함 넣은 돈
    shares: float
    sell_date: date | None
    sell_price: float | None
    proceeds: float | None    # 비용 뺀 판 돈
    dividends: float
    reason: str               # "적정가 도달" | "적정가 계산 불가" | "상장폐지" | "보유 중"
    basis: str                # 첫 매수 날의 판정 근거
    flags: tuple[str, ...]


@dataclass(frozen=True)
class SimResult:
    days: list[date]
    value: list[float]        # 날마다 평가액 (CMA 포함)
    cash: list[float]
    deposits: list[tuple[date, float]]
    trades: list[Trade]       # 판 것 + 끝날 보유 중인 것("보유 중")
    flags: list[str]


@dataclass
class _Position:
    code: str
    name: str
    corp: str
    first_buy: date
    basis: str
    shares: float = 0.0
    invested: float = 0.0
    last_buy: date | None = None
    dividends: float = 0.0
    last_close: float | None = None
    flags: list[str] = field(default_factory=list)

    def flag(self, text: str) -> None:
        if text not in self.flags:
            self.flags.append(text)

    def closed(self, day: date | None, price: float | None, proceeds: float | None, reason: str) -> Trade:
        return Trade(code=self.code, name=self.name, first_buy=self.first_buy, last_buy=self.last_buy or self.first_buy,
                     invested=self.invested, shares=self.shares, sell_date=day, sell_price=price, proceeds=proceeds,
                     dividends=self.dividends, reason=reason, basis=self.basis, flags=tuple(self.flags))


def _basis(v: Vintage, verdict: Verdict, fair: float, buy: float) -> str:
    text = f"{v.year} 사업보고서 · {verdict.method} · 적정가 {fair:,.0f}원 · 매수선 {buy:,.0f}원"
    return text + (" · 금융회사 대체 자료" if v.substitute else "")


def _allocate(cash: float, rooms: list[float]) -> list[float]:
    """cash를 대상마다 똑같이 나누되 대상마다 자리(room)를 넘지 않게. 자리에 닿고 남은 돈은 자리가 남은 대상에 다시 나눠요."""
    give = [0.0] * len(rooms)
    left, open_ = cash, [i for i, room in enumerate(rooms) if room > 0]
    while left > 1e-9 and open_:
        share = left / len(open_)
        still = []
        for i in open_:
            add = min(share, rooms[i] - give[i])
            give[i] += add
            left -= add
            if rooms[i] - give[i] > 1e-9:
                still.append(i)
        if len(still) == len(open_):
            break
        open_ = still
    return give


class _Book:
    """코드마다 valid_from 순 묶음. 그날 쓸 수 있는 마지막 묶음을 찾아요."""

    def __init__(self, vintages: dict[str, list[Vintage]]) -> None:
        self._by_code = {c: sorted(vs, key=lambda v: v.valid_from) for c, vs in vintages.items() if vs}
        self._starts = {c: [v.valid_from for v in vs] for c, vs in self._by_code.items()}

    def codes(self) -> list[str]:
        return sorted(self._by_code)

    def active(self, code: str, day: date) -> Vintage | None:
        starts = self._starts.get(code)
        if not starts:
            return None
        i = bisect_right(starts, day) - 1
        return self._by_code[code][i] if i >= 0 else None


class _Sim:
    def __init__(self, stocks: Callable[[date], dict[str, PriceRow]], vintages: dict[str, list[Vintage]],
                 variant: str, rules: Rules, cma_growth: Callable[[date, date], float],
                 listed: Callable[[date], set[str]], month_starts: set[date], year_ends: set[date]) -> None:
        self.stocks, self.variant, self.rules = stocks, variant, rules
        self.cma_growth, self.listed, self.month_starts = cma_growth, listed, month_starts
        self.year_ends = year_ends
        self.book = _Book(vintages)
        self.tracked = set(self.book.codes())
        self.splits: dict[str, list[tuple[date, float]]] = {}      # 코드 → [(분할 확인한 날, 주식 수 배수)]
        self.last_rows: dict[str, PriceRow] = {}                  # 코드 → 마지막으로 본 시세
        self.pending: dict[tuple[str, int], tuple[float, date, date]] = {}   # (코드, 결산 해) → (주식 수, 그날, 첫 매수일)
        self.cash = 0.0
        self.positions: dict[str, _Position] = {}
        self.trades: list[Trade] = []
        self.deposits: list[tuple[date, float]] = []
        self.flags: list[str] = []
        self.recent: deque[dict[str, PriceRow]] = deque(maxlen=LIQUIDITY_DAYS)   # 최근 거래일 시세 (거래대금 평균용)

    # ---- 판정 ----

    def _verdict(self, code: str, day: date) -> tuple[Vintage, Verdict] | None:
        v = self.book.active(code, day)
        return None if v is None or self.variant not in v.verdicts else (v, v.verdicts[self.variant])

    def _levels(self, code: str, v: Vintage, verdict: Verdict) -> tuple[float | None, float | None]:
        """그 묶음의 적정가·매수선 (분할 맞춤은 _scale)."""
        k = self._scale(code, v)
        fair = None if verdict.fair is None else verdict.fair / k
        buy = None if verdict.buy_line is None else verdict.buy_line / k
        return fair, buy

    def _scale(self, code: str, v: Vintage) -> float:
        """묶음 시작(valid_from) 뒤에 확인한 분할 배수의 곱. 적정가·매수선을 이 값으로 나눠요."""
        k = 1.0
        for day, r in self.splits.get(code, ()):
            if day > v.valid_from:
                k *= r
        return k

    def _split_between(self, code: str, after: date, upto: date) -> float:
        k = 1.0
        for day, r in self.splits.get(code, ()):
            if after < day <= upto:
                k *= r
        return k

    def _track_splits(self, day: date, prices: dict[str, PriceRow]) -> None:
        """전에 본 시세와 오늘 시세로 분할·무상증자를 확인해요. 보유 종목은 주식 수를 같은 배수로 늘려요."""
        for code in self.tracked | set(self.positions):
            row, before = prices.get(code), self.last_rows.get(code)
            if row is None or row.close is None or before is None or before.close is None:
                continue
            r = confirmed_split(before.shares, row.shares, before.close, row.close)
            pos = self.positions.get(code)
            if r is not None:
                self.splits.setdefault(code, []).append((day, r))
                if pos is not None:
                    pos.shares *= r
            elif pos is not None and row.close / before.close < DROP_RATIO:
                pos.flag(FLAG_DROP)

    def _dividends(self, day: date) -> None:
        """결산일에 들고 있던 주식 수 × 그해 DPS를, 그해 사업보고서 묶음이 쓰이기 시작한 날 받아요."""
        for (code, year), (shares, snap_day, first_buy) in list(self.pending.items()):
            v = self.book.active(code, day)
            if v is None or v.year < year:
                continue
            del self.pending[(code, year)]
            if v.year > year or not v.dps:
                continue
            amount = shares * self._split_between(code, snap_day, v.valid_from) * v.dps
            self.cash += amount
            pos = self.positions.get(code)
            if pos is not None and pos.first_buy == first_buy:
                pos.dividends += amount
                continue
            for i in range(len(self.trades) - 1, -1, -1):
                t = self.trades[i]
                if t.code == code and t.first_buy == first_buy:
                    self.trades[i] = replace(t, dividends=t.dividends + amount)
                    break

    def _delist(self, day: date) -> None:
        """달 첫 거래일에 KRX 목록에 없는 보유 종목은 마지막 종가에 판 걸로 봐요."""
        if day not in self.month_starts or not self.positions:
            return
        listed = self.listed(day)
        for code in sorted(self.positions):
            pos = self.positions[code]
            if code not in listed and pos.last_close is not None:
                self._close(pos, day, pos.last_close, SOLD_DELISTED)

    # ---- 하루 ----

    def day(self, prev: date | None, day: date) -> None:
        if prev is not None:
            self.cash *= self.cma_growth(prev, day)
        if day in self.month_starts:
            self.cash += self.rules.monthly
            self.deposits.append((day, self.rules.monthly))
        prices = self.stocks(day)
        self.recent.append(prices)
        self._track_splits(day, prices)
        self._dividends(day)
        self._delist(day)
        self._sell(day, prices)
        self._buy(day, prices)
        if day in self.year_ends:
            for code, pos in self.positions.items():
                self.pending[(code, day.year)] = (pos.shares, day, pos.first_buy)
        self.last_rows.update(prices)

    def _sell(self, day: date, prices: dict[str, PriceRow]) -> None:
        for code in sorted(self.positions):
            pos = self.positions[code]
            row = prices.get(code)
            if row is None or row.close is None:
                continue                                    # 거래정지: 마지막 종가로 평가만 해요
            pos.last_close = row.close
            found = self._verdict(code, day)
            if found is None:
                continue
            v, verdict = found
            failed = verdict.gate1 == "탈락" or verdict.gate2 == "탈락"
            if failed:
                pos.flag(FLAG_GATES)
            fair, _ = self._levels(code, v, verdict)
            if verdict.uncomputable:
                self._close(pos, day, row.close, SOLD_UNCOMPUTABLE)
            elif failed and self.rules.sell_on_gate_fail:
                self._close(pos, day, row.close, SOLD_GATES)
            elif fair is None:
                pos.flag(FLAG_NO_FAIR)
            elif row.close >= fair:
                self._close(pos, day, row.close, SOLD_FAIR)

    def _close(self, pos: _Position, day: date, price: float, reason: str) -> None:
        proceeds = pos.shares * price * (1 - self.rules.cost_rate)
        self.cash += proceeds
        self.trades.append(pos.closed(day, price, proceeds, reason))
        del self.positions[pos.code]

    def _candidates(self, day: date, prices: dict[str, PriceRow]) -> list[tuple[float, str, Vintage, Verdict, float, float]]:
        """(종가÷적정가, 코드, 묶음, 판정, 적정가, 매수선) — 그날 매수선 이하인 종목."""
        out = []
        for code in self.book.codes():
            row = prices.get(code)
            if row is None or row.close is None:
                continue
            found = self._verdict(code, day)
            if found is None or not found[1].cheap_ok() or found[0].blocked or not self._liquid(code):
                continue
            v, verdict = found
            fair, buy = self._levels(code, v, verdict)
            if fair is None or buy is None or fair <= 0 or row.close > buy:
                continue
            out.append((row.close / fair, code, v, verdict, fair, buy))
        out.sort(key=lambda c: (c[0], c[1]))
        return out

    def _liquid(self, code: str) -> bool:
        """최근 LIQUIDITY_DAYS 거래일 평균 거래대금이 기준 이상인지. 거래대금이 있는 날만 평균해요 (모르면 사지 않아요)."""
        if self.rules.min_trading_value <= 0:
            return True
        values = [p[code].value for p in self.recent if code in p and p[code].value is not None]
        return bool(values) and sum(values) / len(values) >= self.rules.min_trading_value

    def _buy(self, day: date, prices: dict[str, PriceRow]) -> None:
        if self.cash < self.rules.min_trade:
            return
        cands = self._candidates(day, prices)
        if not cands:
            return
        held_corps = {p.corp for p in self.positions.values()}
        targets: list[tuple[str, Vintage, Verdict, float, float]] = []
        for _, code, v, verdict, fair, buy in cands:
            if code in self.positions:
                targets.append((code, v, verdict, fair, buy))
        slots = self.rules.max_holdings - len(self.positions)
        for _, code, v, verdict, fair, buy in cands:
            if slots <= 0:
                break
            if code in self.positions or v.corp_code in held_corps:
                continue
            targets.append((code, v, verdict, fair, buy))
            held_corps.add(v.corp_code)
            slots -= 1
        if not targets:
            return
        total = self.value()
        rooms = []
        for code, *_ in targets:
            pos = self.positions.get(code)
            held = pos.shares * prices[code].close if pos is not None else 0.0
            rooms.append(max(0.0, self.rules.max_weight * total - held))
        for (code, v, verdict, fair, buy), amount in zip(targets, _allocate(self.cash, rooms), strict=True):
            if amount < self.rules.min_trade:
                continue
            close = prices[code].close
            pos = self.positions.get(code)
            if pos is None:
                pos = self.positions[code] = _Position(code=code, name=v.name, corp=v.corp_code, first_buy=day,
                                                       basis=_basis(v, verdict, fair, buy))
            pos.shares += amount * (1 - self.rules.cost_rate) / close
            pos.invested += amount
            pos.last_buy = day
            pos.last_close = close
            self.cash -= amount
        if abs(self.cash) < 1e-6:
            self.cash = 0.0

    def value(self) -> float:
        return self.cash + sum(p.shares * (p.last_close or 0.0) for p in self.positions.values())

    def finish(self) -> list[Trade]:
        held = [p.closed(None, None, None, HOLDING) for p in sorted(self.positions.values(), key=lambda p: p.code)]
        return self.trades + held


def simulate(days: list[date], stocks: Callable[[date], dict[str, PriceRow]], vintages: dict[str, list[Vintage]],
             variant: str, rules: Rules, cma_growth: Callable[[date, date], float],
             listed: Callable[[date], set[str]], month_starts: set[date]) -> SimResult:
    """매 거래일 투자 규칙대로 사고팔아요. days는 거래일 오름차순, month_starts는 입금하는 날이에요."""
    year_ends = {d for d, nxt in zip(days, days[1:]) if nxt.year != d.year}      # 해마다 마지막 거래일 (결산일)
    sim = _Sim(stocks, vintages, variant, rules, cma_growth, listed, month_starts, year_ends)
    value: list[float] = []
    cash: list[float] = []
    prev: date | None = None
    for day in days:
        sim.day(prev, day)
        value.append(sim.value())
        cash.append(sim.cash)
        prev = day
    return SimResult(days=list(days), value=value, cash=cash, deposits=sim.deposits, trades=sim.finish(),
                     flags=sim.flags)
