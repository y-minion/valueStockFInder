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
    "net_income_nci": (_IS, (_IFRS + "ProfitLossAttributableToNonControllingInterests",),
                       ("비지배지분에귀속되는당기순이익", "비지배지분")),
    "profit_loss": (_IS, (_IFRS + "ProfitLoss",), ("당기순이익",)),
    "eps": (_IS, (_IFRS + "BasicEarningsLossPerShare", _IFRS + "BasicAndDilutedEarningsLossPerShare"),
            ("기본주당이익", "기본주당순이익", "보통주기본주당이익", "보통주기본주당순이익", "기본및희석주당이익",
             "기본및희석주당순이익", "보통주기본및희석주당이익", "보통주기본및희석주당순이익")),
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
              ("유형자산의취득", "유형자산및투자부동산의취득")),
    "dividends_paid": (("CF",), (_IFRS + "DividendsPaidClassifiedAsFinancingActivities",
                                 _IFRS + "DividendsPaid"),
                       ("배당금의지급", "배당금지급")),
}


# 자본변동표(SCE) 기초자본 줄: 필드 → account_detail (id와 이 글이 정확히 같을 때만)
_SCE_BEGIN_ID = "dart_EquityAtBeginningOfPeriod"
_SCE_BEGIN = {
    "equity_begin_parent": "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]",
    "equity_begin_total": "자본 [구성요소]",
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
    """이름 비교용: 공백·가운뎃점·'(손실)'을 빼고, '/'는 '및', '손익'은 '이익'으로 읽어요.

    회사마다 "기본/희석주당순이익"·"기본및희석주당손익"·"영업손익"처럼 같은 줄을 다르게 적어요.
    """
    text = re.sub(r"\(손실\)|[\s·]", "", name or "")
    return text.replace("/", "및").replace("손익", "이익")


# 전체 EPS 줄 없이 계속영업·중단영업 EPS만 적는 회사가 있어요 (카카오 2025, NAVER 2023 보고서).
_EPS_CONTINUING = _IFRS + "BasicEarningsLossPerShareFromContinuingOperations"
_EPS_DISCONTINUED = _IFRS + "BasicEarningsLossPerShareFromDiscontinuedOperations"
_EPS_DERIVED = "계속영업 + 중단영업 기본주당이익(더해서 구함)"


def _eps_part(fin: FinRows, key: str, account_id: str, word: str) -> float | None:
    """계속영업(word="계속영업") 또는 중단영업 기본 EPS 한 칸. id로 먼저, 없으면 이름에 word·기본·주당이 든 줄."""
    for matches in (lambda r: r.get("account_id") == account_id,
                    lambda r: all(w in _normalize(r.get("account_nm", "")) for w in (word, "기본", "주당"))):
        for sj in _IS:
            rows = [r for r in fin.rows if r.get("sj_div") == sj and matches(r)]
            values = [v for v in (parse_amount(r.get(key)) for r in sorted(rows, key=_ord)) if v is not None]
            if values:
                return values[0]
    return None


def _derived_eps(fin: FinRows, key: str) -> Sourced | None:
    """전체 EPS = 계속영업 EPS + 중단영업 EPS. 중단영업 칸이 비어 있으면 그해 중단영업이 없던 거예요."""
    continuing = _eps_part(fin, key, _EPS_CONTINUING, "계속영업")
    if continuing is None:
        return None
    discontinued = _eps_part(fin, key, _EPS_DISCONTINUED, "중단영업")
    return Sourced(continuing + (discontinued or 0.0), _EPS_DERIVED, "derived")


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
    """계정 16개를 period("thstrm"·"frmtrm"·"bfefrmtrm") 금액으로 뽑아요. 단위는 보고서 그대로."""
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
    if out["eps"].value is None:
        out["eps"] = _derived_eps(fin, key) or out["eps"]
    for field, detail in _SCE_BEGIN.items():
        amounts = {parse_amount(r.get(key)) for r in fin.rows
                   if r.get("sj_div") == "SCE" and r.get("account_id") == _SCE_BEGIN_ID
                   and (r.get("account_detail") or "").strip() == detail} - {None}
        value = next(iter(amounts)) if len(amounts) == 1 else None   # 여럿이 서로 다르면 찾지 못한 걸로
        out[field] = Sourced(value, _SCE_BEGIN_ID, "id") if value is not None else Sourced(None, "", "id")
    return out
