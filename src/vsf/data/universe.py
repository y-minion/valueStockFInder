"""분석 대상 고르기: 우선주·리츠·스팩·금융회사 등을 사유와 함께 걸러내요."""
from __future__ import annotations

from vsf.data.accounts import extract
from vsf.data.dart import FinRows
from vsf.data.krx import Listed

HOLDING_PREFIX = "64992"
FINANCIAL_DIVISIONS = ("64", "65", "66")
FINANCIAL_KINDS = ("금융지주", "은행", "보험", "증권", "카드·캐피탈")
OTHER_FINANCIAL = "그 밖"
_KIND_BY_PREFIX = (("6412", "은행"), ("651", "보험"), ("652", "보험"), ("6612", "증권"), ("6491", "카드·캐피탈"))


def listing_exclusion(item: Listed) -> str | None:
    """KRX 종목 정보로 제외 사유를 찾아요. 없으면 None.

    KRX 필드 이름이 아직 검증되지 않아서, 값이 비어 있으면 그 항목으로는 제외하지 않아요
    (주식종류가 비면 단축코드 끝자리 0 여부로 우선주를 가려요).
    """
    if item.kind:
        if "보통주" not in item.kind:
            return "우선주"
    elif not item.code.endswith("0"):
        return "우선주"
    if (item.group and "부동산투자" in item.group) or "리츠" in item.name:
        return "리츠"
    if "스팩" in item.name or "기업인수목적" in item.name:
        return "스팩"
    if item.group and "주권" not in item.group:
        return "투자회사 등"
    return None


def is_holding(company: dict) -> bool:
    return str(company.get("induty_code") or "").startswith(HOLDING_PREFIX)


def financial_kind(company: dict) -> str | None:
    """지주회사가 아닌 금융회사의 종류. 금융회사가 아니면 None, 기준이 없는 종류는 "그 밖"이에요."""
    code = str(company.get("induty_code") or "")
    if code[:2] not in FINANCIAL_DIVISIONS or is_holding(company):
        return None
    for prefix, kind in _KIND_BY_PREFIX:
        if code.startswith(prefix):
            return kind
    return OTHER_FINANCIAL


def company_exclusion(company: dict, include_financial: bool = True) -> str | None:
    """DART 기업개황으로 제외 사유를 찾아요. 값이 없으면 그 항목으로는 제외하지 않아요."""
    acc_mt = company.get("acc_mt")
    if acc_mt and acc_mt != "12":
        return "결산월 12월 아님"
    kind = financial_kind(company)
    if kind is None:
        return None
    if not include_financial:
        return "금융회사"
    return f"금융회사({OTHER_FINANCIAL})" if kind == OTHER_FINANCIAL else None


def is_financial_holding(fin: FinRows | None) -> bool:
    """최신 재무상태표에 유동자산이 없으면 금융지주예요. 재무제표가 없으면 판단하지 않아요."""
    return fin is not None and extract(fin, "thstrm")["current_assets"].value is None
