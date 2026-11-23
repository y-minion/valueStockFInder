"""분석 대상 고르기: 우선주·리츠·스팩·금융회사 등을 사유와 함께 걸러내요."""
from __future__ import annotations

from vsf.data.accounts import extract
from vsf.data.dart import FinRows
from vsf.data.krx import Listed

# 외국 회사 주식. KRX 증권구분 값 (2026-11-16 실제 응답에서 확인). 사용자: "지금은 국내 주식만"
FOREIGN_GROUPS = ("외국주권", "주식예탁증권")
REIT_GROUP = "부동산투자회사"   # KRX 증권구분 값 (2026-11-16 실제 응답에서 확인)
HOLDING_PREFIX = "64992"
# DART가 큰 분류 코드만 주는 회사 (2026-11-16 실제 실행: HDC·효성 "649", HS효성 "64999", 카카오페이 "66199" 등)
HOLDING_LIKE_PREFIX, CARD_CAPITAL_PREFIX = "649", "6491"   # 649…는 지주회사처럼 (6491 카드·캐피탈 말고)
BROKER_SERVICE_PREFIX, BROKER_PREFIX = "661", "6612"       # 661…(6612 말고)은 이름에 "증권"이 있을 때만 증권
INSURANCE_SERVICE_PREFIX = "662"                           # 보험 대리·서비스는 일반 회사
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
    if _is_reit(item):
        return "리츠"
    if "스팩" in item.name or "기업인수목적" in item.name:
        return "스팩"
    if item.group in FOREIGN_GROUPS:
        return "외국 회사"
    if item.group and "주권" not in item.group:
        return "투자회사 등"
    return None


def _is_reit(item: Listed) -> bool:
    """KRX 증권구분이 있으면 그것만 봐요("부동산투자회사"). 비어 있을 때만 이름에 "리츠"가 있는지 봐요.

    이름 규칙은 "메리츠…"(메리츠금융지주·메리츠제1호스팩 등)를 잘못 잡아서 "메리츠"로 시작하는 이름은 빼요.
    """
    if item.group:
        return item.group == REIT_GROUP
    return "리츠" in item.name and not item.name.startswith("메리츠")


def is_holding(company: dict) -> bool:
    return str(company.get("induty_code") or "").startswith(HOLDING_PREFIX)


def _code(company: dict) -> str:
    return str(company.get("induty_code") or "")


def is_holding_like(company: dict) -> bool:
    """지주회사처럼 다루는 회사: 64992와, 큰 분류 649…(6491 카드·캐피탈 말고).

    금융지주인지는 재무제표를 받은 뒤 유동자산으로 가려요 (is_financial_holding).
    """
    code = _code(company)
    return code.startswith(HOLDING_LIKE_PREFIX) and not code.startswith(CARD_CAPITAL_PREFIX)


def _broker_name(company: dict) -> bool:
    return any("증권" in str(company.get(key) or "") for key in ("corp_name", "stock_name"))


def financial_kind(company: dict) -> str | None:
    """지주회사가 아닌 금융회사의 종류. 금융회사가 아니면 None, 기준이 없는 종류는 "그 밖"이에요.

    - 649…(6491 말고)는 지주회사처럼 None이에요. 금융지주인지는 재무제표를 받은 뒤 정해요.
    - 661…(6612 말고)은 회사·종목 이름에 "증권"이 있으면 증권, 아니면 일반 회사예요 (NHN KCP 같은 결제 회사).
    - 662…(보험 대리·서비스)는 일반 회사예요.
    """
    code = _code(company)
    if code[:2] not in FINANCIAL_DIVISIONS or is_holding_like(company):   # 64992 포함
        return None
    for prefix, kind in _KIND_BY_PREFIX:
        if code.startswith(prefix):
            return kind
    if code.startswith(BROKER_SERVICE_PREFIX):
        return "증권" if _broker_name(company) else None
    if code.startswith(INSURANCE_SERVICE_PREFIX):
        return None
    return OTHER_FINANCIAL


def company_exclusion(company: dict, include_financial: bool = True) -> str | None:
    """DART 기업개황으로 제외 사유를 찾아요. 값이 없으면 그 항목으로는 제외하지 않아요.

    include_financial=False는 예전 그대로예요: 64·65·66 업종은 64992 지주회사 말고 모두 "금융회사".
    금융회사(그 밖: 창투·신탁·저축은행 등)도 분석해요 (2026-11-23, 점수 순위 설계 4장).
    """
    acc_mt = company.get("acc_mt")
    if acc_mt and acc_mt != "12":
        return "결산월 12월 아님"
    if not include_financial:
        return "금융회사" if _code(company)[:2] in FINANCIAL_DIVISIONS and not is_holding(company) else None
    return None


def is_financial_holding(fin: FinRows | None) -> bool:
    """최신 재무상태표에 유동자산이 없으면 금융지주예요. 재무제표가 없으면 판단하지 않아요."""
    return fin is not None and extract(fin, "thstrm")["current_assets"].value is None
