"""OpenDART 클라이언트: 캐시, 하루 호출 한도, 요청 간격."""
from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from lxml import etree

from vsf.data.http import get_with_retry
from vsf.data.store import Store

BASE = "https://opendart.fss.or.kr/api/"
CORPCODE_TTL = timedelta(days=7)
QUOTA_MESSAGE = "오늘 DART 호출 한도에 가까워 멈췄어요. 내일 다시 실행하면 이어서 받아요."


class DartError(Exception):
    def __init__(self, status: str, message: str = "") -> None:
        super().__init__(f"DART 오류 {status}: {message}" if message else f"DART 오류 {status}")
        self.status = status


class DartQuotaExceeded(DartError):
    def __init__(self, message: str = QUOTA_MESSAGE, status: str = "020") -> None:
        Exception.__init__(self, message)
        self.status = status


@dataclass(frozen=True)
class FinRows:
    rows: list[dict]
    fs: Literal["CFS", "OFS"]
    rcept_no: str


class DartClient:
    def __init__(
        self,
        api_key: str,
        store: Store,
        http: httpx.Client | None = None,
        daily_budget: int = 19000,
        min_interval: float = 0.15,
        today: Callable[[], date] = date.today,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key = api_key
        self._store = store
        self._http = http or httpx.Client(timeout=30)
        self._budget = daily_budget
        self._min_interval = min_interval
        self._today = today
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    @property
    def calls_today(self) -> int:
        return self._store.count_calls("dart", self._today())

    def _request(self, endpoint: str, **params) -> httpx.Response:
        if self.calls_today >= self._budget:
            raise DartQuotaExceeded(QUOTA_MESSAGE)
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = get_with_retry(self._http, BASE + endpoint,
                                  params={"crtfc_key": self._key, **params})
        finally:
            self._last = self._clock()
            self._store.add_call("dart", self._today())
        if resp.status_code != 200:
            raise DartError(f"http-{resp.status_code}", f"{endpoint} 요청이 거절됐어요")
        return resp

    @staticmethod
    def _check(status: str, message: str) -> bool:
        """True면 정상, False면 데이터 없음(013). 그 밖은 예외."""
        if status == "000":
            return True
        if status == "013":
            return False
        if status == "020":
            raise DartQuotaExceeded(f"DART 요청 제한을 넘었어요: {message}", status)
        raise DartError(status, message)

    def _json(self, endpoint: str, **params) -> dict | None:
        data = self._request(endpoint, **params).json()
        return data if self._check(data.get("status", ""), data.get("message", "")) else None

    def corp_codes(self) -> dict[str, str]:
        key = "dart:corpcode"
        raw = self._store.get_bytes(key)
        at = self._store.fetched_at(key)
        if raw is None or at is None or datetime.now() - at > CORPCODE_TTL:
            raw = self._request("corpCode.xml").content
            if not zipfile.is_zipfile(io.BytesIO(raw)):
                root = etree.fromstring(raw)
                status, message = root.findtext("status", ""), root.findtext("message", "")
                self._check(status, message)
                raise DartError(status or "corpCode", message or "corpCode.xml 응답이 zip이 아니에요")
            self._store.put_bytes(key, raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read("CORPCODE.xml")
        out: dict[str, str] = {}
        for item in etree.fromstring(xml).iter("list"):
            stock = (item.findtext("stock_code") or "").strip()
            if stock:
                out[stock] = (item.findtext("corp_code") or "").strip()
        return out

    def company(self, corp_code: str) -> dict | None:
        key = f"dart:{corp_code}:company"
        cached = self._store.get_json(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = self._json("company.json", corp_code=corp_code)
        if data is not None:
            self._store.put_json(key, data)
        return data

    def financials(self, corp_code: str, year: int, report: str = "11011") -> FinRows | None:
        key = f"dart:{corp_code}:fin:{year}:{report}"
        cacheable = report == "11011"
        if cacheable:
            c = self._store.get_json(key)
            if c is not None:
                return FinRows(c["rows"], c["fs"], c["rcept_no"])  # type: ignore[index]
        for fs in ("CFS", "OFS"):
            data = self._json("fnlttSinglAcntAll.json", corp_code=corp_code,
                              bsns_year=str(year), reprt_code=report, fs_div=fs)
            if data is None or not data.get("list"):
                continue
            rows = data["list"]
            result = FinRows(rows, fs, rows[0].get("rcept_no", ""))  # type: ignore[arg-type]
            if cacheable:
                self._store.put_json(key, {"rows": rows, "fs": fs, "rcept_no": result.rcept_no})
            return result
        return None

    def dividends(self, corp_code: str, year: int) -> list[dict] | None:
        key = f"dart:{corp_code}:div:{year}"
        cached = self._store.get_json(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = self._json("alotMatter.json", corp_code=corp_code,
                          bsns_year=str(year), reprt_code="11011")
        if data is None:
            return None
        rows = data.get("list", [])
        self._store.put_json(key, rows)
        return rows

    def filings(self, start: date, end: date, detail_type: str | None = "A001",
                corp_code: str | None = None) -> list[dict]:
        out: list[dict] = []
        lo = start
        while lo <= end:
            hi = min(lo + timedelta(days=89), end)
            page = 1
            while True:
                params: dict[str, str] = {"bgn_de": lo.strftime("%Y%m%d"),
                                          "end_de": hi.strftime("%Y%m%d"),
                                          "page_no": str(page), "page_count": "100"}
                if detail_type:
                    params["pblntf_detail_ty"] = detail_type
                if corp_code:
                    params["corp_code"] = corp_code
                data = self._json("list.json", **params)
                if data is None:
                    break
                out.extend(data.get("list", []))
                if page >= int(data.get("total_page") or 1):
                    break
                page += 1
            lo = hi + timedelta(days=1)
        return out

    def invalidate(self, corp_code: str) -> None:
        self._store.delete_prefix(f"dart:{corp_code}:")
