import pytest

from tests.helpers import fin_row, synthetic
from vsf.data.krx import Listed
from vsf.data.universe import (company_exclusion, financial_kind, is_financial_holding, is_holding,
                               listing_exclusion)


def L(**kw) -> Listed:
    base = dict(code="005930", name="삼성전자", market="KOSPI", group="주권", kind="보통주", shares=1.0)
    return Listed(**{**base, **kw})


def fin_with(**kw):
    extra = []
    if kw.get("current_assets"):
        extra.append(fin_row("BS", "ifrs-full_CurrentAssets", "유동자산", kw["current_assets"], ord=1))
    return synthetic(defaults=False, extra=extra)


@pytest.mark.parametrize("item,want", [
    (L(kind="우선주"), "우선주"), (L(name="하나30호스팩"), "스팩"), (L(name="X기업인수목적1호"), "스팩"),
    (L(group="부동산투자회사"), "리츠"), (L(name="어떤리츠", group=""), "리츠"),
    # 리츠는 KRX 증권구분으로만 가려요. 이름 규칙은 증권구분이 빌 때만, 그때도 "메리츠…"는 빼요.
    (L(name="메리츠금융지주", group="주권"), None), (L(name="메리츠제1호스팩"), "스팩"),
    (L(name="ESR켄달스퀘어리츠", group="부동산투자회사"), "리츠"), (L(name="어떤리츠", group=None), "리츠"),
    (L(name="메리츠금융지주", group=""), None), (L(name="메리츠제1호스팩", group=""), "스팩"),
    (L(name="맥쿼리인프라", group="투자회사"), "투자회사 등"), (L(), None),
    # 순서: 우선주 → 리츠 → 스팩 → 투자회사 등
    (L(kind="우선주", name="리츠"), "우선주"), (L(name="리츠스팩", group=""), "리츠"),
    # kind 비었으면 단축코드 끝자리로
    (L(kind="", code="005935"), "우선주"), (L(kind=None, code="005935"), "우선주"),
    (L(kind="", code="005930"), None), (L(kind=None, code="005930"), None),
    # group 비었으면 투자회사 등으로 제외하지 않아요
    (L(group=""), None), (L(group=None), None),
    # 외국 회사 주식(외국주권·주식예탁증권)은 빼요. 사용자: "지금은 국내 주식만"
    (L(group="외국주권", name="엘브이엠씨홀딩스", code="900140"), "외국 회사"),
    (L(group="주식예탁증권", name="어떤DR"), "외국 회사")])
def test_listing_exclusion(item, want):
    assert listing_exclusion(item) == want


@pytest.mark.parametrize("co,want", [
    ({"acc_mt": "03", "induty_code": "30121"}, "결산월 12월 아님"),
    ({"acc_mt": "12", "induty_code": "6419"}, "금융회사"), ({"acc_mt": "12", "induty_code": "65110"}, "금융회사"),
    ({"acc_mt": "12", "induty_code": "66"}, "금융회사"),
    ({"acc_mt": "12", "induty_code": "64992"}, None), ({"acc_mt": "12", "induty_code": "30121"}, None),
    ({"induty_code": "30121"}, None), ({"acc_mt": "12"}, None), ({}, None),
    ({"acc_mt": None, "induty_code": None}, None), ({"acc_mt": "", "induty_code": ""}, None),
    ({"induty_code": "6419"}, "금융회사")])
def test_company_exclusion(co, want):
    assert company_exclusion(co, include_financial=False) == want


def test_is_holding():
    assert is_holding({"induty_code": "64992"}) and not is_holding({"induty_code": "6419"})
    assert not is_holding({})


def test_holding_with_current_assets_kept():
    assert not is_financial_holding(fin_with(current_assets=1))


def test_financial_holding_excluded():
    assert is_financial_holding(fin_with())


def test_holding_without_statement_is_not_judged():
    assert not is_financial_holding(None)


