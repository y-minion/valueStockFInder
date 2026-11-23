"""거래 적음 확인: 최근 주말 거래일의 거래대금 평균 (우선주 설계 7장). 표시만 하고 판정은 안 바꿔요."""
from datetime import date

THIN_TRADING_WON = 100_000_000      # 평균 거래대금이 이보다 적으면 '거래 적음' (내 판단, 2026-11-24)


def average_value(krx, codes: set[str], until: date, weeks: int = 13) -> dict[str, tuple[float, int]]:
    """종목 → (거래대금 평균, 날 수). 최근 weeks주의 주말 거래일과 until 당일을 봐요. 값이 없는 날은 빼요."""
    sums: dict[str, list[float]] = {}
    for day in [*krx.week_ends(until, weeks), until]:
        rows = krx.daily(day, need_value=True)
        for code in codes:
            row = rows.get(code)
            if row is not None and row.value is not None:
                sums.setdefault(code, []).append(row.value)
    return {code: (sum(v) / len(v), len(v)) for code, v in sums.items()}
