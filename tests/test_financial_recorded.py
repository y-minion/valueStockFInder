"""실제 DART 응답(KB금융·삼성화재·삼성증권)으로 금융회사 분류와 금융업 판정을 확인해요."""
import json
from dataclasses import replace
from datetime import date

import pytest

from helpers import RECORDED_DART, load_company, load_divs, load_fin
from vsf.config import FinancialSettings
from vsf.data.assemble import assemble
from vsf.data.store import PriceRow
from vsf.data.universe import financial_kind, is_financial_holding
from vsf.engine import compute
from vsf.financial import financial_gate
from vsf.model import Criteria

D = date(2026, 11, 13)
CASES = [("kb", "105560", "금융지주"), ("samsungfire", "000810", "보험"), ("samsungsec", "016360", "증권")]


def _kind(name: str, code: str) -> str | None:
    raw = json.loads((RECORDED_DART / f"company_{code}.json").read_text(encoding="utf-8"))
    kind = financial_kind(raw)
    if kind is None and is_financial_holding(load_fin(f"{name}_2025_cfs")):
        kind = "금융지주"
    return kind


@pytest.mark.recorded("dart")
@pytest.mark.parametrize("name,code,want", CASES)
def test_recorded_financial_companies_get_sector_verdicts(name, code, want):
    assert _kind(name, code) == want
    co = replace(load_company(name), financial_kind=want)
    price = PriceRow(D, code, co.name, co.market, close=50_000.0, shares=None)
    a = assemble(co, 2025, load_fin(f"{name}_2025_cfs"), load_fin(f"{name}_2023_cfs"), load_divs(name), {}, price, D)
    for y in a.inputs.years:
        assert (y.debt_ratio, y.interest_coverage, y.ocf, y.capex) == (None, None, None, None)
        assert y.eps is not None and y.roe is not None and y.net_income is not None
    v = compute(a.inputs, Criteria(), financial=financial_gate(want, None, FinancialSettings()))
    assert [v[c] for c in ("D79", "D80", "D81", "D89")] == ["해당 없음"] * 4
    assert v["F_LOSS_D"] == "통과" and v["F_CAP_D"] == "직접 확인" and v["D82"] in ("확인 필요", "탈락")
