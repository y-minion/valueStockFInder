"""KRX OPEN API 클라이언트 메커니즘 테스트 (손으로 쓴 synthetic 응답 사용)."""
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from vsf.data.krx import KrxClient, KrxError, Listed
from vsf.data.store import Store

SYN = Path(__file__).parent / "fixtures" / "krx" / "synthetic"
KEY = "KRXSECRET" + "0" * 31
TODAY = date(2026, 11, 14)
EMPTY = {"OutBlock_1": []}


def _load(name):
    return json.loads((SYN / name).read_text(encoding="utf-8"))


class FakeKrx:
    """평일(휴장일 제외)이면 synthetic 일별 자료를, 아니면 빈 응답을 주는 MockTransport."""

    def __init__(self, holidays=(), status=None, bodies=None):
        self.calls = 0
        self.requests = []
        self.holidays = {d.strftime("%Y%m%d") for d in holidays}
        self.status = status or {}  # service -> HTTP status
        self.bodies = bodies or {}  # service -> body (일별 자료를 덮어써요)
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, req):
        self.calls += 1
        self.requests.append(req)
        service = req.url.path.rsplit("/", 1)[-1]
        ymd = req.url.params["basDd"]
        if service in self.status:
            return httpx.Response(self.status[service], text="denied")
        if service in self.bodies:
            return httpx.Response(200, json=self.bodies[service])
        if service.endswith("isu_base_info"):
            return httpx.Response(200, json=_load(f"{service}_20261113.json"))
        d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
        if d.weekday() >= 5 or ymd in self.holidays:
            return httpx.Response(200, json=EMPTY)
        name = f"{service}_{ymd}.json"
        return httpx.Response(200, json=_load(name if (SYN / name).exists()
                                              else f"{service}_20261113.json"))


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "vsf.db")


def make(store, transport, **kw):
    kw.setdefault("min_interval", 0)
    kw.setdefault("today", lambda: TODAY)
    return KrxClient(KEY, store, http=transport.client, **kw)


def test_daily_merges_markets_and_parses(store):
    rows = make(store, FakeKrx()).daily(date(2025, 12, 30))
    assert rows["000270"].market == "KOSPI" and rows["000270"].close == 112000.0
    assert rows["000270"].shares == 405363347.0 and rows["000270"].name == "기아"
    assert rows["247540"].market == "KOSDAQ"
    assert rows["088980"].shares is None  # "-"
    assert rows["000270"].date == date(2025, 12, 30)


def test_request_shape_and_one_call_logged_per_request(store):
    t = FakeKrx()
    make(store, t).daily(date(2025, 12, 30))
    assert t.calls == 2 and store.count_calls("krx", TODAY) == 2
    req = t.requests[0]
    assert req.headers["AUTH_KEY"] == KEY and req.url.params["basDd"] == "20251230"
    assert str(req.url).startswith("https://data-dbg.krx.co.kr/svc/apis/sto/")
    assert KEY not in str(req.url)


def test_daily_cached_for_past_days(store):
    t = FakeKrx()
    krx = make(store, t)
    first = krx.daily(date(2025, 12, 30))
    n = t.calls
    assert krx.daily(date(2025, 12, 30)) == first and t.calls == n
    assert store.get_prices(date(2025, 12, 30))


def test_daily_today_not_cached_and_empty_not_stored(store):
    t = FakeKrx()
    krx = make(store, t)
    krx.daily(date(2026, 11, 13)); krx.daily(TODAY)  # 14일은 토요일 → 빈 응답
    assert store.price_dates() == [date(2026, 11, 13)]
    n = t.calls
    assert krx.daily(TODAY) == {} and t.calls == n + 2
    live = make(store, t, today=lambda: date(2026, 11, 13))  # 오늘 자료는 저장된 걸 쓰지 않아요
    n = t.calls
    live.daily(date(2026, 11, 13))
    assert t.calls == n + 2


