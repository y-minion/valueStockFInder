"""엔진·정답 자료가 같이 쓰는 사례 17개. 예시 두 종목은 엑셀 예시 시트의 노란 칸 값이에요."""
from dataclasses import replace
from datetime import date

from vsf.model import Criteria, Gate4Inputs, StockInputs, YearRow

_COLUMNS = ("year", "eps", "per", "dps", "roe", "debt_ratio", "interest_coverage",
            "net_income", "ocf", "capex", "dividends_paid")


def rows(**cols) -> tuple[YearRow, ...]:
    """열별 튜플(길이 5)로 YearRow 5개를 만들어요. 안 준 열은 None이에요."""
    return tuple(
        YearRow(**{name: cols[name][i] for name in _COLUMNS if name in cols})
        for i in range(5)
    )


def replace_year(inputs: StockInputs, idx: int, **changes) -> StockInputs:
    years = list(inputs.years)
    years[idx] = replace(years[idx], **changes)
    return replace(inputs, years=tuple(years))


def with_column(inputs: StockInputs, attr: str, values: tuple) -> StockInputs:
    return replace(inputs, years=tuple(replace(y, **{attr: v}) for y, v in zip(inputs.years, values)))


CHEIL = StockInputs(name="제일기획", code="030000", price=19500.0, price_date=date(2026, 11, 9), pbr=1.43,
    years=rows(year=(2021, 2022, 2023, 2024, 2025),
        eps=(1634, 1913, 1849, 2049, 2049), per=(13.98, 12.05, 10.29, 8.289999999999999, 10.25),
        dps=(990, 1150, 1110, 1230, 1230), roe=(15.64, 16.68, 15.09, 15.03, 13.63),
        debt_ratio=(125.51, 125.26, 122.65, 124.32, 125.93),
        interest_coverage=(36.38, 44.97, 28.23, 32.66, 22.32),
        net_income=(1654.85, 1937.32, 1873.02, 2075.17, 2075.46), ocf=(2495, 1842, 2667, 3464, 2123)),
    prior_years=(2016, 2017, 2018, 2019, 2020), prior_dps=(300, 760, 770, 820, 840),
    gate4=Gate4Inputs(reason="주요 고객사(삼성 계열)가 마케팅 예산을 줄이고 원화가 강해져서 올해 이익이 줄었다."))

KIA = StockInputs(name="기아", code="000270", price=97000.0, price_date=date(2026, 11, 9), pbr=0.62,
    years=rows(year=(2021, 2022, 2023, 2024, 2025),
        eps=(11874, 13495, 22168, 24893, 19382), per=(6.92, 4.39, 4.51, 4.05, 6.28),
        dps=(3000, 3500, 5600, 6500, 6800), roe=(14.69, 14.57, 20.44, 19.09, 12.91),
        debt_ratio=(91.48, 87.34999999999999, 73.18000000000001, 66.11, 61.76),
        interest_coverage=(29.72, 30.85, 63.02, 121.2, 115.56),
        net_income=(47604.5, 54094.29, 87769.7, 97729.57000000001, 75609.83),
        ocf=(74000, 93000, 113000, 126000, 91000)),
    prior_years=(2016, 2017, 2018, 2019, 2020), prior_dps=(1100, 800, 900, 1150, 1000),
    gate4=Gate4Inputs(reason="미국 관세, 할인 경쟁(인센티브 증가), 중국 전기차의 공세로 이익이 2024년 정점에서 내려오고 있다."))

_REASON = KIA.gate4.reason
_FULL_PASS = replace(
    with_column(KIA, "capex", (20000,) * 5),
    price=60000.0, prior_dps=(800, 900, 1000, 1100, 1150),
    gate4=Gate4Inputs(_REASON, "예", "예", "예", "일시적", "근거"))

_DEFAULT = Criteria()

CASES: dict[str, tuple[StockInputs, Criteria]] = {
    "blank": (StockInputs(), _DEFAULT),
    "cheil": (CHEIL, _DEFAULT),
    "kia": (KIA, _DEFAULT),
    "kia_negative_eps": (with_column(KIA, "eps", (-500, -800, 300, 200, -100)), _DEFAULT),
    "kia_abnormal_year": (replace_year(KIA, 1, eps=3000), _DEFAULT),
    "kia_x_marks": (replace_year(replace_year(KIA, 2, exclude_avg=True), 0, exclude_div=True), _DEFAULT),
    "kia_zero_dps": (replace(replace_year(KIA, 3, dps=0), prior_dps=(1100, 800, 0, 1150, 1000)), _DEFAULT),
    "kia_cov999_no_debt": (replace_year(KIA, 4, interest_coverage=999, debt_ratio=None), _DEFAULT),
    "kia_ni_sum_negative": (with_column(KIA, "net_income", (-50000, -60000, 10000, 5000, 20000)), _DEFAULT),
    "kia_count_mismatch": (with_column(replace_year(KIA, 0, ocf=None), "capex",
                                       (None, None, 20000, 20000, 20000)), _DEFAULT),
    "kia_partial_years": (replace(KIA, years=(YearRow(), YearRow()) + KIA.years[2:],
                                  prior_years=(None,) * 5, prior_dps=(None,) * 5), _DEFAULT),
    "kia_full_pass": (_FULL_PASS, _DEFAULT),
    "kia_gate3_pass_gate2_check": (replace(_FULL_PASS, prior_dps=KIA.prior_dps, gate4=Gate4Inputs()), _DEFAULT),
    "kia_gate4_fail": (replace(_FULL_PASS, gate4=replace(_FULL_PASS.gate4, judgment="구조적")), _DEFAULT),
    "payout_round_edge": (with_column(with_column(CHEIL, "eps", (2000,) * 5), "dps", (1210,) * 5), _DEFAULT),
    "override_eps": (replace(KIA, normal_eps_override=25000.0, my_eps=21000.0), _DEFAULT),
    "criteria_alt": (KIA, Criteria(required_return=0.08, safety_margin=0.30, roe_min=15, payout_max=0.5)),
    "text_inputs": (replace(KIA, name="A&B<C>", gate4=replace(KIA.gate4, q1="모르겠음")), _DEFAULT),
}
