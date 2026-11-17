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


def news_item(title: str, pub: str = "Fri, 13 Nov 2026 10:30:00 +0900", link: str = "https://n.naver/a") -> dict:
    return {"title": title, "originallink": "https://news.example/a", "link": link, "pubDate": pub}


def test_quarterly_label_and_values():
    q = quarterly_summary(fin_q3(), 2026, "11014")
    assert q == {"label": "2026년 3분기 누적", "net_income": 1.5, "net_income_prev": 1.0,
                 "op_income": 2.5, "op_income_prev": 2.0, "eps": None, "eps_prev": None,
                 "year": 2026, "quarter": 3}


def test_quarterly_half_and_first_quarter_labels_and_fields():
    half = quarterly_summary(fin_q3(), 2026, "11012")
    assert half["label"] == "2026년 반기 누적" and half["net_income"] == 1.5
    first = quarterly_summary(fin_q("11013", "300,000,000", "100,000,000", "-50,000,000", "70,000,000", q1=True),
                              2026, "11013")
    assert first == {"label": "2026년 1분기", "net_income": 3.0, "net_income_prev": 1.0,
                     "op_income": -0.5, "op_income_prev": 0.7, "eps": None, "eps_prev": None,
                     "year": 2026, "quarter": 1}


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
    # 개발자센터는 2026-07-31부터 검색 API 새 키를 안 내줘요. 새 키는 NAVER API HUB용이에요.
    assert req.headers["X-NCP-APIGW-API-KEY-ID"] == "my-id" and req.headers["X-NCP-APIGW-API-KEY"] == "my-secret"
    assert "X-Naver-Client-Id" not in req.headers and "X-Naver-Client-Secret" not in req.headers
    # 관련도순으로 넉넉히 받아요. 최신순이면 '기아'·'KT'처럼 야구단과 이름이 같은 회사는 경기 기사뿐이에요.
    assert req.url.params["display"] == "100" and req.url.params["sort"] == "sim"
    assert str(req.url).startswith("https://naverapihub.apigw.ntruss.com/search/v1/news?")


def test_news_skips_sports_entertainment_and_repeated_titles():
    items = [news_item("KT 위즈 우승", link="https://m.sports.naver.com/kbaseball/article/1"),
             news_item("KT 광고 모델", link="https://m.entertain.naver.com/article/2"),
             news_item("KT, 3분기 실적 발표"),
             news_item("KT 3분기 실적 발표!"),            # 기호만 다른 같은 제목
             news_item("KT, 배당 늘린다")]
    got = NaverNews("i", "s", http=news_http(*items)).search("KT")
    assert [g["title"] for g in got] == ["KT, 3분기 실적 발표", "KT, 배당 늘린다"]


def test_news_keeps_the_n_most_relevant_and_lists_them_newest_first():
    items = [news_item("가", pub="Wed, 11 Nov 2026 09:00:00 +0900"),
             news_item("나", pub="Fri, 13 Nov 2026 09:00:00 +0900"),
             news_item("다", pub="Thu, 12 Nov 2026 09:00:00 +0900"),
             news_item("라", pub="Sat, 14 Nov 2026 09:00:00 +0900")]   # 관련도 4위라서 3개만 고르면 빠져요
    got = NaverNews("i", "s", http=news_http(*items)).search("기아", 3)
    assert [g["title"] for g in got] == ["나", "다", "가"]


def test_news_takes_one_per_day_before_a_second_from_the_same_day():
    # 같은 사건 기사는 같은 날 몰려요. 날짜별로 돌아가며 골라서 다른 날 소식도 보이게 해요.
    d15, d13, d12 = ("Sun, 15 Nov 2026 09:00:00 +0900", "Fri, 13 Nov 2026 09:00:00 +0900",
                     "Thu, 12 Nov 2026 09:00:00 +0900")
    items = [news_item("A", pub=d15), news_item("B", pub=d15), news_item("C", pub=d15),
             news_item("D", pub=d13), news_item("E", pub=d12)]
    got = NaverNews("i", "s", http=news_http(*items)).search("기아", 3)
    assert [g["title"] for g in got] == ["A", "D", "E"]
    few = [news_item("A", pub=d15), news_item("B", pub=d15), news_item("C", pub=d13)]
    got = NaverNews("i", "s", http=news_http(*few)).search("기아", 3)
    assert [g["title"] for g in got] == ["A", "B", "C"]      # 날짜가 모자라면 같은 날에서 더 골라요


def test_news_json_body_sent_as_text_plain_is_read():
    # NAVER API HUB는 JSON 본문을 text/plain으로 보내요 (2026-11-15 실제 응답).
    body = json.dumps({"items": [news_item("기아 실적")]}, ensure_ascii=False).encode()
    http = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers={"content-type": "text/plain;charset=UTF-8"})))
    assert NaverNews("i", "s", http=http).search("기아")[0]["title"] == "기아 실적"


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


# ---- 최근 4분기 EPS로 본 매수선 (판정은 안 바꾸고 경고만) ----

from vsf.extras import recent_row  # noqa: E402


