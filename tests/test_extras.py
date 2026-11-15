import json
from dataclasses import replace
from datetime import date

import httpx
import pytest

from fakes import D, KIA_CORP, FakeDart, FakeKrx
from helpers import RUN_1114, fin_row
from vsf.data.dart import DartError, DartQuotaExceeded, FinRows
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError
from vsf.data.naver import NaverAuthError, NaverNews
from vsf.extras import gather_extras, quarterly_summary

# 가짜 DART는 회사 번호를 99+종목코드로 보므로 실행 결과의 회사 번호도 맞춰요.
_kia = RUN_1114.results["000270"]
RUN = replace(RUN_1114, results={"000270": replace(_kia, company=replace(_kia.company, corp_code=KIA_CORP))})
KIA = "000270"


def fin_q(report: str, ni: str, ni_prev: str, op: str, op_prev: str, q1: bool = False) -> FinRows:
    cur, prev = ("thstrm_amount", "frmtrm_q_amount") if q1 else ("thstrm_add_amount", "frmtrm_add_amount")

    def row(sj, aid, nm, a, b):
        r = fin_row(sj, aid, nm)
        r.update({cur: a, prev: b})
        return r
    return FinRows([row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                        "지배기업 소유주지분", ni, ni_prev),
                    row("IS", "dart_OperatingIncomeLoss", "영업이익", op, op_prev)], "CFS", "20261114000001")


def fin_q3() -> FinRows:
    return fin_q("11014", "150,000,000", "100,000,000", "250,000,000", "200,000,000")


class QuarterDart(FakeDart):
    """분기 보고서를 (연도, 보고서 코드)로 구분해서 주는 가짜 DART."""

    def __init__(self, reports=None, **kw):
        super().__init__({KIA: self.entry()}, **kw)
        self.reports = reports if reports is not None else {(2026, "11014"): fin_q3()}

    def financials(self, corp_code, year, report="11011"):
        self._enter("financials", corp_code, year, report)
        return self.reports.get((year, report))


def go(dart=None, krx=None, naver=None, codes=(KIA,), run=RUN):
    return gather_extras(list(codes), run, dart or QuarterDart(), krx or FakeKrx.default(), naver, D)


