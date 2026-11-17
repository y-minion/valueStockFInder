from vsf.data.splits import (
    RESTATE_FLAG, SPLIT_FLAG, SplitCheck, check_splits, close_factor,
    is_split_like, overlap_ratio,
)


def test_no_split():
    assert check_splits(100, 100, {2021: 10, 2022: 10, 2023: 10, 2024: 10, 2025: 10}, 2025) == SplitCheck(1.0, ())


def test_two_for_one_split_last_year():
    c = check_splits(50, 100, {2023: 10, 2024: 20, 2025: 20}, 2025)
    assert c.eps_divisor_older == 2.0 and SPLIT_FLAG in c.flags


def test_big_issuance_is_flag_only():
    c = check_splits(100, 100, {2023: 10, 2025: 16}, 2025)
    assert c.eps_divisor_older == 1.0 and c.flags == (SPLIT_FLAG,)


def test_restatement_flag():
    c = check_splits(100, 105, {2023: 10, 2025: 10}, 2025)
    assert c.eps_divisor_older == 1.0 and c.flags == (RESTATE_FLAG,)


def test_close_factor():
    assert close_factor(10, 20) == 0.5 and close_factor(10, 11) == 1.0 and close_factor(None, 20) == 1.0


def test_split_like_ratio_without_share_data_is_flagged_not_applied():
    for shares in ({}, {2023: None, 2025: 20}, {2023: 10, 2025: None}, {2023: 0, 2025: 20}):
        c = check_splits(50, 100, shares, 2025)
        assert c.eps_divisor_older == 1.0 and RESTATE_FLAG in c.flags


def test_split_like_ratio_with_mismatched_shares_is_flagged_not_applied():
    c = check_splits(50, 100, {2023: 10, 2025: 10}, 2025)
    assert c.eps_divisor_older == 1.0 and c.flags == (RESTATE_FLAG,)


def test_flag_order_and_no_duplicates():
    c = check_splits(100, 105, {2023: 10, 2024: 5, 2025: 20}, 2025)
    assert c.flags == (RESTATE_FLAG, SPLIT_FLAG)


def test_helpers():
    assert is_split_like(1.5) and is_split_like(1 / 1.5) and not is_split_like(1.2) and not is_split_like(None)
    assert overlap_ratio(50, 100) == 2.0
    assert overlap_ratio(0, 100) is None and overlap_ratio(None, 1) is None and overlap_ratio(-1, 1) is None


def test_confirmed_split_after_latest_year():
    from vsf.data.splits import confirmed_split
    # 10:1 액면분할: 주식 수 ×10, 주가 ÷10 → 확인돼요 (q = (100,000 / 10,000) / 10 = 1)
    assert confirmed_split(100, 1000, 100_000, 10_000) == 10.0
    assert confirmed_split(100, 1000, 100_000, 19_000) == 10.0           # q = 0.53, 0.5–2 안이에요
    assert confirmed_split(1000, 100, 10_000, 100_000) == 0.1            # 주식 병합도 같아요
    # 유상증자: 주식 수는 늘었는데 주가는 그대로 → q = 0.1이라 확인 안 돼요
    assert confirmed_split(100, 1000, 100_000, 100_000) is None
    assert confirmed_split(100, 1000, 100_000, 21_000) is None           # q = 0.48
    assert confirmed_split(100, 120, 100_000, 83_000) is None            # 1.2배는 분할 모양이 아니에요
    for args in ((None, 1000, 1, 1), (100, None, 1, 1), (100, 1000, None, 1), (100, 1000, 1, None),
                 (0, 1000, 1, 1), (100, 1000, 1, 0)):
        assert confirmed_split(*args) is None


def test_confirmed_split_needs_price_closer_to_r_than_to_unchanged():
    from vsf.data.splits import confirmed_split
    # 주가가 그대로면 q = 1/r. r이 1.5–2면 [0.5, 2] 안이라도 분할로 보지 않아요 (|ln q| < |ln r| / 2).
    assert confirmed_split(100, 150, 100_000, 100_000) is None
    assert confirmed_split(100, 200, 100_000, 100_000) is None
    assert confirmed_split(100, 151.2, 2965, 3050) is None            # 한온시스템 018880: 유상증자
    assert confirmed_split(100, 150, 150_000, 100_000) == 1.5         # 주가도 ÷1.5
    assert confirmed_split(100, 150, 120_000, 100_000) is None        # q = 0.8: 1.5 쪽보다 '그대로' 쪽에 가까워요
    assert confirmed_split(100, 150, 125_000, 100_000) == 1.5         # q ≈ 0.83
    assert confirmed_split(100, 1000, 100_000, 19_000) == 10.0        # r = 10은 [0.5, 2] 그대로