def fin_q_eps(eps: str, eps_prev: str, q1: bool = False) -> FinRows:
    """분기 보고서에 기본주당이익 줄을 더한 것 (파트론 2026년 3분기: 누적 185원, 작년 같은 때 407원)."""
    fin = fin_q("11014", "9,166,000,000", "20,436,000,000", "22,364,000,000", "29,234,000,000", q1=q1)
    cur, prev = ("thstrm_amount", "frmtrm_q_amount") if q1 else ("thstrm_add_amount", "frmtrm_add_amount")
    row = fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", "기본주당이익")
    row.update({cur: eps, prev: eps_prev})
    return FinRows(fin.rows + [row], fin.fs, fin.rcept_no)


def partron_q3() -> dict:
    return quarterly_summary(fin_q_eps("185", "407"), 2026, "11014")


def test_quarterly_summary_reads_cumulative_eps_and_period():
    q = partron_q3()
    assert (q["eps"], q["eps_prev"], q["year"], q["quarter"]) == (185.0, 407.0, 2026, 3)
    first = quarterly_summary(fin_q_eps("203", "136", q1=True), 2026, "11013")
    assert (first["eps"], first["eps_prev"], first["quarter"]) == (203.0, 136.0, 1)
    assert quarterly_summary(fin_q3(), 2026, "11012")["quarter"] == 2


def test_recent_row_uses_last_four_quarters_like_the_eps_table():
    # 2025년 EPS 674 + 2026년 1~3분기 185 − 2025년 1~3분기 407 = 452
    r = recent_row(partron_q3(), latest_year=2025, latest_eps=674.0, b118=10.0, price=3790.0,
                   safety_margin=0.25, gate3="통과")
    assert r["label"] == "최근 4분기 (2025년 4분기~2026년 3분기)"
    assert r["eps"] == 452.0 and r["fair"] == 4520.0 and r["buy_line"] == 3390.0
    assert r["ratio"] == pytest.approx(3790 / 4520) and r["verdict"] == "제값"
    assert r["warning"] == ("최근 4분기 EPS 452원으로 보면 매수선이 3,390원이라 지금 주가 3,790원보다 낮아요. "
                            "계산기는 연간 실적만 봐서 아직 반영하지 못했어요.")


def test_recent_row_span_for_half_and_first_quarter():
    half = dict(partron_q3(), quarter=2)
    first = dict(partron_q3(), quarter=1)
    kw = dict(latest_year=2025, latest_eps=674.0, b118=10.0, price=3790.0, safety_margin=0.25, gate3="통과")
    assert recent_row(half, **kw)["label"] == "최근 4분기 (2025년 3분기~2026년 2분기)"
    assert recent_row(first, **kw)["label"] == "최근 4분기 (2025년 2분기~2026년 1분기)"


def test_no_warning_when_still_cheap_or_gate3_not_passed():
    kw = dict(latest_year=2025, latest_eps=674.0, b118=10.0, safety_margin=0.25)
    cheap = recent_row(partron_q3(), price=3000.0, gate3="통과", **kw)
    assert cheap["verdict"] == "싸요" and cheap["warning"] is None
    assert recent_row(partron_q3(), price=3790.0, gate3="탈락", **kw)["warning"] is None


def test_loss_over_four_quarters_has_no_fair_value_and_warns():
    q = dict(partron_q3(), eps=-900.0)       # 674 − 900 − 407 = −633
    r = recent_row(q, latest_year=2025, latest_eps=674.0, b118=10.0, price=3790.0,
                   safety_margin=0.25, gate3="통과")
    assert r["eps"] == -633.0 and r["ratio"] is None and r["verdict"] is None
    assert r["warning"] == ("최근 4분기 EPS가 −633원(적자)이라 이 기준으로는 매수선이 없어요. "
                            "계산기는 연간 실적만 봐서 아직 반영하지 못했어요.")


@pytest.mark.parametrize("change", [
    dict(latest_year=2024),                  # 연간 보고서와 분기 보고서 사이에 빈 해가 있으면 이어 붙일 수 없어요
    dict(latest_eps=None), dict(b118=None), dict(price=None),
])
def test_recent_row_needs_adjacent_years_and_numbers(change):
    kw = dict(latest_year=2025, latest_eps=674.0, b118=10.0, price=3790.0, safety_margin=0.25, gate3="통과")
    assert recent_row(partron_q3(), **(kw | change)) is None
    assert recent_row(dict(partron_q3(), eps=None), **kw) is None
    assert recent_row(None, **kw) is None


def test_gather_extras_attaches_recent_row():
    e = go(dart=QuarterDart(reports={(2026, "11014"): fin_q_eps("15,000", "14,000")}))[KIA]
    kia = RUN.results[KIA]
    assert e.recent["eps"] == kia.cells["B123"] + 1000
    assert e.recent["verdict"] == "싸요" and e.recent["warning"] is None
    assert go()[KIA].recent is None          # EPS 줄이 없는 분기 보고서


def test_quarter_year_follows_the_latest_annual_report():
    """2027년 2월엔 2026년 사업보고서가 아직 없으니 2026년 3분기 누적을 써요."""
    dart = QuarterDart(reports={(2026, "11014"): fin_q_eps("15,000", "14,000")})
    e = gather_extras([KIA], RUN, dart, FakeKrx.default(), None, date(2027, 2, 10))[KIA]
    assert e.quarterly["label"] == "2026년 3분기 누적" and e.recent is not None
