"""분석 대상 고르기: 우선주·리츠·스팩·금융회사 등을 사유와 함께 걸러내요."""
from __future__ import annotations

from vsf.data.accounts import extract
from vsf.data.dart import FinRows
from vsf.data.krx import Listed

HOLDING_PREFIX = "64992"
FINANCIAL_DIVISIONS = ("64", "65", "66")


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


def company_exclusion(company: dict) -> str | None:
    """DART 기업개황으로 제외 사유를 찾아요. 값이 없으면 그 항목으로는 제외하지 않아요."""
    acc_mt = company.get("acc_mt")
    if acc_mt and acc_mt != "12":
        return "결산월 12월 아님"
    code = str(company.get("induty_code") or "")
    if code[:2] in FINANCIAL_DIVISIONS and not is_holding(company):
        return "금융회사"
    return None


def holding_exclusion(fin: FinRows | None) -> str | None:
    """지주회사인데 최신 재무상태표에 유동자산이 없으면 금융지주예요. 재무제표가 없으면 판단하지 않아요."""
    if fin is None:
        return None
    if extract(fin, "thstrm")["current_assets"].value is None:
        return "금융지주"
    return None
