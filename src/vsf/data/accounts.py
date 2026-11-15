"""DART 재무제표 줄(FinRows)에서 계산기에 넣을 계정을 뽑아요."""
import math
import re
from dataclasses import dataclass
from typing import Literal

from vsf.data.dart import FinRows

PERIODS = ("thstrm", "frmtrm", "bfefrmtrm")

_IFRS = "ifrs-full_"
_IS = ("IS", "CIS")
_ABSOLUTE = {"capex", "dividends_paid"}

# 필드: (재무제표 순서, account_id 목록, 정규화한 이름 목록)
_SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "net_income_parent": (_IS, (_IFRS + "ProfitLossAttributableToOwnersOfParent",),
                          ("지배기업의소유주에게귀속되는당기순이익", "지배기업소유주지분", "지배기업의소유주지분")),
    "profit_loss": (_IS, (_IFRS + "ProfitLoss",), ("당기순이익",)),
    "eps": (_IS, (_IFRS + "BasicEarningsLossPerShare", _IFRS + "BasicAndDilutedEarningsLossPerShare"),
            ("기본주당이익", "기본주당순이익", "보통주기본주당이익", "기본및희석주당이익", "기본및희석주당순이익")),
    "equity_parent": (("BS",), (_IFRS + "EquityAttributableToOwnersOfParent",),
                      ("지배기업의소유주에게귀속되는자본", "지배기업소유주지분")),
    "equity_total": (("BS",), (_IFRS + "Equity",), ("자본총계",)),
    "liabilities": (("BS",), (_IFRS + "Liabilities",), ("부채총계",)),
    "current_assets": (("BS",), (_IFRS + "CurrentAssets",), ("유동자산",)),
    "operating_income": (_IS, ("dart_OperatingIncomeLoss",), ("영업이익",)),
    "interest_expense": (_IS, (_IFRS + "InterestExpense",), ("이자비용",)),
    "interest_paid": (("CF",), (_IFRS + "InterestPaidClassifiedAsOperatingActivities",
                                _IFRS + "InterestPaidClassifiedAsFinancingActivities"),
                      ("이자의지급", "이자지급")),
    "ocf": (("CF",), (_IFRS + "CashFlowsFromUsedInOperatingActivities",),
            ("영업활동현금흐름", "영업활동으로인한현금흐름")),
    "capex": (("CF",), (_IFRS + "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                        _IFRS + "PurchaseOfPropertyPlantAndEquipment"),
              ("유형자산의취득",)),
    "dividends_paid": (("CF",), (_IFRS + "DividendsPaidClassifiedAsFinancingActivities",
                                 _IFRS + "DividendsPaid"),
                       ("배당금의지급", "배당금지급")),
}


@dataclass(frozen=True)
class Sourced:
    value: float | None
    account: str
    how: Literal["id", "name", "proxy", "derived"]


def parse_amount(s: str | None) -> float | None:
    """"1,234" → 1234.0. 빈 값·"-"·숫자가 아닌 글자는 None."""
    if s is None:
        return None
    text = s.strip().replace(",", "")
    if text in ("", "-"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _normalize(name: str) -> str:
    return re.sub(r"\(손실\)|[\s·]", "", name or "")


def _ord(row: dict) -> int:
    try:
        return int(row.get("ord") or 0)
    except ValueError:
        return 0


def _pick(candidates: list[dict], field: str) -> dict:
    """같은 줄이 여럿이면 ord가 앞선 줄. EPS는 이름에 '보통주'가 든 줄을 먼저."""
    ordered = sorted(candidates, key=_ord)
    if field == "eps":
        ordered = [r for r in ordered if "보통주" in r.get("account_nm", "")] + \
                  [r for r in ordered if "보통주" not in r.get("account_nm", "")]
    return ordered[0]


def extract(fin: FinRows, period: str) -> dict[str, Sourced]:
    """계정 13개를 period("thstrm"·"frmtrm"·"bfefrmtrm") 금액으로 뽑아요. 단위는 보고서 그대로."""
    key = f"{period}_amount"
    out: dict[str, Sourced] = {}
    for field, (statements, ids, names) in _SPEC.items():
        wanted_names = {_normalize(n) for n in names}
        found: Sourced | None = None
        for how, matches in (
            ("id", lambda r: r.get("account_id") in ids),
            ("name", lambda r: _normalize(r.get("account_nm", "")) in wanted_names),
        ):
            for sj in statements:
                rows = [r for r in fin.rows
                        if r.get("sj_div") == sj and matches(r) and parse_amount(r.get(key)) is not None]
                if rows:
                    row = _pick(rows, field)
                    value = parse_amount(row[key])
                    assert value is not None
                    found = Sourced(abs(value) if field in _ABSOLUTE else value,
                                    row["account_id"] if how == "id" else row["account_nm"], how)
                    break
            if found:
                break
        out[field] = found or Sourced(None, "", "id")
    return out
