"""거래 적음 확인: 최근 주말 거래일의 거래대금 평균 (우선주 설계 7장)."""
from datetime import date

from vsf.data.store import PriceRow
from vsf.liquidity import THIN_TRADING_WON, average_value


class Krx:
    def __init__(self, days):
        self.days = days            # {date: {code: value}}
        self.asked = []

    def week_ends(self, until, weeks=52):
        """진짜 KrxClient.week_ends처럼 until이 거래일이면 until도 마지막에 들어 있어요."""
        return sorted(d for d in self.days if d <= until)[-weeks:]

    def daily(self, day, need_value=False):
        self.asked.append((day, need_value))
        return {c: PriceRow(day, c, c, "KOSPI", 1.0, 1.0, v) for c, v in self.days.get(day, {}).items()}


def test_average_over_week_ends_and_the_base_day():
    days = {date(2026, 11, 6): {"A": 100.0, "B": None}, date(2026, 11, 13): {"A": 300.0},
            date(2026, 11, 20): {"A": 200.0, "B": 50.0}}
    k = Krx(days)
    got = average_value(k, {"A", "B", "Z"}, date(2026, 11, 20), weeks=13)
    assert got == {"A": (200.0, 3), "B": (50.0, 1)}                     # 값이 없는 날은 빼요, 없는 종목은 결과에 없어요
    assert [d for d, _ in k.asked].count(date(2026, 11, 20)) == 1      # 기준일은 한 번만 세요
    assert all(need for _, need in k.asked)


def test_threshold_is_one_hundred_million_won():
    assert THIN_TRADING_WON == 100_000_000
