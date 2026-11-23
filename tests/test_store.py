from datetime import date

from vsf.data.store import PriceRow, Store


def test_json_roundtrip_and_prefix_delete(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    s.put_json("dart:001:fin:2025", {"a": 1})
    s.put_json("dart:002:fin:2025", {"b": 2})
    assert s.get_json("dart:001:fin:2025") == {"a": 1}
    assert s.delete_prefix("dart:001:") == 1 and s.get_json("dart:001:fin:2025") is None
    assert s.fetched_at("dart:002:fin:2025") is not None


def test_json_list_and_bytes(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    s.put_json("k", [1, {"x": "한"}])
    assert s.get_json("k") == [1, {"x": "한"}]
    s.put_bytes("z", b"\x00\x01")
    assert s.get_bytes("z") == b"\x00\x01"
    assert s.get_json("z") is None and s.get_bytes("k") is None
    assert s.get_bytes("none") is None and s.fetched_at("none") is None


def test_delete_prefix_treats_wildcards_literally(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    s.put_json("a_b:1", {}); s.put_json("axb:1", {})
    assert s.delete_prefix("a_b:") == 1 and s.get_json("axb:1") == {}


def test_call_counts_per_day(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    d = date(2026, 11, 14)
    s.add_call("dart", d); s.add_call("dart", d); s.add_call("krx", d)
    assert (s.count_calls("dart", d), s.count_calls("dart", date(2026, 11, 15))) == (2, 0)


def test_prices_upsert(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    d = date(2025, 12, 30)
    s.put_prices([PriceRow(d, "000270", "기아", "KOSPI", 100.0, 10.0)])
    s.put_prices([PriceRow(d, "000270", "기아", "KOSPI", 101.0, None)])
    got = s.get_prices(d)["000270"]
    assert got.close == 101.0 and got.shares is None and s.price_dates() == [d]


def test_meta_and_persistence(tmp_path):
    p = tmp_path / "v.sqlite3"
    s = Store(p)
    assert s.get_meta("last") is None
    s.set_meta("last", "2026-11-14"); s.set_meta("last", "2026-11-15")
    assert Store(p).get_meta("last") == "2026-11-15"


# ---- 거래대금 (우선주 거래 적음 확인, 2026-11-24) ----

def test_price_value_round_trip(tmp_path):
    s = Store(tmp_path / "v.sqlite3")
    d = date(2026, 11, 20)
    s.put_prices([PriceRow(d, "005387", "현대차2우B", "KOSPI", 139500.0, 34257047.0, 2.5e9),
                  PriceRow(d, "005380", "현대차", "KOSPI", 255000.0, 203466492.0)])
    got = s.get_prices(d)
    assert got["005387"].value == 2.5e9 and got["005380"].value is None


def test_old_price_table_gets_value_column(tmp_path):
    import sqlite3
    p = tmp_path / "old.sqlite3"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE prices(date TEXT, code TEXT, name TEXT, market TEXT, close REAL, shares REAL, "
               "PRIMARY KEY(date, code))")
    db.execute("INSERT INTO prices VALUES('2026-11-13','000270','기아','KOSPI',128500,1)")
    db.commit(); db.close()
    s = Store(p)
    row = s.get_prices(date(2026, 11, 13))["000270"]
    assert row.close == 128500 and row.value is None                  # 예전 시세는 그대로
    s.put_prices([PriceRow(date(2026, 11, 14), "000270", "기아", "KOSPI", 1.0, 1.0, 5.0)])
    assert s.get_prices(date(2026, 11, 14))["000270"].value == 5.0
