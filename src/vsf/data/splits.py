"""액면분할·무상증자 감지와 조정 (순수 함수)."""
from dataclasses import dataclass

SPLIT_LIKE = 1.5
SPLIT_PRICE_BAND = (0.5, 2.0)   # 분할이면 주가도 주식 수 배수만큼 움직여요
SPLIT_FLAG = "주식 수가 크게 바뀐 해가 있어요(액면분할·무상증자 가능성). 옛날 EPS·DPS를 확인해 주세요."
RESTATE_FLAG = "같은 해 EPS가 보고서마다 달라요(정정·재작성 가능성). EPS를 확인해 주세요."


def is_split_like(ratio: float | None) -> bool:
    if ratio is None:
        return False
    return ratio >= SPLIT_LIKE or ratio <= 1 / SPLIT_LIKE


def close_factor(shares_then: float | None, shares_now: float | None) -> float:
    if not shares_then or not shares_now:
        return 1.0
    if is_split_like(shares_now / shares_then):
        return shares_then / shares_now
    return 1.0


def confirmed_split(shares_then: float | None, shares_now: float | None,
                    close_then: float | None, close_now: float | None) -> float | None:
    """그때와 지금 사이에 액면분할·무상증자가 있었다고 확인되면 주식 수 배수 r, 아니면 None.

    주식 수가 분할 모양으로 바뀌었고(r), 주가도 그만큼 움직였을 때만 확인해요:
    q = (그때 종가 ÷ 지금 종가) ÷ r 이 SPLIT_PRICE_BAND 안이어야 해요. 유상증자는 주가가 r만큼 움직이지 않아요.
    """
    if not shares_then or not shares_now or not close_then or not close_now:
        return None
    r = shares_now / shares_then
    if not is_split_like(r):
        return None
    low, high = SPLIT_PRICE_BAND
    return r if low <= (close_then / close_now) / r <= high else None


def overlap_ratio(newer: float | None, older: float | None) -> float | None:
    if not newer or not older or (newer > 0) != (older > 0):
        return None
    return older / newer


@dataclass(frozen=True)
class SplitCheck:
    eps_divisor_older: float
    flags: tuple[str, ...]


def _share_ratio(shares: dict[int, float | None], now_year: int, then_year: int) -> float | None:
    now, then = shares.get(now_year), shares.get(then_year)
    if not now or not then:
        return None
    return now / then


def check_splits(
    eps_newer_at_overlap: float | None,
    eps_older_at_overlap: float | None,
    shares_by_year: dict[int, float | None],
    latest_year: int,
) -> SplitCheck:
    divisor = 1.0
    flags: list[str] = []

    r = overlap_ratio(eps_newer_at_overlap, eps_older_at_overlap)
    if r is not None and abs(r - 1) > 0.02:
        s = _share_ratio(shares_by_year, latest_year, latest_year - 2)
        if is_split_like(r) and s is not None and abs(s / r - 1) <= 0.10:
            divisor = r
        else:
            # 확인할 수 없거나 맞지 않으면 숫자를 바꾸지 않고 표시만 해요.
            flags.append(RESTATE_FLAG)

    for y in shares_by_year:
        if is_split_like(_share_ratio(shares_by_year, latest_year, y)):
            flags.append(SPLIT_FLAG)
            break

    return SplitCheck(divisor, tuple(flags))