@pytest.mark.parametrize("empty_market", ["stk_bydd_trd", "ksq_bydd_trd"])
def test_day_with_one_market_empty_is_not_cached(store, empty_market):
    # 한 시장만 비어 있으면 저장하지 않아요. 저장하면 다음에는 다른 시장 종목이 조용히 빠져요.
    t = FakeKrx(bodies={empty_market: EMPTY})
    krx = make(store, t)
    rows = krx.daily(date(2025, 12, 30))
    assert rows and {r.market for r in rows.values()} == {"KOSDAQ" if empty_market.startswith("stk") else "KOSPI"}
    assert store.get_prices(date(2025, 12, 30)) == {} and store.price_dates() == []
    n = t.calls
    assert krx.daily(date(2025, 12, 30)) == rows and t.calls == n + 2   # 다음에 다시 받아요


def _daily_row(code: str, close: str) -> dict:
    row = dict(_load("stk_bydd_trd_20251230.json")["OutBlock_1"][0])
    return {**row, "ISU_CD": code, "TDD_CLSPRC": close}


def test_zero_or_negative_close_is_missing(store):
    rows = [_daily_row("000001", "0"), _daily_row("000002", "-1,000"), _daily_row("000003", "0.0"),
            _daily_row("000004", "1,234")]
    t = FakeKrx(bodies={"stk_bydd_trd": {"OutBlock_1": rows}})
    got = make(store, t).daily(date(2025, 12, 30))              # 지난날(연말 종가)도 같은 방법으로 읽어요
    assert [got[c].close for c in ("000001", "000002", "000003", "000004")] == [None, None, None, 1234.0]
    assert store.get_prices(date(2025, 12, 30))["000001"].close is None


def test_zero_close_makes_collect_fail_the_stock(store):
    # KRX가 종가를 "0"으로 주면 None으로 읽고, 수집은 그 종목을 '주가 자료가 없어요'로 실패 처리해요.
    from fakes import FakeDart, noop
    from vsf.collect import collect

    rows = _load("stk_bydd_trd_20261113.json")["OutBlock_1"]
    zero = [{**r, "TDD_CLSPRC": "0"} if r["ISU_CD"] == "000270" else r for r in rows]
    t = FakeKrx(bodies={"stk_bydd_trd": {"OutBlock_1": zero}})
    c = collect(FakeDart.with_company("000270"), make(store, t), store, TODAY, progress=noop)
    assert ("000270", "기아", "주가 자료가 없어요") in c.failed and "000270" not in c.records


def test_latest_trading_day_skips_empty_days(store):
    assert make(store, FakeKrx()).latest_trading_day(date(2026, 11, 15)) == date(2026, 11, 13)


def test_latest_trading_day_includes_today(store):
    assert make(store, FakeKrx()).latest_trading_day(date(2026, 11, 13)) == date(2026, 11, 13)


def test_latest_trading_day_none_found(store):
    t = FakeKrx(holidays=[date(2026, 11, 13) - timedelta(days=i) for i in range(30)])
    with pytest.raises(KrxError, match="거래일"):
        make(store, t).latest_trading_day(date(2026, 11, 15), max_back=5)


def test_year_end(store):
    krx = make(store, FakeKrx(holidays=[date(2025, 12, 31)]))
    assert krx.year_end(2025) == date(2025, 12, 30)


def test_week_ends_distinct_and_ordered(store):
    w = make(store, FakeKrx()).week_ends(date(2026, 11, 13), 52)
    assert len(w) == 52 and w == sorted(set(w)) and w[-1] == date(2026, 11, 13)
    assert all(d.weekday() == 4 for d in w)  # 공휴일 없는 달력이면 매주 금요일


def test_week_ends_mid_week_until_and_holidays(store):
    # until=수요일 → 그 주는 수요일. 11/6 주는 금요일이 휴장이라 목요일, 10/26 주는 통째로 휴장이라 건너뛰어요.
    hol = [date(2026, 11, 6)] + [date(2026, 10, 26) + timedelta(days=i) for i in range(5)]
    w = make(store, FakeKrx(holidays=hol)).week_ends(date(2026, 11, 11), 4)
    assert w == [date(2026, 10, 16), date(2026, 10, 23), date(2026, 11, 5), date(2026, 11, 11)]


