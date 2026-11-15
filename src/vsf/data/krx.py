"""KRX OPEN API 클라이언트: 상장 종목, 일별 시세, 거래일 찾기."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import httpx

from vsf.data.http import get_with_retry
from vsf.data.store import PriceRow, Store

BASE = "https://data-dbg.krx.co.kr/svc/apis/sto/"

# 응답 필드 이름. 제3자 자료에서 가져온 값이라, tools/record_fixtures.py krx로
# 실제 응답을 녹화해 확인하기 전까지는 검증되지 않았어요.
DAILY_FIELDS = {"code": "ISU_CD", "name": "ISU_NM", "close": "TDD_CLSPRC", "shares": "LIST_SHRS"}
BASE_FIELDS = {"code": "ISU_SRT_CD", "name": "ISU_ABBRV", "group": "SECUGRP_NM",
               "kind": "KIND_STKCERT_TP_NM", "shares": "LIST_SHRS"}

SERVICE_NAMES = {
    "stk_bydd_trd": "유가증권 일별매매정보",
    "ksq_bydd_trd": "코스닥 일별매매정보",
    "stk_isu_base_info": "유가증권 종목기본정보",
    "ksq_isu_base_info": "코스닥 종목기본정보",
}
MARKETS: tuple[tuple[str, Literal["KOSPI", "KOSDAQ"]], ...] = (("stk", "KOSPI"), ("ksq", "KOSDAQ"))


class KrxError(Exception):
    """KRX 요청 오류. 메시지는 한국어이고 인증키는 담기지 않아요."""


@dataclass(frozen=True)
class Listed:
    code: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    group: str  # 증권구분
    kind: str  # 주식종류
    shares: float | None


def _num(v) -> float | None:
    """"1,234" → 1234.0, ""·"-"·없음 → None."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _close(v) -> float | None:
    """종가. 0 이하는 '시세 없음'(None)으로 봐요. 0원 종가로 매수선 이하 판정이 나오면 안 돼요."""
    x = _num(v)
    return x if x is not None and x > 0 else None


class KrxClient:
    def __init__(
        self,
        auth_key: str,
        store: Store,
        http: httpx.Client | None = None,
        min_interval: float = 0.2,
        today: Callable[[], date] = date.today,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key = auth_key
        self._store = store
        self._http = http or httpx.Client(timeout=30)
        self._min_interval = min_interval
        self._today = today
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def _rows(self, service: str, day: date) -> list[dict]:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        label = SERVICE_NAMES[service]
        try:
            resp = get_with_retry(self._http, BASE + service,
                                  params={"basDd": day.strftime("%Y%m%d")},
                                  headers={"AUTH_KEY": self._key})
        finally:
            self._last = self._clock()
            self._store.add_call("krx", self._today())
        if resp.status_code in (401, 403):
            raise KrxError(f"KRX OPEN API에서 '{label}' 이용 승인이 필요해요. "
                           "openapi.krx.co.kr에서 이용신청 상태를 확인해 주세요.")
        if resp.status_code >= 400:
            raise KrxError(f"KRX OPEN API '{label}' 요청이 거절됐어요 (HTTP {resp.status_code})")
        try:
            rows = resp.json()["OutBlock_1"]
        except (ValueError, KeyError, TypeError):
            raise KrxError(f"KRX OPEN API '{label}' 응답 형식이 달라요") from None
        if not isinstance(rows, list):
            raise KrxError(f"KRX OPEN API '{label}' 응답 형식이 달라요")
        return rows

    def listed(self, day: date) -> list[Listed]:
        key = f"krx:base:{day.strftime('%Y%m%d')}"
        cacheable = day < self._today()
        if cacheable:
            cached = self._store.get_json(key)
            if cached is not None:
                return [Listed(**r) for r in cached]  # type: ignore[arg-type]
        f = BASE_FIELDS
        out: list[Listed] = []
        for prefix, market in MARKETS:
            for r in self._rows(f"{prefix}_isu_base_info", day):
                code = str(r.get(f["code"]) or "").strip()
                if code:
                    out.append(Listed(code, str(r.get(f["name"]) or "").strip(), market,
                                      str(r.get(f["group"]) or "").strip(),
                                      str(r.get(f["kind"]) or "").strip(),
                                      _num(r.get(f["shares"]))))
        if cacheable and out:
            self._store.put_json(key, [x.__dict__ for x in out])
        return out

    def daily(self, day: date) -> dict[str, PriceRow]:
        """그날 두 시장 시세. 지난 날은 두 시장 모두 자료가 있을 때만 저장해요.

        한 시장만 받은 날을 저장하면, 다음부터 다른 시장 종목이 그날 시세 없이 조용히 빠져요.
        """
        cacheable = day < self._today()
        if cacheable:
            stored = self._store.get_prices(day)
            if stored:
                return stored
        f = DAILY_FIELDS
        out: dict[str, PriceRow] = {}
        markets_with_rows: set[str] = set()
        for prefix, market in MARKETS:
            for r in self._rows(f"{prefix}_bydd_trd", day):
                code = str(r.get(f["code"]) or "").strip()
                if not code:
                    continue
                if code in out:
                    raise KrxError(f"종목코드 {code}가 코스피와 코스닥 응답에 모두 있어요")
                out[code] = PriceRow(day, code, str(r.get(f["name"]) or "").strip(), market,
                                     _close(r.get(f["close"])), _num(r.get(f["shares"])))
                markets_with_rows.add(market)
        if cacheable and len(markets_with_rows) == len(MARKETS):
            self._store.put_prices(out.values())
        return out

    def latest_trading_day(self, today: date, max_back: int = 10) -> date:
        for i in range(max_back + 1):
            d = today - timedelta(days=i)
            if self.daily(d):
                return d
        raise KrxError(f"{today.isoformat()} 기준 최근 {max_back}일 안에 거래일 자료가 없어요")

    def year_end(self, year: int) -> date:
        for i in range(10):
            d = date(year, 12, 31) - timedelta(days=i)
            if self.daily(d):
                return d
        raise KrxError(f"{year}년 마지막 거래일 자료를 찾지 못했어요")

    def week_ends(self, until: date, weeks: int = 52) -> list[date]:
        """주(월~일)마다 마지막 거래일. until이 든 주는 until 이전까지만 봐요. 오래된 순."""
        monday = until - timedelta(days=until.weekday())
        found: list[date] = []
        for w in range(weeks + 10):
            if len(found) >= weeks:
                break
            lo = monday - timedelta(weeks=w)
            hi = min(until, lo + timedelta(days=6))
            d = hi
            while d >= lo:
                if d.weekday() < 5 and self.daily(d):  # 주말엔 장이 안 서서 묻지 않아요
                    found.append(d)
                    break
                d -= timedelta(days=1)
        return sorted(found)
