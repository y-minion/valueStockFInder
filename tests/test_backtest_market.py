"""백테스트: 시세 창고 (거래일·주식·ETF·지수·달별 종목 목록)."""
from datetime import date, timedelta

import pytest
from fakes import FakeKrx, _listed, mem_store
from vsf.backtest.market import Market, MarketPaused
from vsf.data.krx import KrxError
from vsf.data.store import PriceRow

ITEM = _listed("000270", "기아")
TODAY = date(2026, 11, 24)


def _weekday_rows(start: date, end: date, holidays=()) -> dict[date, dict[str, PriceRow]]:
    out = {}
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            out[d] = {"000270": PriceRow(d, "000270", "기아", "KOSPI", 50000.0, 4e8)}
        d += timedelta(days=1)
    return out


def _market(krx, store, start=date(2019, 12, 30), end=date(2020, 2, 7)):
    return Market(krx, store, start, end, today=TODAY)


def test_weekends_are_not_requested_and_holidays_are_remembered():
    store = mem_store()
    days = _weekday_rows(date(2019, 12, 30), date(2020, 2, 7), holidays={date(2020, 1, 1)})
    first = FakeKrx([ITEM], days)
    got = _market(first, store).trading_days()
    assert date(2020, 1, 1) not in got and date(2020, 1, 2) in got
    assert all(d.weekday() < 5 for d, in first._log["daily"])               # 주말은 묻지 않아요
    again = FakeKrx([ITEM], days)
    assert _market(again, store).trading_days() == got
    assert (date(2020, 1, 1),) not in again._log["daily"]                   # 휴장일은 기억해서 다시 묻지 않아요


def test_today_and_later_are_never_marked_as_holidays():
    store = mem_store()
    krx = FakeKrx([ITEM], {})
    Market(krx, store, date(2026, 11, 23), date(2026, 11, 24), today=date(2026, 11, 24)).trading_days()
    assert store.get_meta("bt:holiday:20261124") is None and store.get_meta("bt:holiday:20261123") == "1"


def test_month_starts_skip_holidays():
    days = _weekday_rows(date(2019, 12, 30), date(2020, 2, 7), holidays={date(2020, 1, 1)})
    m = _market(FakeKrx([ITEM], days), mem_store())
    assert m.month_starts() == [date(2019, 12, 30), date(2020, 1, 2), date(2020, 2, 3)]


def test_first_trading_day_on_or_after():
    m = _market(FakeKrx([ITEM], _weekday_rows(date(2019, 12, 30), date(2020, 2, 7))), mem_store())
    assert m.first_trading_day_on_or_after(date(2020, 1, 4)) == date(2020, 1, 6)       # 토요일 → 월요일
    assert m.first_trading_day_on_or_after(date(2020, 1, 6)) == date(2020, 1, 6)
    assert m.first_trading_day_on_or_after(date(2020, 3, 1)) is None                   # 기간 뒤
    assert m.first_trading_day_on_or_after(date(2019, 1, 1)) == date(2019, 12, 30)


def test_etf_index_stock_and_listing_lookup():
    d = date(2020, 1, 2)
    krx = FakeKrx([ITEM], _weekday_rows(date(2019, 12, 30), date(2020, 2, 7), holidays={date(2020, 1, 1)}),
                  etf={d: {"133690": 31880.0}}, index={d: {"코스피": 2175.17}})
    m = _market(krx, mem_store())
    assert m.etf_close(d, "133690") == 31880.0 and m.etf_close(d, "999999") is None
    assert m.index_close(d, "코스피") == 2175.17 and m.index_close(date(2020, 1, 3), "코스피") is None
    assert m.stocks(d)["000270"].close == 50000.0
    assert [x.code for x in m.listing(date(2020, 1, 15))] == ["000270"]
    assert (date(2020, 1, 2),) in krx._log["listed"]                           # 그 달 첫 거래일 목록


class _BrokenKrx(FakeKrx):
    def etf_daily(self, day):
        raise KrxError("KRX OPEN API 'ETF 일별매매정보' 요청이 거절됐어요 (HTTP 429)")


def test_krx_error_pauses_download_with_korean_message():
    m = _market(_BrokenKrx([ITEM], _weekday_rows(date(2019, 12, 30), date(2020, 2, 7))), mem_store())
    with pytest.raises(MarketPaused, match="내일 다시"):
        m.download(progress=lambda s: None)
