"""금융회사 전용 판정 자료: 자본비율과 업종별 기준."""
from dataclasses import asdict, dataclass

from vsf.config import FinancialSettings

CAPITAL_LABELS = {"금융지주": "보통주자본비율", "은행": "보통주자본비율", "보험": "지급여력비율(K-ICS)",
                  "증권": "순자본비율", "카드·캐피탈": "자본비율"}
CAPITAL_HELP = "자본비율은 금감원 금융통계정보시스템(fisis.fss.or.kr)이나 사업보고서 '자본적정성'에서 확인해 주세요."
FIN_CELLS = ("F_LOSS_B", "F_LOSS_C", "F_LOSS_D", "F_CAP_B", "F_CAP_C", "F_CAP_D", "F_CAP_SRC")


@dataclass(frozen=True)
class CapitalRatio:
    value: float        # 퍼센트
    base_month: str     # 예: "2026-09"
    source: str


@dataclass(frozen=True)
class FinancialGate:
    kind: str
    capital: CapitalRatio | None
    capital_min: float | None


def financial_gate(kind: str | None, capital: CapitalRatio | None,
                   fs: FinancialSettings) -> FinancialGate | None:
    if kind is None:
        return None
    capital_min = {"금융지주": fs.bank_cet1_min, "은행": fs.bank_cet1_min,
                   "보험": fs.insurer_kics_min, "증권": fs.securities_ncr_min}.get(kind)
    return FinancialGate(kind=kind, capital=capital, capital_min=capital_min)


def gate_to_dict(g: FinancialGate | None) -> dict | None:
    if g is None:
        return None
    return asdict(g)


def gate_from_dict(d: dict | None) -> FinancialGate | None:
    if d is None:
        return None
    c = d.get("capital")
    cap = None if c is None else CapitalRatio(float(c["value"]), c["base_month"], c["source"])
    m = d.get("capital_min")
    return FinancialGate(kind=d["kind"], capital=cap, capital_min=None if m is None else float(m))
