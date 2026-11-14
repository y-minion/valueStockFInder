"""액면분할·무상증자 감지와 조정 (순수 함수)."""
from dataclasses import dataclass

SPLIT_LIKE = 1.5
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
