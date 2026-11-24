"""백테스트: 회사×사업연도 판정 묶음 (2026-11-24 백테스트 설계 4장)."""
from dataclasses import replace
from datetime import date, timedelta

import pytest
from fakes import _BASE, FakeDart, FakeKrx, _listed, corp_of, mem_store
from helpers import div_rows, settings_with
from vsf.backtest.market import Market
from vsf.backtest.vintage import build_vintages
from vsf.config import BacktestSettings
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


def _build(dart, items=(KIA, CHEIL), filings=None, end=date(2026, 4, 30), krx=None):
    market = Market(krx or _krx(items), mem_store(), date(2026, 3, 2), end, today=date(2026, 11, 24))
    filings = filings if filings is not None else {(corp_of(x.code), 2025): FILED for x in items}
    return build_vintages({x.code: x for x in items}, filings, YEARS, market, dart, settings_with(),
                          lambda day: None, progress=lambda s: None)


def test_vintage_starts_on_first_trading_day_after_filing():
    vintages, failures = _build(FakeDart.two_companies())
    v = vintages["000270"][0]
    assert (v.year, v.filed, v.valid_from) == (2025, FILED, date(2026, 3, 30)) and failures == []
    assert v.corp_code == corp_of("000270") and v.shares and v.dps == 6800.0 and not v.substitute
    assert set(v.verdicts) == {x.name for x in BacktestSettings().variants}


def test_report_filed_on_a_trading_day_starts_the_next_trading_day():
    # 사업보고서는 장 마감 뒤에도 올라와요. 공시일 종가로는 아직 볼 수 없었으니 다음 거래일부터 써요.
    filed = date(2026, 3, 30)                                   # 월요일 (거래일)
    vintages, _ = _build(FakeDart.two_companies(), filings={(corp_of("000270"), 2025): filed})
    v = vintages["000270"][0]
    assert (v.filed, v.valid_from) == (filed, date(2026, 3, 31))


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
    market = Market(_krx((KIA,)), mem_store(), date(2026, 3, 2), date(2026, 4, 30), today=date(2026, 11, 24))
    vintages, failures = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market, bank,
                                        settings_with(), lambda day: _RoeFisis({2024: 9.0, 2025: 9.5}),
                                        progress=lambda s: None)
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


def _no_current_assets(fin: FinRows) -> FinRows:
    return replace(fin, rows=[r for r in fin.rows if r["account_id"] != "ifrs-full_CurrentAssets"])


def test_financial_holding_is_recognised_from_statements_filed_after_the_period():
    # 금융지주(64992)는 유동자산이 없는 재무상태표로 가려요. 그해 표가 없으면 지금 해까지의 표로 회사 종류만 봐요.
    holding = FakeDart({"000270": FakeDart.entry(induty_code="64992", fin={2026: _no_current_assets(_BASE[2])},
                                                 dividends={y: _alot_rows(y) for y in (2025, 2023, 2021, 2019, 2017)})})
    market = Market(_krx((KIA,)), mem_store(), date(2026, 3, 2), date(2026, 4, 30), today=date(2027, 6, 1))
    vintages, failures = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market, holding,
                                        settings_with(), lambda day: _RoeFisis({2025: 9.0}), progress=lambda s: None)
    assert failures == [] and vintages["000270"][0].substitute


class _RoeFisis:
    """은행 ROE만 주는 가짜 FISIS (자본비율은 없음)."""
    def __init__(self, roe: dict[int, float]):
        self.roe = roe

    def annual_values(self, part_div, names, list_no, account, y0, y1):
        return {y: v for y, v in self.roe.items() if y0 <= y <= y1}

    def capital_ratio(self, kind, names):
        return None


def test_substitute_without_any_roe_is_not_built():
    # 과거 ROE를 하나도 못 구한 금융회사는 관문 ①을 '확인 필요'로 공짜 통과하지 않게 묶음을 만들지 않아요.
    bank = FakeDart({"000270": FakeDart.entry(induty_code="64121", fin={},
                                              dividends={y: _alot_rows(y) for y in (2025, 2023, 2021, 2019, 2017)})})
    market = Market(_krx((KIA,)), mem_store(), date(2026, 3, 2), date(2026, 4, 30), today=date(2026, 11, 24))
    vintages, failures = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market, bank,
                                        settings_with(), lambda day: None, progress=lambda s: None)
    assert vintages == {} and failures == [("000270", 2025, "과거 ROE 자료가 없는 금융회사예요 (대체 자료)")]
    with_roe, failures = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market, bank,
                                        settings_with(), lambda day: _RoeFisis({2023: 9.0, 2024: 9.5, 2025: 10.0}),
                                        progress=lambda s: None)
    assert failures == [] and with_roe["000270"][0].substitute


