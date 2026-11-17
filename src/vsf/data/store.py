"""SQLite store: API cache, call log, daily prices, meta."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class PriceRow:
    date: date
    code: str
    name: str
    market: str
    close: float | None
    shares: float | None


class Store:
    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS api_cache(
                key TEXT PRIMARY KEY, body BLOB, is_json INTEGER, fetched_at TEXT);
            CREATE TABLE IF NOT EXISTS call_log(
                day TEXT, source TEXT, n INTEGER, PRIMARY KEY(day, source));
            CREATE TABLE IF NOT EXISTS prices(
                date TEXT, code TEXT, name TEXT, market TEXT, close REAL, shares REAL,
                PRIMARY KEY(date, code));
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _put(self, key: str, body: bytes, is_json: int) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO api_cache VALUES(?,?,?,?)",
            (key, body, is_json, datetime.now().isoformat()),
        )
        self._db.commit()

    def _get(self, key: str, is_json: int) -> bytes | None:
        row = self._db.execute(
            "SELECT body FROM api_cache WHERE key=? AND is_json=?", (key, is_json)
        ).fetchone()
        return None if row is None else bytes(row[0])

    def put_json(self, key: str, body: dict | list) -> None:
        self._put(key, json.dumps(body, ensure_ascii=False).encode("utf-8"), 1)

    def get_json(self, key: str) -> dict | list | None:
        raw = self._get(key, 1)
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def put_bytes(self, key: str, body: bytes) -> None:
        self._put(key, body, 0)

    def get_bytes(self, key: str) -> bytes | None:
        return self._get(key, 0)

    def fetched_at(self, key: str) -> datetime | None:
        """When the entry was stored, as naive local time (datetime.now())."""
        row = self._db.execute(
            "SELECT fetched_at FROM api_cache WHERE key=?", (key,)
        ).fetchone()
        return None if row is None else datetime.fromisoformat(row[0])

    def delete_prefix(self, prefix: str) -> int:
        cur = self._db.execute(
            "DELETE FROM api_cache WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
        )
        self._db.commit()
        return cur.rowcount

    def count_calls(self, source: str, day: date) -> int:
        row = self._db.execute(
            "SELECT n FROM call_log WHERE day=? AND source=?", (day.isoformat(), source)
        ).fetchone()
        return 0 if row is None else row[0]

    def add_call(self, source: str, day: date) -> None:
        self._db.execute(
            "INSERT INTO call_log VALUES(?,?,1) "
            "ON CONFLICT(day, source) DO UPDATE SET n = n + 1",
            (day.isoformat(), source),
        )
        self._db.commit()

    def put_prices(self, rows: Iterable[PriceRow]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?)",
            [(r.date.isoformat(), r.code, r.name, r.market, r.close, r.shares) for r in rows],
        )
        self._db.commit()

    def get_prices(self, day: date) -> dict[str, PriceRow]:
        rows = self._db.execute(
            "SELECT code, name, market, close, shares FROM prices WHERE date=?",
            (day.isoformat(),),
        ).fetchall()
        return {c: PriceRow(day, c, n, m, cl, sh) for c, n, m, cl, sh in rows}

    def price_dates(self) -> list[date]:
        rows = self._db.execute("SELECT DISTINCT date FROM prices ORDER BY date").fetchall()
        return [date.fromisoformat(r[0]) for r in rows]

    def get_meta(self, k: str) -> str | None:
        row = self._db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return None if row is None else row[0]

    def set_meta(self, k: str, v: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))
        self._db.commit()
