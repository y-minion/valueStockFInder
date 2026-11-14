"""공용 데이터 모델."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Criteria:
    """판정 기준값. 기본값은 엑셀 '기준값' 시트와 같아요."""

    required_return: float = 0.10
    safety_margin: float = 0.25
    roe_min: float = 8.0
    debt_ratio_max: float = 200.0
    interest_coverage_min: float = 3.0
    ocf_to_ni_min: float = 1.0
    payout_min: float = 0.20
    payout_max: float = 0.60
    fcf_to_div_min: float = 1.0
    abnormal_ratio: float = 0.5
    isa_weight_max: float = 0.10
