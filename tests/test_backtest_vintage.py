"""백테스트: 회사×사업연도 판정 묶음 (2026-11-24 백테스트 설계 4장)."""
from dataclasses import replace
from datetime import date, timedelta

import pytest
from fakes import _BASE, FakeDart, FakeKrx, _listed, corp_of, mem_store
from helpers import div_rows, settings_with
from vsf.backtest.market import Market
from vsf.backtest.vintage import build_vintages
from vsf.data.dart import DartError, DartQuotaExceeded, FinRows

FILED = date(2026, 3, 28)                 # 토요일
YEARS = range(2025, 2026)
KIA, CHEIL = _listed("000270", "기아"), _listed("030000", "제일기획")


def _krx(items=(KIA, CHEIL)) -> FakeKrx:
    """합성 연말 시세 + 2026-03-23~04-10 평일 시세."""
    days = {}
    for row in _BASE[5].values():
        days[row.date] = {x.code: replace(row, code=x.code, name=x.name) for x in items}
    d = date(2026, 3, 23)
    while d <= date(2026, 4, 10):
        if d.weekday() < 5:
            days[d] = {x.code: replace(_BASE[6], date=d, code=x.code, name=x.name) for x in items}
        d += timedelta(days=1)
    return FakeKrx(list(items), days)


def _build(dart, items=(KIA, CHEIL), filings=None, end=date(2026, 4, 30)):
    market = Market(_krx(items), mem_store(), date(2026, 3, 2), end, today=date(2026, 11, 24))
    filings = filings if filings is not None else {(corp_of(x.code), 2025): FILED for x in items}
    return build_vintages({x.code: x for x in items}, filings, YEARS, market, dart, settings_with(),
                          lambda day: None, progress=lambda s: None)


def test_vintage_starts_on_first_trading_day_after_filing():
    vintages, failures = _build(FakeDart.two_companies())
    v = vintages["000270"][0]
    assert (v.year, v.filed, v.valid_from) == (2025, FILED, date(2026, 3, 30)) and failures == []
    assert v.corp_code == corp_of("000270") and v.shares and v.dps == 6800.0 and not v.substitute
    assert set(v.verdicts) == {"지금 규칙", "배당성향 하한 없음"}


def test_vintage_after_period_end_is_not_built():
    vintages, _ = _build(FakeDart.two_companies(), filings={(corp_of("000270"), 2025): date(2026, 5, 4)})
    assert vintages == {}


def test_verdicts_per_variant():
    low = {2025: ("1,700", "1,625", "1,400"), 2023: ("1,400", "875", "750"), 2021: ("750", "250", "288"),
           2019: ("288", "225", "200"), 2017: ("200", "275", "275")}
    dart = FakeDart({"000270": FakeDart.entry(dividends={y: div_rows(*v, year=y) for y, v in low.items()})})
    v = _build(dart, items=(KIA,))[0]["000270"][0]
    assert v.verdicts["지금 규칙"].gate2 == "탈락"
    assert v.verdicts["배당성향 하한 없음"].gate2 != "탈락"
    assert v.verdicts["지금 규칙"].fair == v.verdicts["배당성향 하한 없음"].fair is not None


def _negative_eps(fin: FinRows) -> FinRows:
    rows = [{**r, **{f"{p}_amount": "-90000" for p in ("thstrm", "frmtrm", "bfefrmtrm")}}
            if "EarningsLossPerShare" in r["account_id"] else r for r in fin.rows]
    return replace(fin, rows=rows)


def test_uncomputable_fair_value_is_marked():
    fin = {y: _negative_eps(f) for y, f in {2025: _BASE[2], 2023: _BASE[3]}.items()}
    v = _build(FakeDart({"000270": FakeDart.entry(fin=fin)}), items=(KIA,))[0]["000270"][0]
    verdict = v.verdicts["지금 규칙"]
    assert verdict.uncomputable and verdict.fair is None and verdict.buy_line is None and not verdict.cheap_ok()


def test_failures_are_listed_not_raised():
    vintages, failures = _build(FakeDart.two_companies(raise_for={"030000": DartError("013", "조회된 데이타가 없습니다")}))
    assert "000270" in vintages and "030000" not in vintages
    assert [(c, y) for c, y, _ in failures] == [("030000", 2025)]


def test_quota_propagates():
    with pytest.raises(DartQuotaExceeded):
        _build(FakeDart.two_companies(quota_after=0))


def _alot_rows(year: int) -> list[dict]:
    rows = div_rows("3,000", "2,800", "2,500", year=year)
    def row(se, a, b, c):
        return {**rows[0], "se": se, "stock_knd": "", "thstrm": a, "frmtrm": b, "lwfr": c}
    return rows + [row("(연결)주당순이익(원)", "12,000", "11,000", "10,000"),
                   row("(연결)당기순이익(백만원)", "3,600,000", "3,300,000", "3,000,000")]


def test_financial_without_statements_uses_substitute():
    bank = FakeDart({"000270": FakeDart.entry(induty_code="64121", fin={},
                                              dividends={y: _alot_rows(y) for y in (2025, 2023, 2021, 2019, 2017)})})
    vintages, failures = _build(bank, items=(KIA,))
    v = vintages["000270"][0]
    assert v.substitute and failures == []
    assert v.verdicts["지금 규칙"].fair is not None and v.dps == 3000.0


def test_payer_is_assembled_in_full_even_in_a_no_dividend_year():
    divs = {**FakeDart.entry()["dividends"], 2025: div_rows("-", "6,500", "5,600")}
    v = _build(FakeDart({"000270": FakeDart.entry(dividends=divs)}), items=(KIA,))[0]["000270"][0]
    verdict = v.verdicts["지금 규칙"]
    assert verdict.gate2 == "탈락" and verdict.fair is not None and v.dps == 0.0


def test_non_payer_stays_quick_fail_without_fair_value():
    none = {y: div_rows("-", "-", "-", year=y) for y in (2025, 2023, 2021, 2019, 2017)}
    v = _build(FakeDart({"000270": FakeDart.entry(dividends=none)}), items=(KIA,))[0]["000270"][0]
    assert v.verdicts["지금 규칙"].fair is None and not v.verdicts["지금 규칙"].uncomputable


def test_non_december_company_is_a_listed_failure():
    vintages, failures = _build(FakeDart({"000270": FakeDart.entry(acc_mt="03")}), items=(KIA,))
    assert vintages == {} and failures == [("000270", 2025, "결산월이 12월이 아니에요")]
