"""엑셀 함수와 같은 결과를 내는 작은 도우미."""
from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def _quant(x: float, digits: int) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def excel_round(x: float, digits: int) -> float:
    """엑셀 ROUND: 반쪽은 0에서 먼 쪽으로."""
    return float(_quant(x, digits))


_NUMBER_FORMATS = {
    "0": (0, False), "0.0": (1, False), "0.00": (2, False),
    "#,##0": (0, True), "#,##0.0": (1, True),
}


def excel_text(x: float | date, fmt: str) -> str:
    """엑셀 TEXT. 지원 형식만 받고 나머지는 ValueError."""
    if fmt == "yyyy-mm-dd":
        if not isinstance(x, date):
            raise ValueError("날짜 형식에는 날짜가 필요해요")
        return x.strftime("%Y-%m-%d")
    if fmt == "0%":
        return f"{_quant(float(Decimal(repr(x)) * 100), 0):f}%"
    if fmt not in _NUMBER_FORMATS:
        raise ValueError(f"지원하지 않는 형식이에요: {fmt}")
    digits, comma = _NUMBER_FORMATS[fmt]
    d = _quant(x, digits)
    return f"{d:,f}" if comma else f"{d:f}"


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def count(vals: Iterable) -> int:
    return sum(1 for v in vals if is_num(v))


def average(vals: Iterable) -> float | None:
    nums = [v for v in vals if is_num(v)]
    return sum(nums) / len(nums) if nums else None
