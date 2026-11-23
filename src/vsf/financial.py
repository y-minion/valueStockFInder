"""금융회사 전용 판정 자료: 자본비율과 업종별 기준."""
from dataclasses import asdict, dataclass

from vsf.config import FinancialSettings
from vsf.model import SheetValues

CAPITAL_LABELS = {"금융지주": "보통주자본비율", "은행": "보통주자본비율", "보험": "지급여력비율(K-ICS)",
                  "증권": "순자본비율", "카드·캐피탈": "자본비율", "그 밖": "자본비율"}
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


def financial_memo(g: FinancialGate, cells: SheetValues) -> str:
    """엑셀 B23 메모: 엑셀 칸은 계산기 그대로라, 금융업 기준 판정은 여기에 글로 적어요."""
    b78 = cells.get("B78")
    roe = f"{b78:.1f}%" if isinstance(b78, (int, float)) and not isinstance(b78, bool) else "—"
    loss = {"통과": "없음", "탈락": "있음"}.get(cells.get("F_LOSS_D"), "확인 필요")
    cap = (f"{g.capital.value:g}% · {g.capital.base_month} 기준 · {cells.get('F_CAP_D')}"
           if g.capital else "직접 확인")
    return (f"금융회사({g.kind})라 금융업 기준으로 판정했어요: 관문 ① {cells.get('D82')} "
            f"(ROE 5년 평균 {roe}, 최근 5년 적자 {loss}, {CAPITAL_LABELS[g.kind]} {cap}), "
            f"관문 ② {cells.get('D90')}. 부채비율·이자보상배율·현금흐름은 금융회사에 맞지 않아 비워 뒀어요.")
