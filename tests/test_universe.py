import pytest

from tests.helpers import fin_row, synthetic
from vsf.data.krx import Listed
from vsf.data.universe import company_exclusion, holding_exclusion, is_holding, listing_exclusion


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
    (L(group="부동산투자회사"), "리츠"), (L(name="어떤리츠"), "리츠"),
    (L(name="맥쿼리인프라", group="투자회사"), "투자회사 등"), (L(), None),
    # 순서: 우선주 → 리츠 → 스팩 → 투자회사 등
    (L(kind="우선주", name="리츠"), "우선주"), (L(name="리츠스팩"), "리츠"),
    # kind 비었으면 단축코드 끝자리로
    (L(kind="", code="005935"), "우선주"), (L(kind=None, code="005935"), "우선주"),
    (L(kind="", code="005930"), None), (L(kind=None, code="005930"), None),
    # group 비었으면 투자회사 등으로 제외하지 않아요
    (L(group=""), None), (L(group=None), None)])
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
    assert company_exclusion(co) == want


def test_is_holding():
    assert is_holding({"induty_code": "64992"}) and not is_holding({"induty_code": "6419"})
    assert not is_holding({})


def test_holding_with_current_assets_kept():
    assert holding_exclusion(fin_with(current_assets=1)) is None


def test_financial_holding_excluded():
    assert holding_exclusion(fin_with()) == "금융지주"


def test_holding_without_statement_is_not_judged():
    assert holding_exclusion(None) is None
