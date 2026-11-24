"""백테스트: DART 재무제표 API에 없는 해의 금융회사 입력 (2026-11-24 백테스트 설계 4장)."""
from dataclasses import replace
from datetime import date

from helpers import div_rows, synthetic_company
from vsf.backtest.past_financial import SUBSTITUTE_NOTE, substitute_inputs
from vsf.data.assemble import PRE_FOUNDING_NOTE, CompanyInfo, assemble, dividend_history
from vsf.data.fisis import LIFE_EQUITY, ROE_TABLES
from vsf.data.store import PriceRow

D = date(2019, 6, 28)
HANA = CompanyInfo(corp_code="00547583", code="086790", name="하나금융지주", market="KOSPI", induty_code="64992",
                   acc_mt="12", financial_kind="금융지주")
NAMES = ("(주)하나금융지주", "Hana Financial Group Inc.", "하나금융지주")


def _alot(year: int, eps: tuple[str, str, str], income: tuple[str, str, str], dps: tuple[str, str, str],
          sep: tuple[str, str, str] = ("-", "-", "-")) -> list[dict]:
    """배당 공시 한 건: 주당 현금배당금·(연결)주당순이익·(연결)/(별도)당기순이익(백만원) 줄."""
    rows = div_rows(*dps, year=year)
    def row(se, vals):
        return {**rows[0], "se": se, "stock_knd": "", "thstrm": vals[0], "frmtrm": vals[1], "lwfr": vals[2]}
    return rows + [row("(연결)주당순이익(원)", eps), row("(연결)당기순이익(백만원)", income), row("(별도)당기순이익(백만원)", sep)]


HANA_DIVS = {
    2018: _alot(2018, ("7,360", "6,817", "4,421"), ("2,233,325", "2,036,839", "1,330,477"), ("1,900", "1,550", "1,050")),
    2016: _alot(2016, ("4,421", "3,001", "3,177"), ("1,330,477", "909,732", "937,707"), ("1,050", "650", "600")),
}
HANA_YE = {y: PriceRow(date(y, 12, 28), "086790", "하나금융지주", "KOSPI", c, 300_000_000.0)
           for y, c in ((2014, 32000.0), (2015, 23600.0), (2016, 31250.0), (2017, 49800.0), (2018, 36250.0))}
HANA_PRICE = PriceRow(D, "086790", "하나금융지주", "KOSPI", 37400.0, 300_000_000.0)


class FakeFisis:
    def __init__(self, values: dict[tuple[str, str, str], dict[int, float]]):
        self.values = values
        self.asked: list[tuple] = []

    def annual_values(self, part_div, names, list_no, account, y0, y1):
        self.asked.append((part_div, list_no, account, y0, y1))
        return {y: v for y, v in self.values.get((part_div, list_no, account), {}).items() if y0 <= y <= y1}


def test_dividend_history_matches_assemble():
    co, L, fa, fb, divs, ye, price, d = synthetic_company()
    a = assemble(co, L, fa, fb, divs, ye, price, d)
    values, flags, notes = dividend_history(divs, L)
    assert [values[y] for y in range(L - 4, L + 1)] == [y.dps for y in a.inputs.years]
    assert [values[y] for y in range(L - 9, L - 4)] == list(a.inputs.prior_dps)
    founded = dividend_history({**divs, 2017: div_rows("800", "-", "-", year=2017)}, L, est_dt="20170302")
    assert founded[0][2016] is None and PRE_FOUNDING_NOTE.format(years="2016", founded="2017-03-02") in founded[2]


def test_substitute_inputs_from_dividend_reports_and_fisis():
    roe = {2014: 4.55, 2015: 4.17, 2016: 5.92, 2017: 8.77, 2018: 8.87}
    fisis = FakeFisis({ROE_TABLES["금융지주"]: roe})
    got = substitute_inputs(HANA, 2018, HANA_DIVS, HANA_YE, HANA_PRICE, D, fisis, NAMES, None)
    ys = got.inputs.years
    assert [y.year for y in ys] == [2014, 2015, 2016, 2017, 2018]
    assert [y.eps for y in ys] == [3177.0, 3001.0, 4421.0, 6817.0, 7360.0]
    assert [y.net_income for y in ys] == [9377.07, 9097.32, 13304.77, 20368.39, 22333.25]
    assert [y.dps for y in ys] == [600.0, 650.0, 1050.0, 1550.0, 1900.0]
    assert [y.roe for y in ys] == [4.55, 4.17, 5.92, 8.77, 8.87]
    assert ys[-1].per == round(36250 / 7360, 2) and ys[0].per == round(32000 / 3177, 2)
    assert all(y.debt_ratio is None and y.ocf is None for y in ys)
    assert got.inputs.price == 37400.0 and got.latest_year == 2018 and not got.quick_fail
    assert SUBSTITUTE_NOTE in got.notes