@pytest.mark.parametrize("code,kind", [
    ("64121", "은행"), ("65110", "보험"), ("65121", "보험"), ("65200", "보험"), ("66121", "증권"),
    ("64911", "카드·캐피탈"), ("64201", "그 밖"), ("6419", "그 밖"), ("66", "그 밖"),
    ("64992", None), ("30121", None), ("", None)])
def test_financial_kind(code, kind):
    assert financial_kind({"induty_code": code}) == kind


def test_company_exclusion_includes_supported_financials():
    assert company_exclusion({"acc_mt": "12", "induty_code": "64121"}) is None
    assert company_exclusion({"acc_mt": "12", "induty_code": "64201"}) == "금융회사(그 밖)"
    assert company_exclusion({"acc_mt": "12", "induty_code": "64121"}, include_financial=False) == "금융회사"


# ---- DART가 큰 분류 코드만 주는 회사 (2026-11-16 실제 실행에서 본 코드) ----

@pytest.mark.parametrize("co,kind", [
    # 649…(6491 카드·캐피탈 말고)는 지주회사처럼: 재무제표를 받은 뒤 유동자산으로 가려요 → 여기서는 None
    ({"induty_code": "649", "corp_name": "HDC"}, None), ({"induty_code": "64999", "corp_name": "HS효성"}, None),
    ({"induty_code": "64991", "corp_name": "LB인베스트먼트"}, None), ({"induty_code": "64911"}, "카드·캐피탈"),
    # 661…(6612 말고)은 이름에 "증권"이 있으면 증권, 아니면 일반 회사
    ({"induty_code": "661", "corp_name": "다올투자증권"}, "증권"),
    ({"induty_code": "661", "corp_name": "다올투자증권(주)", "stock_name": "다올투자증권"}, "증권"),
    ({"induty_code": "661", "corp_name": "어떤회사", "stock_name": "어떤증권"}, "증권"),
    ({"induty_code": "661", "corp_name": "NHN KCP", "stock_name": "NHN KCP"}, None),
    ({"induty_code": "661", "corp_name": "헥토파이낸셜"}, None), ({"induty_code": "661"}, None),
    ({"induty_code": "66199", "corp_name": "카카오페이"}, None),
    # 662…(보험 대리·서비스)는 일반 회사
    ({"induty_code": "66202", "corp_name": "에이플러스에셋"}, None), ({"induty_code": "66202"}, None),
    # 나머지는 그대로 "그 밖": 신탁(642), 창업투자(6420x), 저축은행(64132)
    ({"induty_code": "642"}, "그 밖"), ({"induty_code": "64201"}, "그 밖"), ({"induty_code": "64132"}, "그 밖"),
    ({"induty_code": "66", "corp_name": "어떤증권"}, "그 밖")])
def test_financial_kind_coarse_codes(co, kind):
    assert financial_kind(co) == kind


@pytest.mark.parametrize("code,name,want", [
    ("649", "HDC", None), ("64999", "HS효성", None), ("64991", "LB인베스트먼트", None),
    ("661", "다올투자증권", None), ("661", "NHN KCP", None), ("66199", "카카오페이", None),
    ("66202", "인카금융서비스", None), ("642", "어떤신탁", "금융회사(그 밖)"),
    ("64201", "어떤창업투자", "금융회사(그 밖)"), ("64132", "어떤저축은행", "금융회사(그 밖)")])
def test_company_exclusion_coarse_codes(code, name, want):
    co = {"acc_mt": "12", "induty_code": code, "corp_name": name}
    assert company_exclusion(co) == want
    # include = false는 예전 그대로: 64·65·66은 (64992 지주회사 말고) 모두 "금융회사"
    assert company_exclusion(co, include_financial=False) == "금융회사"


def test_is_holding_like():
    from vsf.data.universe import is_holding_like

    assert all(is_holding_like({"induty_code": c}) for c in ("649", "64991", "64992", "64999"))
    assert not any(is_holding_like({"induty_code": c}) for c in ("6491", "64911", "642", "661", "30121", ""))
    assert not is_holding_like({})
