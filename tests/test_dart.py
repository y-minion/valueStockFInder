"""OpenDART 클라이언트 메커니즘 테스트 (손으로 쓴 synthetic 응답 사용)."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from vsf.data.dart import DartClient, DartError, DartQuotaExceeded
from vsf.data.store import Store

SYN = Path(__file__).parent / "fixtures" / "dart" / "synthetic"
KIA_CORP = "99000270"
CHEIL_CORP = "99030000"
KEY = "K" * 40
TODAY = date(2026, 11, 14)


def _json(name):
    return json.loads((SYN / name).read_text(encoding="utf-8"))


class FakeDart:
    """경로별 응답을 돌려주고 호출을 세는 MockTransport."""

    def __init__(self, overrides=None, list_pages=None):
        self.calls = 0
        self.windows = []
        self.requests = []
        self.overrides = overrides or {}  # path 또는 (path, fs_div) -> bytes
        self.list_pages = list_pages
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, req):
        self.calls += 1
        self.requests.append(req)
        q = req.url.params
        path = req.url.path.rsplit("/", 1)[-1]
        for k in ((path, q.get("fs_div")), path):
            if k in self.overrides:
                return httpx.Response(200, content=self.overrides[k])
        if path == "corpCode.xml":
            return httpx.Response(200, content=(SYN / "corpcode.zip").read_bytes())
        if path == "company.json":
            return httpx.Response(200, json=_json("company.json"))
        if path == "fnlttSinglAcntAll.json":
            return httpx.Response(200, json=_json("fnltt_cfs.json"))
        if path == "alotMatter.json":
            return httpx.Response(200, json=_json("alot_matter.json"))
        if path == "list.json":
            self.windows.append((q["bgn_de"], q["end_de"]))
            if self.list_pages:
                return httpx.Response(200, json=self.list_pages[int(q["page_no"]) - 1])
            return httpx.Response(200, json=_json("list_page1.json"))
        raise AssertionError(path)


def body(name):
    return (SYN / name).read_bytes()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture
def transport():
    return FakeDart()


def make(store, transport, **kw):
    kw.setdefault("min_interval", 0)
    return DartClient(KEY, store, http=transport.client, today=lambda: TODAY, **kw)


@pytest.fixture
def dart(store, transport):
    return make(store, transport)


def test_corp_codes_maps_stock_code(dart):
    m = dart.corp_codes()
    assert m["000270"] == KIA_CORP and m["030000"] == CHEIL_CORP
    assert len(m) == 2  # 비상장(빈 stock_code)은 빠져요


def test_corp_codes_cached_then_refreshed_after_7_days(dart, store, transport):
    dart.corp_codes(); dart.corp_codes()
    assert transport.calls == 1
    store._db.execute("UPDATE api_cache SET fetched_at=? WHERE key='dart:corpcode'",
                      ((datetime.now() - timedelta(days=8)).isoformat(),))
    dart.corp_codes()
    assert transport.calls == 2


def test_corp_codes_xml_error_body(store):
    t = FakeDart({"corpCode.xml": body("corpcode_error_013.xml")})
    with pytest.raises(DartError) as e:
        make(store, t).corp_codes()
    assert e.value.status == "013"


def test_financials_cfs_cached(dart, transport):
    f = dart.financials(KIA_CORP, 2025)
    assert f.fs == "CFS" and f.rows and f.rcept_no == "20260310000123"
    n = transport.calls
    f2 = dart.financials(KIA_CORP, 2025)
    assert transport.calls == n and f2 == f


def test_ofs_fallback_when_cfs_missing(store):
    t = FakeDart({("fnlttSinglAcntAll.json", "CFS"): body("error_013.json")})
    f = make(store, t).financials(KIA_CORP, 2025)
    assert f.fs == "OFS" and t.calls == 2


def test_financials_none_when_both_missing(store):
    t = FakeDart({"fnlttSinglAcntAll.json": body("error_013.json")})
    assert make(store, t).financials(KIA_CORP, 2025) is None


def test_quarterly_not_cached(dart, transport):
    dart.financials(KIA_CORP, 2025, report="11013")
    dart.financials(KIA_CORP, 2025, report="11013")
    assert transport.calls == 2


def test_no_data_is_none(store):
    t = FakeDart({"alotMatter.json": body("error_013.json")})
    assert make(store, t).dividends(KIA_CORP, 2014) is None


def test_dividends_cached(dart, transport):
    rows = dart.dividends(KIA_CORP, 2025)
    assert any(r["se"] == "주당 현금배당금(원)" and r["stock_knd"] == "보통주" for r in rows)
    dart.dividends(KIA_CORP, 2025)
    assert transport.calls == 1


def test_company_cached(dart, transport):
    assert dart.company(KIA_CORP)["corp_cls"] == "Y"
    dart.company(KIA_CORP)
    assert transport.calls == 1


def test_status_020_raises(store):
    t = FakeDart({"company.json": body("error_020.json")})
    with pytest.raises(DartQuotaExceeded):
        make(store, t).company(KIA_CORP)


def test_other_status_raises_dart_error(store):
    t = FakeDart({"company.json": body("error_100.json")})
    with pytest.raises(DartError) as e:
        make(store, t).company(KIA_CORP)
    assert e.value.status == "100" and not isinstance(e.value, DartQuotaExceeded)


def test_budget_stops_before_network(store, transport):
    c = make(store, transport, daily_budget=1)
    c.company(KIA_CORP)
    with pytest.raises(DartQuotaExceeded, match="오늘 DART 호출 한도"):
        c.company(CHEIL_CORP)
    assert transport.calls == 1 and c.calls_today == 1


def test_calls_counted_only_for_network(dart, store):
    dart.company(KIA_CORP); dart.company(KIA_CORP)
    assert store.count_calls("dart", TODAY) == 1 == dart.calls_today


def test_budget_checked_before_ofs_fallback(store):
    t = FakeDart({("fnlttSinglAcntAll.json", "CFS"): body("error_013.json")})
    with pytest.raises(DartQuotaExceeded):
        make(store, t, daily_budget=1).financials(KIA_CORP, 2025)
    assert t.calls == 1


def test_filings_split_into_90_day_windows(dart, transport):
    dart.filings(date(2026, 1, 1), date(2026, 7, 19))
    assert transport.windows == [("20260101", "20260331"), ("20260401", "20260629"),
                                 ("20260630", "20260719")]


def test_filings_params_and_no_cache(dart, transport):
    rows = dart.filings(date(2026, 3, 1), date(2026, 3, 31))
    assert [r["corp_name"] for r in rows] == ["기아", "제일기획"]
    q = transport.requests[-1].url.params
    assert q["pblntf_detail_ty"] == "A001" and q["page_count"] == "100" and "corp_code" not in q
    dart.filings(date(2026, 3, 1), date(2026, 3, 31))
    assert transport.calls == 2


def test_filings_all_pages(store):
    p1 = {**_json("list_page1.json"), "page_no": 1, "total_page": 2}
    p2 = {**_json("list_page1.json"), "page_no": 2, "total_page": 2}
    p2["list"] = [{**p2["list"][0], "rcept_no": "20260325000999"}]
    t = FakeDart(list_pages=[p1, p2])
    rows = make(store, t).filings(date(2026, 3, 1), date(2026, 3, 31), corp_code=KIA_CORP)
    assert len(rows) == 3 and t.calls == 2
    assert t.requests[0].url.params["corp_code"] == KIA_CORP


def test_filings_013_is_empty(store):
    t = FakeDart({"list.json": body("error_013.json")})
    assert make(store, t).filings(date(2026, 3, 1), date(2026, 3, 31)) == []


def test_invalidate(dart, store):
    dart.financials(KIA_CORP, 2025); dart.dividends(KIA_CORP, 2025)
    dart.invalidate(KIA_CORP)
    assert store.get_json(f"dart:{KIA_CORP}:fin:2025:11011") is None
    assert store.get_json(f"dart:{KIA_CORP}:div:2025") is None


def test_min_interval_sleeps(store, transport):
    sleeps = []
    t = [100.0]
    c = DartClient(KEY, store, http=transport.client, today=lambda: TODAY,
                   min_interval=0.15, sleep=sleeps.append, clock=lambda: t[0])
    c.company(KIA_CORP)
    t[0] += 0.05
    c.dividends(KIA_CORP, 2025)
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(0.10)


def test_key_not_in_cache_keys_or_errors(store):
    t = FakeDart({"company.json": body("error_100.json")})
    c = make(store, t)
    with pytest.raises(DartError) as e:
        c.company(KIA_CORP)
    assert KEY not in str(e.value)
    c.dividends(KIA_CORP, 2025)
    keys = [r[0] for r in store._db.execute("SELECT key FROM api_cache")]
    assert keys and all(KEY not in k for k in keys)
