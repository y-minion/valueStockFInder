"""백테스트 시세 창고: 거래일, 주식·ETF·지수 종가, 달마다 첫 거래일의 KRX 종목 목록 (2026-11-24 백테스트 설계 4·5·7장).

KrxClient가 지난 날 시세를 저장소에 저장해서, 한 번 받은 날은 다시 묻지 않아요.
주식 시세가 없는 평일(휴장일)은 KrxClient가 저장하지 않아서, 여기서 meta로 기억해요.
"""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Iterator
from datetime import date, timedelta

from vsf.data.http import NetworkError
from vsf.data.krx import KrxError, Listed
from vsf.data.store import PriceRow, Store

PAUSED = ("KRX 자료를 받다가 멈췄어요 ({error}). 받은 자료는 저장했으니, 내일 다시 `uv run backtest.py`를 "
          "실행하면 이어서 받아요.")
PROGRESS_EVERY = 100


class MarketPaused(Exception):
    """KRX 하루 한도 등으로 자료 받기를 멈췄어요. 메시지는 한국어예요."""


def _holiday_key(d: date) -> str:
    return f"bt:holiday:{d.strftime('%Y%m%d')}"


class Market:
    def __init__(self, krx, store: Store, start: date, end: date, today: date | None = None) -> None:
        """today: 이날과 그 뒤는 시세가 비어도 휴장일로 기억하지 않아요 (아직 안 올라온 날일 수 있어요)."""
        self.krx = krx
        self._store = store
        self.start, self.end = start, end
        self._today = today or date.today()
        self._days: list[date] | None = None
        self._listings: dict[date, list[Listed]] = {}

    def _weekdays(self) -> Iterator[date]:
        d = self.start
        while d <= self.end:
            if d.weekday() < 5:
                yield d
            d += timedelta(days=1)

    def _trades(self, d: date) -> bool:
        if self._store.get_meta(_holiday_key(d)) == "1":
            return False
        if self.krx.daily(d):
            return True
        if d < self._today:
            self._store.set_meta(_holiday_key(d), "1")
        return False

    def trading_days(self) -> list[date]:
        """주식 시세가 있는 날. 주말은 묻지 않아요."""
        if self._days is None:
            self._days = [d for d in self._weekdays() if self._trades(d)]
        return self._days

    def month_starts(self) -> list[date]:
        out: list[date] = []
        for d in self.trading_days():
            if not out or (d.year, d.month) != (out[-1].year, out[-1].month):
                out.append(d)
        return out

    def first_trading_day_on_or_after(self, d: date) -> date | None:
        days = self.trading_days()
        i = bisect_left(days, d)
        return days[i] if i < len(days) else None

    def stocks(self, day: date) -> dict[str, PriceRow]:
        return self.krx.daily(day)

    def etf_close(self, day: date, code: str) -> float | None:
        return self.krx.etf_daily(day).get(code)

    def index_close(self, day: date, name: str) -> float | None:
        return self.krx.index_daily(day).get(name)

    def listing(self, day: date) -> list[Listed]:
        """그 달 첫 거래일의 KRX 종목 목록이에요 (그때 상장돼 있다가 나중에 사라진 종목도 들어 있어요)."""
        starts = [d for d in self.month_starts() if (d.year, d.month) == (day.year, day.month) and d <= day]
        first = starts[0] if starts else day
        if first not in self._listings:
            self._listings[first] = self.krx.listed(first)
        return self._listings[first]

    def download(self, progress: Callable[[str], None] = print) -> None:
        """기간의 모든 거래일 주식·ETF·지수 시세와 달마다 첫 거래일 종목 목록을 받아 둬요."""
        try:
            days = self.trading_days()
            for i, d in enumerate(days, 1):
                self.krx.etf_daily(d)
                self.krx.index_daily(d)
                if i % PROGRESS_EVERY == 0 or i == len(days):
                    progress(f"KRX 시세 {i}/{len(days)} 거래일")
            for d in self.month_starts():
                self.listing(d)
        except (KrxError, NetworkError) as e:
            raise MarketPaused(PAUSED.format(error=e)) from None