def test_preferred_of_an_excluded_common_is_skipped():
    # 우선주는 보통주가 빠지는 사유(리츠·스팩·외국 회사 등)를 따라가요.
    reit, pref = _listed("000270", "기아", group="부동산투자회사"), _listed("000275", "기아우", kind="구형우선주")
    vintages, failures = _build(FakeDart.two_companies(), items=(reit, pref),
                                filings={(corp_of("000270"), 2025): FILED})
    assert vintages == {} and failures == []

def _shares_doubled(close_after: float) -> FakeKrx:
    """2025년 말 종가 60,000원 → 2026-03-23부터 주식 수 두 배, 종가 close_after."""
    krx = _krx((KIA,))
    end = _BASE[5][2025].date
    krx._days[end]["000270"] = replace(krx._days[end]["000270"], close=60_000.0)
    for d, rows in krx._days.items():
        if d >= date(2026, 3, 23):
            rows["000270"] = replace(rows["000270"], shares=rows["000270"].shares * 2, close=close_after)
    return krx


def test_share_jump_after_year_end_blocks_buying_unless_the_price_confirms_a_split():
    # 연말 뒤 주식 수가 두 배인데 주가가 그대로면 유상증자·합병 같은 일이에요. 주당 숫자가 지금 주식 수와 안 맞아서
    # 이 묶음으로는 사지 않아요. 주가도 반이 됐으면 분할이라 조립이 이미 맞췄어요.
    unconfirmed = _build(FakeDart.two_companies(), items=(KIA,), krx=_shares_doubled(60_000.0))[0]["000270"][0]
    split = _build(FakeDart.two_companies(), items=(KIA,), krx=_shares_doubled(30_000.0))[0]["000270"][0]
    plain = _build(FakeDart.two_companies(), items=(KIA,))[0]["000270"][0]
    assert unconfirmed.blocked and not split.blocked and not plain.blocked


def test_substitute_bundle_with_a_share_jump_is_blocked_even_for_a_split():
    # 금융회사 대체 자료는 분할 조정을 하지 않아요. 주식 수가 크게 바뀐 해가 있으면 그 묶음으로는 사지 않아요.
    bank = FakeDart({"000270": FakeDart.entry(induty_code="64121", fin={},
                                              dividends={y: _alot_rows(y) for y in (2025, 2023, 2021, 2019, 2017)})})
    market = Market(_shares_doubled(30_000.0), mem_store(), date(2026, 3, 2), date(2026, 4, 30), today=date(2026, 11, 24))
    vintages, failures = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market, bank,
                                        settings_with(), lambda day: _RoeFisis({2024: 9.0, 2025: 9.5}),
                                        progress=lambda s: None)
    v = vintages["000270"][0]
    assert failures == [] and v.substitute and v.blocked


def test_variant_overrides_win_over_industry_overrides():
    # 업종 기준값이 배당성향 하한을 0.5로 올려도, '배당성향 하한 없음' 변형은 그 업종에서도 하한 없이 봐요.
    market = Market(_krx((KIA,)), mem_store(), date(2026, 3, 2), date(2026, 4, 30), today=date(2026, 11, 24))
    vintages, _ = build_vintages({"000270": KIA}, {(corp_of("000270"), 2025): FILED}, YEARS, market,
                                 FakeDart.two_companies(), settings_with(overrides={"30": {"payout_min": 0.5}}),
                                 lambda day: None, progress=lambda s: None)
    v = vintages["000270"][0].verdicts
    assert v["지금 규칙"].gate2 == "탈락" and v["배당성향 하한 없음"].gate2 != "탈락"

LOWER = "정상 EPS = 5년 평균과 최근 해 중 낮은 값"


def _low_latest_eps(fin: FinRows) -> FinRows:
    """A 보고서의 당기 EPS만 1,000원으로 (실적이 꺾인 해)."""
    rows = [{**r, "thstrm_amount": "1000"} if "EarningsLossPerShare" in r["account_id"] else r for r in fin.rows]
    return replace(fin, rows=rows)


def test_lower_normal_eps_variant_uses_the_lower_of_average_and_latest():
    # 실적이 꺾인 해에는 5년 평균보다 최근 해 EPS가 낮아요. 이 변형은 낮은 쪽으로 적정가를 계산해요.
    fin = {2025: _low_latest_eps(_BASE[2]), 2023: _BASE[3]}
    fell = _build(FakeDart({"000270": FakeDart.entry(fin=fin)}), items=(KIA,))[0]["000270"][0].verdicts
    assert fell[LOWER].fair < fell["지금 규칙"].fair
    usual = _build(FakeDart.two_companies(), items=(KIA,))[0]["000270"][0].verdicts
    assert usual[LOWER].fair == usual["지금 규칙"].fair                  # 최근 해가 평균보다 높으면 같아요
