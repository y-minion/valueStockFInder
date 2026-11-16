"""금융감독원 금융통계정보시스템(FISIS) OPEN API: 금융회사 자본비율. 오류 메시지에는 인증키를 넣지 않아요."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date

import httpx

from vsf.data.http import get_with_retry
from vsf.data.store import Store
from vsf.financial import CapitalRatio

BASE = "https://fisis.fss.or.kr/openapi/"

# (partDiv, listNo, 쓸 계정 — 앞쪽이 우선). 카드·캐피탈은 자본비율 통계가 달라 조회하지 않아요.
TABLES: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "금융지주": [("L", "SL008", ("C2",))],
    "은행": [("A", "SA014", ("A2",))],
    "보험": [("H", "SH021", ("D", "A")), ("I", "SI021", ("D", "A"))],
    "증권": [("F", "SF308", ("E",))],
}
_AUTH_CODES = {"010", "011", "012", "013"}
_CLOSED = ("[폐]", "[closed]")
_KR_DROP = re.compile(r"\(주\)|주식회사|\s+")
_EN_DROP = re.compile(r"[^a-z0-9]")


class FisisError(Exception):
    """FISIS 요청 오류. 메시지는 한국어이고 인증키는 담기지 않아요."""


class FisisAuthError(FisisError):
    """인증키 문제. 이번 실행에서는 더 부르지 않아요."""


def _kr(name: str) -> str:
    return _KR_DROP.sub("", name)


def _en(name: str) -> str:
    return _EN_DROP.sub("", name.lower())


def _ym(d: date, back_months: int = 0) -> str:
    m = d.year * 12 + d.month - 1 - back_months
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def _positive(v) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return x if x > 0 else None


class FisisClient:
    def __init__(
        self,
        auth_key: str,
        store: Store,
        http: httpx.Client | None = None,
        today: Callable[[], date] = date.today,
        min_interval: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key = auth_key
        self._store = store
        self._http = http or httpx.Client(timeout=30)
        self._today = today
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def _call(self, service: str, params: dict) -> dict:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = get_with_retry(self._http, BASE + service + ".json",
                                  params={"auth": self._key, **params})
        finally:
            self._last = self._clock()
            self._store.add_call("fisis", self._today())
        if resp.status_code >= 400:
            raise FisisError(f"금감원 FISIS 요청이 거절됐어요 (HTTP {resp.status_code})")
        try:
            result = resp.json()["result"]
            code = str(result["err_cd"])
        except (ValueError, KeyError, TypeError):
            raise FisisError("금감원 FISIS 응답 형식이 달라요") from None
        if code in _AUTH_CODES:
            raise FisisAuthError(f"금감원 FISIS 인증키가 맞지 않아요 ({code})")
        if code != "000":
            raise FisisError(f"금감원 FISIS 요청에 실패했어요 ({code})")
        return result

    def companies(self, part_div: str, lang: str) -> list[tuple[str, str]]:
        """(finance_cd, finance_nm). 폐업 회사는 빼요. 한 달에 한 번만 받아요."""
        key = f"fisis:companies:{part_div}:{lang}:{_ym(self._today())}"
        cached = self._store.get_json(key)
        if cached is None:
            result = self._call("companySearch", {"lang": lang, "partDiv": part_div})
            rows = result.get("list") or []
            try:
                cached = [[r["finance_cd"], r["finance_nm"]] for r in rows
                          if not any(t in r["finance_nm"] for t in _CLOSED)]
            except (KeyError, TypeError):
                raise FisisError("금감원 FISIS 응답 형식이 달라요") from None
            self._store.put_json(key, cached)
        return [(c, n) for c, n in cached]

    def _match(self, part_div: str, names: tuple[str, ...]) -> str | None:
        for lang, norm in (("kr", _kr), ("en", _en)):
            wanted = {norm(n) for n in names if n} - {""}
            for code, name in self.companies(part_div, lang):
                if norm(name) in wanted:
                    return code
        return None

    def _latest(self, finance_cd: str, list_no: str, accounts: tuple[str, ...]) -> CapitalRatio | None:
        today = self._today()
        key = f"fisis:ratio:{finance_cd}:{list_no}:{_ym(today)}"
        cached = self._store.get_json(key)
        if cached is not None:
            return CapitalRatio(**cached) if cached else None       # type: ignore[arg-type]
        result = self._call("statisticsInfoSearch", {
            "lang": "kr", "financeCd": finance_cd, "listNo": list_no, "term": "Q",
            "startBaseMm": _ym(today, 12), "endBaseMm": _ym(today)})
        rows = result.get("list") or []
        found: CapitalRatio | None = None
        for acc in accounts:
            good = [(str(r.get("base_month", "")), v, r) for r in rows
                    if r.get("account_cd") == acc and (v := _positive(r.get("a"))) is not None]
            if good:
                month, value, row = max(good, key=lambda t: t[0])
                found = CapitalRatio(
                    value=value, base_month=f"{month[:4]}-{month[4:6]}",
                    source=f"금감원 금융통계정보시스템 {list_no}·{row.get('account_nm') or acc}")
                break
        self._store.put_json(key, {"value": found.value, "base_month": found.base_month,
                                   "source": found.source} if found else {})
        return found

    def capital_ratio(self, kind: str, names: tuple[str, ...]) -> CapitalRatio | None:
        for part_div, list_no, accounts in TABLES.get(kind, []):
            code = self._match(part_div, names)
            if code is not None:
                return self._latest(code, list_no, accounts)
        return None