def test_life_insurer_roe_is_separate_income_over_average_equity():
    life = CompanyInfo(corp_code="00126256", code="032830", name="삼성생명", market="KOSPI", induty_code="65110",
                       acc_mt="12", financial_kind="보험")
    divs = {2018: _alot(2018, ("9,268", "6,494", "11,407"), ("1,664,382", "1,166,121", "2,054,267"),
                        ("2,650", "2,000", "1,200"), sep=("1,666,000", "1,200,000", "2,000,000"))}
    equity = {2015: 2.0e13, 2016: 2.2e13, 2017: 2.4e13, 2018: 2.65e13}       # 원
    fisis = FakeFisis({LIFE_EQUITY: equity})
    got = substitute_inputs(life, 2018, divs, {}, HANA_PRICE, D, fisis, ("삼성생명보험(주)",), None)
    roe = {y.year: y.roe for y in got.inputs.years}
    assert roe[2018] == round(16660.0 / ((265000.0 + 240000.0) / 2) * 100, 2)
    assert roe[2016] == round(20000.0 / ((220000.0 + 200000.0) / 2) * 100, 2)
    assert roe[2014] is None                                                # 자본 자료가 없는 해


def test_insurer_without_fisis_values_leaves_roe_blank():
    nonlife = CompanyInfo(corp_code="00139214", code="000810", name="삼성화재", market="KOSPI", induty_code="65121",
                          acc_mt="12", financial_kind="보험")
    got = substitute_inputs(nonlife, 2018, HANA_DIVS, HANA_YE, HANA_PRICE, D, FakeFisis({}), ("삼성화재해상보험(주)",), None)
    assert all(y.roe is None for y in got.inputs.years) and got.inputs.years[-1].eps == 7360.0


def test_non_life_insurer_and_securities_roe_from_fisis_equity():
    from vsf.data.fisis import EQUITY_TABLES
    divs = {2018: _alot(2018, ("9,000", "8,000", "7,000"), ("600,000", "500,000", "400,000"), ("2,000", "1,800", "1,600"),
                        sep=("550,000", "480,000", "390,000"))}
    equity = {2015: 4.0e12, 2016: 4.2e12, 2017: 4.6e12, 2018: 4.9e12}
    for kind, table in (("보험", EQUITY_TABLES["보험"][1]), ("증권", EQUITY_TABLES["증권"][0])):
        info = replace(HANA, financial_kind=kind)
        got = substitute_inputs(info, 2018, divs, {}, HANA_PRICE, D, FakeFisis({table: equity}), NAMES, None)
        roe = {y.year: y.roe for y in got.inputs.years}
        assert roe[2018] == round(5500.0 / ((49000.0 + 46000.0) / 2) * 100, 2), kind

def test_separate_only_net_income_still_fills_net_income():
    # (연결) 줄이 '-'이고 (별도) 줄에만 순이익이 있는 증권사예요 (저장된 금융회사 배당 공시 49건이 이 모양).
    # 순이익이 비면 관문 ①의 '5년 흑자' 확인이 빠져서 적자 회사도 통과해요.
    broker = CompanyInfo(corp_code="00145190", code="001500", name="증권사", market="KOSPI", induty_code="66121",
                         acc_mt="12", financial_kind="증권")
    divs = {2019: _alot(2019, ("-50", "30", "25"), ("-", "-", "-"), ("100", "100", "100"), sep=("-1,200", "800", "700"))}
    got = substitute_inputs(broker, 2019, divs, {}, HANA_PRICE, D, FakeFisis({}), ("증권사",), None)
    ni = {y.year: y.net_income for y in got.inputs.years}
    assert (ni[2017], ni[2018], ni[2019]) == (7.0, 8.0, -12.0)