def test_unapproved_service_message(store):
    for status in (401, 403):
        t = FakeKrx(status={"stk_bydd_trd": status})
        with pytest.raises(KrxError, match="이용 승인") as e:
            make(store, t).daily(date(2025, 12, 30))
        assert "유가증권 일별매매정보" in str(e.value) and KEY not in str(e.value)


def test_unapproved_names_the_right_service(store):
    t = FakeKrx(status={"ksq_isu_base_info": 403})
    with pytest.raises(KrxError, match="코스닥 종목기본정보"):
        make(store, t).listed(date(2026, 11, 13))


def test_other_http_error_has_status_and_service_not_key(store):
    t = FakeKrx(status={"ksq_bydd_trd": 404})
    with pytest.raises(KrxError) as e:
        make(store, t).daily(date(2025, 12, 30))
    assert "404" in str(e.value) and "코스닥 일별매매정보" in str(e.value) and KEY not in str(e.value)


def test_missing_outblock_is_an_error(store):
    t = FakeKrx(bodies={"stk_bydd_trd": {"respMsg": "x"}})
    with pytest.raises(KrxError, match="유가증권 일별매매정보"):
        make(store, t).daily(date(2025, 12, 30))


def test_same_code_in_both_markets_is_an_error(store):
    row = _load("stk_bydd_trd_20251230.json")["OutBlock_1"][:1]
    t = FakeKrx(bodies={"stk_bydd_trd": {"OutBlock_1": row}, "ksq_bydd_trd": {"OutBlock_1": row}})
    with pytest.raises(KrxError, match="000270"):
        make(store, t).daily(date(2025, 12, 30))


def test_listed_parses_and_caches_past_days(store):
    t = FakeKrx()
    krx = make(store, t)
    rows = {r.code: r for r in krx.listed(date(2026, 11, 13))}
    assert rows["005935"] == Listed("005935", "삼성전자우", "KOSPI", "주권", "우선주", 815974664.0)
    assert rows["088980"].group == "부동산투자회사" and rows["088980"].shares is None
    assert rows["400001"].market == "KOSDAQ" and "스팩" in rows["400001"].name
    n = t.calls
    assert krx.listed(date(2026, 11, 13)) == list(rows.values()) and t.calls == n


def test_listed_today_is_not_cached(store):
    t = FakeKrx()
    krx = make(store, t, today=lambda: date(2026, 11, 13))
    krx.listed(date(2026, 11, 13)); n = t.calls
    krx.listed(date(2026, 11, 13))
    assert t.calls == n + 2


def test_pacing_sleeps_between_requests(store):
    now = [0.0]
    sleeps = []
    krx = KrxClient(KEY, store, http=FakeKrx().client, min_interval=0.2, today=lambda: TODAY,
                    sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
                    clock=lambda: now[0])
    krx.daily(date(2025, 12, 30))
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(0.2)


# ---- 거래대금 ----

def test_daily_parses_trading_value(store):
    rows = make(store, FakeKrx()).daily(date(2026, 11, 13))
    assert rows["000270"].value == 1_000_000.0


def test_need_value_refetches_a_cached_day_without_values_once(store):
    from vsf.data.store import PriceRow
    d = date(2026, 11, 13)
    store.put_prices([PriceRow(d, "000270", "기아", "KOSPI", 128500.0, 1.0)])   # 거래대금 칸이 생기기 전 캐시
    t = FakeKrx()
    krx = make(store, t)
    assert krx.daily(d)["000270"].value is None and t.calls == 0           # 평소엔 캐시 그대로
    assert krx.daily(d, need_value=True)["000270"].value == 1_000_000.0 and t.calls == 2
    assert krx.daily(d, need_value=True)["000270"].value == 1_000_000.0 and t.calls == 2   # 다시 저장했어요
