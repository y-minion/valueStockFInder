import logging
from dataclasses import replace
from datetime import date

from fakes import D, KIA_CORP, FakeDart, FakeKrx, _listed, mem_store, noop
from helpers import div_rows, synthetic
from vsf.collect import FISIS_FAIL_NOTE, FISIS_KEY_NOTE, NO_FIN, collect, collect_one
from vsf.data.dart import DartError, DartQuotaExceeded
from vsf.data.fisis import FisisAuthError, FisisError
from vsf.financial import CapitalRatio
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError

KIA_DIVS_2024 = div_rows("6,500", "5,600", "3,500", year=2024)


def run(dart, krx=None, store=None, today=D):
    return collect(dart, krx or FakeKrx.default(), store or mem_store(), today, progress=noop)


def test_late_filer_uses_previous_year():                    # Review Focus 1
    dart = FakeDart.with_company("000270", dividends={2024: KIA_DIVS_2024},
                                 fin={2024: synthetic(), 2022: synthetic()})   # 2025는 013
    rec = collect(dart, FakeKrx.default(), mem_store(), date(2026, 11, 14), progress=noop).records["000270"]
    assert rec[1].latest_year == 2024 and rec[1].inputs.years[4].year == 2024


def test_network_error_isolated_to_one_stock():              # Review Focus 3
    dart = FakeDart.two_companies(raise_for={"030000": NetworkError("x")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    assert "000270" in c.records and [f[0] for f in c.failed] == ["030000"]


def test_unexpected_error_isolated_to_one_stock_and_logged(caplog):
    # 화이트리스트 밖의 오류도 그 종목만 실패로 남기고, 다음 종목은 계속 처리해요.
    dart = FakeDart.two_companies(raise_for={"000270": TypeError("unsupported operand")})
    with caplog.at_level(logging.ERROR, logger="vsf.collect"):
        c = run(dart)
    assert c.failed == [("000270", "기아", "예상하지 못한 오류: TypeError: unsupported operand")]
    assert set(c.records) == {"030000"} and not c.pending
    logged = [r for r in caplog.records if r.name == "vsf.collect"]
    assert len(logged) == 1 and logged[0].exc_info[0] is TypeError and "기아(000270)" in logged[0].getMessage()


def test_quota_moves_rest_to_pending():
    c = collect(FakeDart.many(quota_after=3), FakeKrx.many(), mem_store(), D, progress=noop)
    assert len(c.records) >= 1 and c.pending and not set(c.pending) & set(c.records)
    assert len(c.records) == 3 and len(c.records) + len(c.pending) == c.total_listed == 10
    assert [code for code, _ in c.pending] == [f"{100000 + i * 10:06d}" for i in range(3, 10)]


def test_new_annual_reports_invalidate_cache():
    store = mem_store()
    store.set_meta("filings_checked", "2026-11-07")
    dart = FakeDart.default(filings=[{"corp_code": KIA_CORP}, {"corp_code": KIA_CORP}])
    collect(dart, FakeKrx.default(), store, D, progress=noop)
    assert dart.invalidated == [KIA_CORP] and store.get_meta("filings_checked") == "2026-11-14"
    assert dart._log["filings"][0][:3] == (date(2026, 11, 7), D, "A001")


def test_first_run_skips_filings_check_and_records_date():
    store, dart = mem_store(), FakeDart.default()
    collect(dart, FakeKrx.default(), store, D, progress=noop)
    assert dart.calls_of("filings") == 0 and store.get_meta("filings_checked") == "2026-11-14"


def test_exclusions_bucketed():
    c = collect(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, progress=noop)
    assert set(c.excluded) == {"우선주(보통주 없음)", "스팩", "결산월 12월 아님"} and len(c.records) == 2
    assert c.records["055550"][0].financial_kind == "그 밖"
    assert c.excluded["스팩"] == [("123450", "하나30호스팩")]


def test_financial_companies_are_analyzed_with_their_kind():
    c = run(FakeDart({"000270": FakeDart.entry(induty_code="64121")}))
    assert c.records["000270"][0].financial_kind == "은행"


def test_financial_holding_is_analyzed_as_its_kind():
    bank_holding = synthetic(defaults=False)
    c = run(FakeDart.with_company("000270", induty_code="64992", fin={2025: bank_holding, 2023: bank_holding}))
    assert c.records["000270"][0].financial_kind == "금융지주" and c.excluded == {}


def test_include_false_keeps_old_exclusions():
    c = collect(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, progress=noop,
                include_financial=False)
    assert set(c.excluded) == {"우선주(보통주 없음)", "스팩", "금융회사", "결산월 12월 아님"}
    bank_holding = synthetic(defaults=False)
    held = collect(FakeDart.with_company("000270", induty_code="64992", fin={2025: bank_holding, 2023: bank_holding}),
                   FakeKrx.default(), mem_store(), D, progress=noop, include_financial=False)
    assert held.excluded == {"금융지주": [("000270", "기아")]}
    keeps = collect(FakeDart.with_company("000270", induty_code="64992"), FakeKrx.default(), mem_store(), D,
                    progress=noop, include_financial=False)
    assert "000270" in keeps.records


def test_holding_without_statements_fails_instead_of_general_verdict():
    c = run(FakeDart.with_company("000270", induty_code="64992", fin={}))
    # 030000은 가짜 KRX 목록에는 있지만 회사 한 곳뿐인 가짜 DART에는 없어서 함께 실패해요
    assert [f for f in c.failed if f[0] == "000270"] == [("000270", "기아", NO_FIN.format(year=2025))]
    assert "000270" not in c.records


def test_quick_fail_skips_statements():
    dart = FakeDart.with_company("000270", dividends={2025: div_rows("-", "1,000", "900")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    assert c.records["000270"][1].quick_fail and dart.calls_of("financials") == 0


def test_missing_corp_code_is_a_failure_not_a_stop():
    c = run(FakeDart.with_company("000270"))     # KRX에는 030000도 있지만 DART에는 없어요
    assert "000270" in c.records
    assert c.failed == [("030000", "제일기획", "DART에서 회사 정보를 찾지 못했어요")]


def test_missing_statements_failure_names_the_year():
    c = run(FakeDart.with_company("000270", fin={}), FakeKrx.with_listed(FakeKrx.default()._listed[:1]))
    assert c.failed == [("000270", "기아", "2025년 사업보고서 재무제표가 없어요")]


def test_missing_price_is_a_failure():
    krx = FakeKrx.default()
    krx._days[date(2026, 11, 13)].pop("030000")
    c = run(FakeDart.two_companies(), krx)
    assert c.failed == [("030000", "제일기획", "주가 자료가 없어요")] and "000270" in c.records


def test_price_row_without_close_is_a_failure():
    krx = FakeKrx.default()
    day = date(2026, 11, 13)
    krx._days[day]["030000"] = replace(krx._days[day]["030000"], close=None)
    c = run(FakeDart.two_companies(), krx)
    assert c.failed == [("030000", "제일기획", "주가 자료가 없어요")] and "000270" in c.records


def test_dart_and_krx_errors_are_isolated():
    dart = FakeDart.two_companies(raise_for={"000270": DartError("100", "잘못된 요청"), "030000": KrxError("시세 오류")})
    c = run(dart)
    assert not c.records and [(f[0], f[2]) for f in c.failed] == [
        ("000270", "DART 오류 100: 잘못된 요청"), ("030000", "시세 오류")]


def test_quota_at_start_defers_every_included_stock():
    dart = FakeDart.exclusion_mix(raise_in={"corp_codes": DartQuotaExceeded()})
    c = run(dart, FakeKrx.exclusion_mix())
    assert not c.records and not c.failed and dart.calls_of("company") == 0
    assert [code for code, _ in c.pending] == ["000270", "005935", "055550", "007070"]   # 우선주도 다음에 받아요
    assert set(c.excluded) == {"스팩"}


def test_quota_during_filings_check_does_not_update_meta():
    store = mem_store()
    store.set_meta("filings_checked", "2026-11-07")
    dart = FakeDart.default(raise_in={"filings": DartQuotaExceeded()})
    c = run(dart, store=store)
    assert len(c.pending) == 2 and store.get_meta("filings_checked") == "2026-11-07"


def test_year_ends_fetched_before_stocks_and_missing_years_skipped():
    krx = FakeKrx.default()
    c = run(FakeDart.default(), krx)
    # 2016–2020은 자료가 없어서 건너뛰고, 있는 해는 종목마다 다시 받지 않아요
    assert c.records["000270"][1].inputs.years[4].per is not None
    assert krx.calls_of("listed") == 1


def test_year_end_missing_records_failed_and_absent_years():
    krx = FakeKrx.default()
    krx._days.pop(date(2023, 12, 28))                    # 2023년 마지막 거래일 자료 없음 → year_end가 KrxError

    real = krx.daily

    def daily(day):
        if (day.year, day.month) == (2024, 12):
            raise NetworkError("연결이 끊겼어요")
        return real(day)

    krx.daily = daily
    c = run(FakeDart.default(), krx)
    # 2016–2020은 가짜 KRX에 자료가 없어요. PER에 쓰일 수 있는 해(올해−6부터)만 알려요.
    assert c.year_end_missing == [2020, 2023, 2024]
    assert set(c.records) == {"000270", "030000"}
    years = c.records["000270"][1].inputs.years
    assert [y.per is None for y in years] == [False, False, True, True, False]


def test_year_end_banner_skips_years_too_old_for_per():
    krx = FakeKrx.default()
    old, recent = D.year - 8, D.year - 2
    real, seen = krx.daily, []

    def daily(day):
        seen.append(day.year)
        if day.year in (old, recent) and day.month == 12:
            raise KrxError("없어요")
        return real(day) or (real(date(2025, 12, 30)) if day.month == 12 else {})

    krx.daily = daily
    c = run(FakeDart.default(), krx)
    assert c.year_end_missing == [recent]
    assert old in seen and recent in seen             # 둘 다 시도했어요


def test_year_end_missing_empty_when_every_year_is_there():
    krx = FakeKrx.default()
    for y in range(2016, 2021):                           # 2016–2020 연말도 깔아 둬요
        krx._days[date(y, 12, 30)] = krx._days[date(2025, 12, 30)]
    assert run(FakeDart.default(), krx).year_end_missing == []


def test_progress_every_50_stocks_and_at_end():
    messages: list[str] = []
    collect(FakeDart.many(120), FakeKrx.many(120), mem_store(), D, progress=messages.append)
    assert [m.split(" ")[0] for m in messages] == ["50/120", "100/120", "120/120"]
    assert "종목 처리 중 (오늘 DART 호출 " in messages[0] and messages[0].endswith("회)")


def test_collect_one_returns_record():
    info, assembled = collect_one(FakeDart.default(), FakeKrx.default(), mem_store(), D, "000270")
    assert (info.code, info.name, info.corp_code) == ("000270", "기아", KIA_CORP)
    assert assembled.latest_year == 2025


def test_collect_one_unknown_code(): assert "찾지 못했어요" in collect_one(FakeDart.default(), FakeKrx.default(), mem_store(), D, "999999")


def test_collect_one_excluded_code_says_why():
    msg = collect_one(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, "005935")
    assert msg == "005935은(는) 분석 대상이 아니에요: 우선주(보통주 없음)"


def test_collect_one_failure_is_a_reason_text():
    dart = FakeDart.default(raise_for={"000270": NetworkError("연결이 끊겼어요")})
    assert collect_one(dart, FakeKrx.default(), mem_store(), D, "000270") == "연결이 끊겼어요"


class FakeFisis:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def capital_ratio(self, kind, names):
        self.calls.append((kind, names))
        if self.error:
            raise self.error
        return self.result


def two_banks():
    return FakeDart({"000270": FakeDart.entry(induty_code="64121"), "030000": FakeDart.entry(induty_code="64121")})


def test_collect_sets_capital_and_survives_fisis_failures():
    cap = CapitalRatio(13.2, "2026-06", "금감원 금융통계정보시스템 SA014·보통주자본비율")
    fake = FakeFisis(cap)
    c = collect(two_banks(), FakeKrx.default(), mem_store(), D, progress=noop, fisis=fake)
    assert c.records["000270"][1].capital == cap and fake.calls[0][0] == "은행"
    assert fake.calls[0][1][2] == c.records["000270"][0].name

    bad = FakeFisis(error=FisisError("x"))
    c = collect(two_banks(), FakeKrx.default(), mem_store(), D, progress=noop, fisis=bad)
    a = c.records["000270"][1]
    assert a.capital is None and FISIS_FAIL_NOTE in a.notes and c.failed == [] and len(c.records) == 2
    net = collect(two_banks(), FakeKrx.default(), mem_store(), D, progress=noop,
                  fisis=FakeFisis(error=NetworkError("x")))
    assert FISIS_FAIL_NOTE in net.records["000270"][1].notes


def test_fisis_auth_error_stops_calls_and_notes_every_financial_stock():
    fake = FakeFisis(error=FisisAuthError("금감원 FISIS 인증키가 맞지 않아요 (011)"))
    c = collect(two_banks(), FakeKrx.default(), mem_store(), D, progress=noop, fisis=fake)
    assert len(fake.calls) == 1 and len(c.records) == 2
    assert all(FISIS_KEY_NOTE in a.notes and a.capital is None for _, a in c.records.values())


def test_fisis_is_not_called_for_non_financial_or_card_stocks():
    fake = FakeFisis(CapitalRatio(1.0, "2026-06", "x"))
    c = collect(FakeDart.default(), FakeKrx.default(), mem_store(), D, progress=noop, fisis=fake)
    assert fake.calls == [] and c.records["000270"][1].capital is None
    cards = FakeDart({"000270": FakeDart.entry(induty_code="64911")})
    collect(cards, FakeKrx.default(), mem_store(), D, progress=noop, fisis=fake)
    assert fake.calls == []


def test_collect_one_passes_fisis():
    cap = CapitalRatio(13.2, "2026-06", "x")
    got = collect_one(two_banks(), FakeKrx.default(), mem_store(), D, "000270", fisis=FakeFisis(cap))
    assert got[1].capital == cap


def test_unexpected_fisis_exception_still_analyzes_stock_with_note():
    bad = FakeFisis(error=AttributeError("boom"))
    c = collect(two_banks(), FakeKrx.default(), mem_store(), D, progress=noop, fisis=bad)
    a = c.records["000270"][1]
    assert a.capital is None and FISIS_FAIL_NOTE in a.notes and c.failed == [] and len(c.records) == 2


# ---- DART가 큰 분류 코드만 주는 회사 ----

def _coarse(induty_code: str, corp_name: str = "기아", fin=None) -> FakeDart:
    entry = FakeDart.entry(induty_code=induty_code, fin=fin)
    entry["company"] = {**entry["company"], "corp_name": corp_name, "stock_name": corp_name}
    return FakeDart({"000270": entry})


def test_coarse_649_with_current_assets_is_a_general_company():
    c = run(_coarse("649"))                         # 기본 합성 재무제표에는 유동자산이 있어요
    assert c.records["000270"][0].financial_kind is None and c.excluded == {}


def test_coarse_649_without_current_assets_is_a_financial_holding():
    holding = synthetic(defaults=False)
    for code in ("649", "64999", "64991"):
        c = run(_coarse(code, fin={2025: holding, 2023: holding}))
        assert c.records["000270"][0].financial_kind == "금융지주" and c.excluded == {}


def test_coarse_661_broker_by_name_else_general():
    assert run(_coarse("661", "다올투자증권")).records["000270"][0].financial_kind == "증권"
    assert run(_coarse("661", "NHN KCP")).records["000270"][0].financial_kind is None
    assert run(_coarse("66202", "에이플러스에셋")).records["000270"][0].financial_kind is None


def test_coarse_codes_still_excluded_when_financials_are_off():
    holding = synthetic(defaults=False)
    for dart in (_coarse("649"), _coarse("649", fin={2025: holding, 2023: holding}),
                 _coarse("661", "다올투자증권"), _coarse("661", "NHN KCP"), _coarse("66202")):
        c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop, include_financial=False)
        assert c.excluded == {"금융회사": [("000270", "기아")]} and "000270" not in c.records


def test_skipped_dividend_year_now_gets_full_calculation():
    """전 해에만 배당을 쉰 종목은 재무제표를 받아 계산기를 끝까지 돌려요. 관문 ②는 계산기가 스스로 탈락시켜요."""
    from pathlib import Path as _P

    from vsf.config import load_settings
    from vsf.evaluate import evaluate_one
    dart = FakeDart.with_company("000270", dividends={2025: div_rows("1,000", "-", "900")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    info, a = c.records["000270"]
    assert not a.quick_fail and dart.calls_of("financials") >= 1
    settings = load_settings(_P(__file__).resolve().parents[1] / "settings.toml")
    assert evaluate_one(info, a, settings, None).summary.gate2 == "탈락"


def test_other_financial_is_judged_with_capital_to_check():
    from pathlib import Path as _P

    from vsf.config import load_settings
    from vsf.evaluate import evaluate_one
    c = run(FakeDart({"000270": FakeDart.entry(induty_code="64201")}))
    info, a = c.records["000270"]
    r = evaluate_one(info, a, load_settings(_P(__file__).resolve().parents[1] / "settings.toml"), None)
    assert info.financial_kind == "그 밖" and r.financial.capital_min is None
    assert r.cells["F_CAP_D"] == "직접 확인" and "자본비율" in r.cells["C131"]



# ---- 우선주 (2026-11-24 우선주 설계 3장) ----

def _pref_divs():
    from helpers import _SYN_DPS
    plus = lambda v: v if v.strip() in ("-", "") else f"{int(v.replace(',', '')) + 50:,}"   # noqa: E731
    return {y: div_rows(*v, year=y, pref=tuple(plus(x) for x in v)) for y, v in _SYN_DPS.items()}


def test_preferred_share_is_collected_with_company_financials_and_its_own_dividends():
    dart = FakeDart({"000270": FakeDart.entry(dividends=_pref_divs()), "030000": FakeDart.entry()})
    c = collect(dart, FakeKrx.with_preferred(), mem_store(), D, progress=noop)
    info, a = c.records["000275"]
    common = c.records["000270"][1]
    assert info.common_code == "000270" and info.name == "기아우" and info.corp_code == "99000270"
    assert [y.dps for y in a.inputs.years] == [None if y.dps is None else y.dps + 50 for y in common.inputs.years]
    assert [y.eps for y in a.inputs.years] == [y.eps for y in common.inputs.years]
    assert not any(code == "000275" for v in c.excluded.values() for code, _ in v)


def test_preferred_without_a_listed_common_is_excluded():
    c = collect(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, progress=noop)
    assert c.excluded["우선주(보통주 없음)"] == [("005935", "삼성전자우")]


def test_preferred_of_an_excluded_common_takes_the_common_reason():
    # 스팩의 우선주는 스팩으로 빠져요. 보통주가 빠지는 회사를 우선주로 다시 분석하지 않아요.
    krx = FakeKrx.with_listed([_listed("000270", "기아"), _listed("123450", "하나30호스팩"),
                               _listed("123455", "하나30호스팩우", kind="우선주")])
    c = collect(FakeDart({"000270": FakeDart.entry()}), krx, mem_store(), D, progress=noop)
    assert c.excluded["스팩"] == [("123450", "하나30호스팩"), ("123455", "하나30호스팩우")]
    assert collect_one(FakeDart({}), krx, mem_store(), D, "123455") == "123455은(는) 분석 대상이 아니에요: 스팩"


def test_quota_defers_preferred_to_pending():
    dart = FakeDart({"000270": FakeDart.entry(dividends=_pref_divs()), "030000": FakeDart.entry()}, quota_after=1)
    c = collect(dart, FakeKrx.with_preferred(), mem_store(), D, progress=noop)
    assert "000270" in c.records and "000275" not in c.records
    assert ("000275", "기아우") in c.pending and ("030000", "제일기획") in c.pending


def test_collect_one_handles_a_preferred_code():
    dart = FakeDart({"000270": FakeDart.entry(dividends=_pref_divs())})
    got = collect_one(dart, FakeKrx.with_preferred(), mem_store(), D, "000275")
    assert not isinstance(got, str) and got[0].common_code == "000270"


def test_preferred_quick_fail_uses_preferred_dividend():
    divs = _pref_divs()
    divs[2025] = div_rows("6,800", "6,500", "5,600", pref=("-", "6,550", "5,650"))
    dart = FakeDart({"000270": FakeDart.entry(dividends=divs), "030000": FakeDart.entry()})
    c = collect(dart, FakeKrx.with_preferred(), mem_store(), D, progress=noop)
    assert c.records["000275"][1].quick_fail and not c.records["000270"][1].quick_fail


def test_company_founding_date_is_kept_for_dividend_years():
    dart = FakeDart({"000270": FakeDart.entry(est_dt="20170302")})
    info, _ = collect_one(dart, FakeKrx.default(), mem_store(), D, "000270")
    assert info.est_dt == "20170302"


# ---- 사업연도를 받아 조립하기 (2026-11-24 백테스트 플랜 Task 4) ----

from fakes import SYN_PRICE_DATE, _DEFAULT_DIVS  # noqa: E402
from vsf.collect import assemble_for_year, context_for  # noqa: E402


def _kia_item(krx):
    return next(x for x in krx.listed(SYN_PRICE_DATE) if x.code == "000270")


def test_assemble_for_year_can_skip_quick_fail():
    divs = {**_DEFAULT_DIVS, 2025: div_rows("-", "6,500", "5,600")}           # 최근 해 배당 0
    dart = FakeDart({"000270": FakeDart.entry(dividends=divs)})
    krx = FakeKrx.default()
    ctx = context_for(dart, krx, SYN_PRICE_DATE, dart.corp_codes())
    assert assemble_for_year(ctx, _kia_item(krx), 2025)[1].quick_fail is True
    full = assemble_for_year(ctx, _kia_item(krx), 2025, quick_fail=False)[1]
    assert full.quick_fail is False and full.inputs.years[-1].eps is not None


def test_assemble_for_year_uses_the_given_year_and_prefetched_dividends():
    dart = FakeDart({"000270": FakeDart.entry()})
    krx = FakeKrx.default()
    ctx = context_for(dart, krx, SYN_PRICE_DATE, dart.corp_codes())
    info, got = assemble_for_year(ctx, _kia_item(krx), 2025, divs=_DEFAULT_DIVS[2025])
    assert info.code == "000270" and got.latest_year == 2025 and not got.quick_fail
    assert dart.calls_of("dividends") == 4                 # 2023·2021·2019·2017만 받아요 (2025는 받은 걸 써요)


def test_context_for_uses_that_days_prices_and_year_ends():
    krx = FakeKrx.default()
    ctx = context_for(FakeDart.default(), krx, SYN_PRICE_DATE, {})
    assert ctx.today == ctx.price_date == SYN_PRICE_DATE and "000270" in ctx.prices
    assert set(ctx.year_ends) == {2021, 2022, 2023, 2024, 2025}