def news_http(*items: dict, status: int = 200, seen: list | None = None) -> httpx.Client:
    def handle(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        return httpx.Response(status, json={"items": list(items)})
    return httpx.Client(transport=httpx.MockTransport(handle))


def news_item(title: str, pub: str = "Fri, 13 Nov 2026 10:30:00 +0900") -> dict:
    return {"title": title, "originallink": "https://news.example/a", "link": "https://n.naver/a",
            "pubDate": pub}


def test_quarterly_label_and_values():
    q = quarterly_summary(fin_q3(), 2026, "11014")
    assert q == {"label": "2026년 3분기 누적", "net_income": 1.5, "net_income_prev": 1.0,
                 "op_income": 2.5, "op_income_prev": 2.0}


def test_quarterly_half_and_first_quarter_labels_and_fields():
    half = quarterly_summary(fin_q3(), 2026, "11012")
    assert half["label"] == "2026년 반기 누적" and half["net_income"] == 1.5
    first = quarterly_summary(fin_q("11013", "300,000,000", "100,000,000", "-50,000,000", "70,000,000", q1=True),
                              2026, "11013")
    assert first == {"label": "2026년 1분기", "net_income": 3.0, "net_income_prev": 1.0,
                     "op_income": -0.5, "op_income_prev": 0.7}


def test_no_naver_key_gives_link_only():
    e = go()[KIA]
    assert e.news == [] and e.news_link.endswith("%EA%B8%B0%EC%95%84")
    assert e.news_link.startswith("https://search.naver.com/search.naver?where=news&query=")
    assert e.notes == ()


def test_news_titles_stripped_and_unescaped():
    http = news_http(news_item("<b>기아</b> 실적"), news_item("&quot;기아&quot; &amp; <b>현대</b>"))
    got = NaverNews("i", "s", http=http).search("기아")
    assert got[0] == {"title": "기아 실적", "url": "https://news.example/a", "date": "2026-11-13"}
    assert got[1]["title"] == '"기아" & 현대'


def test_news_bad_date_left_blank_and_request_shape():
    seen: list = []
    got = NaverNews("my-id", "my-secret", http=news_http(news_item("a", pub="어제"), seen=seen)).search("기아", 3)
    assert got[0]["date"] == ""
    req = seen[0]
    assert req.headers["X-Naver-Client-Id"] == "my-id" and req.headers["X-Naver-Client-Secret"] == "my-secret"
    assert req.url.params["display"] == "3" and req.url.params["sort"] == "date"
    assert str(req.url).startswith("https://openapi.naver.com/v1/search/news.json?")


def test_news_failure_note_and_no_secret_leak():
    def boom(req):
        raise httpx.ConnectError("down")
    bad = httpx.Client(transport=httpx.MockTransport(boom))
    naver = NaverNews("my-id", "my-secret", http=bad)
    with pytest.raises(NetworkError) as err:
        naver.search("기아")
    assert "my-id" not in str(err.value) and "my-secret" not in str(err.value)
    e = go(naver=NaverNews("my-id", "my-secret", http=news_http(status=404)))[KIA]
    assert e.news == [] and e.notes == ("뉴스를 가져오지 못했어요",)
    with pytest.raises(ValueError) as err:
        NaverNews("my-id", "my-secret", http=news_http(status=404)).search("기아")
    assert "my-id" not in str(err.value) and "my-secret" not in str(err.value)


@pytest.mark.parametrize("status", [401, 403])
def test_naver_bad_key_raises_auth_error_without_the_key(status):
    with pytest.raises(NaverAuthError) as err:
        NaverNews("my-id", "my-secret", http=news_http(status=status)).search("기아")
    assert str(err.value) == f"네이버 검색 키가 맞지 않아요 (HTTP {status})"
    assert "my-id" not in str(err.value) and "my-secret" not in str(err.value)


BAD_KEY_NOTE = "네이버 검색 키가 맞지 않아 뉴스를 가져오지 못했어요. keys.toml의 [naver] 값을 확인해 주세요."


def test_naver_bad_key_is_tried_once_and_every_card_says_so():
    class BadKey:
        calls = 0

        def search(self, query, n=5):
            self.calls += 1
            raise NaverAuthError("네이버 검색 키가 맞지 않아요 (HTTP 401)")

    codes = ("000270", "000271", "000272")
    run = replace(RUN, results={c: RUN.results[KIA] for c in codes})
    naver = BadKey()
    got = go(naver=naver, codes=codes, run=run)
    assert naver.calls == 1
    for c in codes:
        assert got[c].news == [] and BAD_KEY_NOTE in got[c].notes
        assert got[c].news_link.startswith("https://search.naver.com/search.naver?where=news&query=")
    assert "뉴스를 가져오지 못했어요" not in got[KIA].notes


def test_news_success_goes_on_extras():
    e = go(naver=NaverNews("i", "s", http=news_http(news_item("기아 소식"))))[KIA]
    assert [n["title"] for n in e.news] == ["기아 소식"] and e.notes == ()


def test_disclosure_failure_isolated():
    dart = QuarterDart(raise_in={"filings": NetworkError("x")})
    e = go(dart=dart)[KIA]
    assert e.disclosures == [] and e.notes == ("최근 공시를 가져오지 못했어요",) and e.quarterly is not None


def test_disclosures_newest_first_top_ten_with_urls():
    rows = [{"rcept_dt": f"202611{d:02d}", "rcept_no": f"2026111{d:02d}0001", "report_nm": f"공시{d}"}
            for d in range(1, 13)]
    rows.append({"rcept_dt": "20261112", "rcept_no": "99999999000001", "report_nm": "같은날 나중"})
    dart = QuarterDart()
    dart._filings = rows
    got = go(dart=dart)[KIA].disclosures
    assert len(got) == 10
    assert got[0] == {"date": "2026-11-12", "title": "같은날 나중",
                      "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=99999999000001"}
    assert got[1]["title"] == "공시12" and got[-1]["title"] == "공시4"
    assert dart._log["filings"][0] == (date(2026, 8, 16), D, None, KIA_CORP)


def test_quota_gives_single_note_and_never_raises():
    dart = QuarterDart(raise_in={"filings": DartQuotaExceeded(), "financials": DartQuotaExceeded()})
    e = go(dart=dart, krx=FakeKrx.calendar())[KIA]
    assert e.notes == ("오늘 DART 호출 한도에 닿아 일부 자료를 받지 못했어요",)
    assert e.disclosures == [] and e.quarterly is None and len(e.weekly_closes) == 52


def test_other_dart_error_gets_its_own_note():
    e = go(dart=QuarterDart(raise_in={"financials": DartError("100", "x")}))[KIA]
    assert e.notes == ("분기 실적을 가져오지 못했어요",)


def test_no_quarterly_report_this_year():
    e = go(dart=QuarterDart(reports={(2025, "11014"): fin_q3()}))[KIA]
    assert e.quarterly is None and e.notes == ("올해 분기 실적이 아직 없어요",)


def test_quarterly_all_missing_same_as_none():
    empty = FinRows([fin_row("IS", "dart_OperatingIncomeLoss", "영업이익")], "CFS", "x")
    e = go(dart=QuarterDart(reports={(2026, "11012"): empty}))[KIA]
    assert e.quarterly is None and e.notes == ("올해 분기 실적이 아직 없어요",)


def test_quarterly_order_prefers_q3_then_half_then_q1():
    dart = QuarterDart(reports={(2026, "11012"): fin_q3(), (2026, "11013"): fin_q3()})
    assert go(dart=dart)[KIA].quarterly["label"] == "2026년 반기 누적"
    assert [c[2] for c in dart._log["financials"]] == ["11014", "11012"]


def test_weekly_closes_52():
    closes = go(krx=FakeKrx.calendar())[KIA].weekly_closes
    assert len(closes) == 52
    days = [d for d, _ in closes]
    assert days == sorted(days) and days[-1] == "2026-11-13"
    assert all(isinstance(c, float) for _, c in closes)


def test_weekly_closes_skip_missing_and_none():
    krx = FakeKrx.calendar()
    real = krx.daily

    def daily(day):
        rows = real(day)
        if day == date(2026, 11, 13) and rows:
            rows = {k: replace(v, close=None) for k, v in rows.items()}
        if day == date(2026, 11, 6):
            rows = {}
        return rows
    krx.daily = daily
    days = [d for d, _ in go(krx=krx)[KIA].weekly_closes]
    # 11-06이 비면 그 주는 앞 거래일(11-05)로, 11-13은 종가가 없어서 그 주가 빠져요.
    assert "2026-11-13" not in days and "2026-11-06" not in days and "2026-11-05" in days


def test_krx_failure_isolated():
    krx = FakeKrx.calendar()
    krx.week_ends = lambda until, weeks=52: (_ for _ in ()).throw(KrxError("x"))
    e = go(krx=krx)[KIA]
    assert e.weekly_closes == [] and e.notes == ("주가 흐름을 가져오지 못했어요",) and e.quarterly is not None


def test_notes_in_stable_order():
    krx = FakeKrx.calendar()
    krx.week_ends = lambda until, weeks=52: (_ for _ in ()).throw(KrxError("x"))
    dart = QuarterDart(raise_in={"filings": NetworkError("x"), "financials": DartError("100")})
    e = go(dart=dart, krx=krx, naver=NaverNews("i", "s", http=news_http(status=500)))[KIA]
    assert e.notes == ("최근 공시를 가져오지 못했어요", "분기 실적을 가져오지 못했어요",
                       "주가 흐름을 가져오지 못했어요", "뉴스를 가져오지 못했어요")


def test_code_missing_from_run_is_skipped():
    out = go(codes=("999999", KIA))
    assert list(out) == [KIA]
