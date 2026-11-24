"""백테스트: 사업보고서 원본 공시일 (2026-11-24 백테스트 설계 4장)."""
from datetime import date

from fakes import FakeDart, mem_store
from vsf.backtest.filings import annual_filing_dates

TODAY = date(2026, 11, 24)


def _row(corp: str, name: str, ymd: str) -> dict:
    return {"corp_code": corp, "report_nm": name, "rcept_dt": ymd, "rcept_no": ymd + "000001"}


def test_earliest_filing_wins_over_amendments():
    rows = [_row("C1", "[기재정정]사업보고서 (2019.12)", "20200510"), _row("C1", "사업보고서 (2019.12)", "20200330")]
    got = annual_filing_dates(FakeDart({}, filings=rows), mem_store(), range(2020, 2021), TODAY)
    assert got == {("C1", 2019): date(2020, 3, 30)}


def test_non_december_and_other_reports_are_skipped():
    rows = [_row("C2", "사업보고서 (2019.03)", "20190620"), _row("C3", "반기보고서 (2020.06)", "20200814"),
            _row("C4", "[첨부정정]사업보고서 (2020.12)", "20210401"), _row("C4", "사업보고서 (2020.12)", "20210322")]
    assert annual_filing_dates(FakeDart({}, filings=rows), mem_store(), range(2021, 2022), TODAY) == \
        {("C4", 2020): date(2021, 3, 22)}


def test_past_filing_years_are_cached():
    store = mem_store()
    rows = [_row("C1", "사업보고서 (2019.12)", "20200330")]
    first = FakeDart({}, filings=rows)
    annual_filing_dates(first, store, range(2020, 2021), TODAY)
    again = FakeDart({}, filings=rows)
    assert annual_filing_dates(again, store, range(2020, 2021), TODAY) == {("C1", 2019): date(2020, 3, 30)}
    assert again.calls_of("filings") == 0


def test_this_year_is_asked_again_each_time():
    store = mem_store()
    rows = [_row("C1", "사업보고서 (2025.12)", "20260318")]
    annual_filing_dates(FakeDart({}, filings=rows), store, range(2026, 2027), TODAY)
    again = FakeDart({}, filings=rows)
    annual_filing_dates(again, store, range(2026, 2027), TODAY)
    assert again.calls_of("filings") >= 1                  # 올해 목록은 아직 끝나지 않아서 저장하지 않아요
