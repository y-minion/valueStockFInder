"""수집 단계 테스트용 가짜 DART·KRX. 진짜 클라이언트와 같은 메서드 이름·인자를 쓰고, 호출 기록이 남아요."""
import tempfile
from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

from helpers import SYN_PRICE_DATE, SYN_SHARES, synthetic_company
from vsf.data.dart import DartQuotaExceeded
from vsf.data.krx import KrxClient, Listed
from vsf.data.store import PriceRow, Store

D = date(2026, 11, 14)
KIA_CORP = "99000270"
_BASE = synthetic_company()
_DEFAULT_DIVS = _BASE[4]                              # {2025·2023·2021·2019·2017: 배당 줄}
_DEFAULT_FIN = {2025: _BASE[2], 2023: _BASE[3]}       # {A 보고서 연도: FinRows, B 보고서 연도: FinRows}
_YEAR_END = _BASE[5]


def noop(_message: str) -> None:
    """collect의 progress 자리에 넣는 아무것도 안 하는 함수."""


def mem_store() -> Store:
    return Store(Path(tempfile.mkdtemp()) / "store.sqlite")


def corp_of(code: str) -> str:
    return f"99{code}"


class FakeDart:
    """DartClient 흉내.

    companies: {종목코드: {"company": 기업개황 dict, "dividends": {연도: 줄}, "fin": {연도: FinRows},
                "quarterly_fin": {(연도, 보고서 코드): FinRows}, "periodic": {(api, 연도, 보고서 코드): 줄},
                "name": DART 회사명}}  ("quarterly_fin"·"periodic"·"name"은 없어도 돼요)
    없는 연도는 None(DART의 013)을 돌려줘요.
    quota_after=N: 서로 다른 회사 N곳을 건드린 뒤 새 회사를 건드리면 DartQuotaExceeded.
    raise_for={종목코드: 예외}: 그 회사에 대한 어떤 호출이든 그 예외.
    raise_in={메서드 이름: 예외}: 그 메서드를 부르면 그 예외 (예: {"corp_codes": DartQuotaExceeded()}).
    """

    def __init__(self, companies: dict[str, dict], filings=(), quota_after: int | None = None,
                 raise_for: dict[str, Exception] | None = None,
                 raise_in: dict[str, Exception] | None = None) -> None:
        self._companies = companies
        self._by_corp = {corp_of(code): code for code in companies}
        self._filings = list(filings)
        self._quota_after = quota_after
        self._raise_for = raise_for or {}
        self._raise_in = raise_in or {}
        self._touched: list[str] = []
        self._log: dict[str, list[tuple]] = defaultdict(list)
        self.invalidated: list[str] = []

    @property
    def calls_today(self) -> int:
        return sum(len(v) for name, v in self._log.items() if name != "invalidate")

    def calls_of(self, name: str) -> int:
        return len(self._log[name])

    def _enter(self, name: str, *args) -> None:
        self._log[name].append(args)
        if name in self._raise_in:
            raise self._raise_in[name]

    def _gate(self, corp_code: str) -> dict:
        code = self._by_corp[corp_code]
        if code in self._raise_for:
            raise self._raise_for[code]
        if code not in self._touched:
            if self._quota_after is not None and len(self._touched) >= self._quota_after:
                raise DartQuotaExceeded()
            self._touched.append(code)
        return self._companies[code]

    def corp_codes(self) -> dict[str, str]:
        self._enter("corp_codes")
        return {code: corp_of(code) for code in self._companies}

    def company(self, corp_code: str) -> dict | None:
        self._enter("company", corp_code)
        return self._gate(corp_code)["company"]

    def financials(self, corp_code: str, year: int, report: str = "11011"):
        self._enter("financials", corp_code, year, report)
        entry = self._gate(corp_code)
        if report != "11011":
            return entry.get("quarterly_fin", {}).get((year, report))
        return entry["fin"].get(year)

    def periodic(self, api: str, corp_code: str, year: int, report: str = "11011") -> list[dict] | None:
        self._enter("periodic", corp_code, api, year, report)
        return self._gate(corp_code).get("periodic", {}).get((api, year, report))

    def corp_names(self) -> dict[str, str]:
        self._enter("corp_names")
        return {code: e.get("name", f"회사{code}") for code, e in self._companies.items()}

    def dividends(self, corp_code: str, year: int) -> list[dict] | None:
        self._enter("dividends", corp_code, year)
        return self._gate(corp_code)["dividends"].get(year)

    def filings(self, start: date, end: date, detail_type: str | None = "A001",
                corp_code: str | None = None) -> list[dict]:
        self._enter("filings", start, end, detail_type, corp_code)
        return list(self._filings)

    def invalidate(self, corp_code: str) -> None:
        self._log["invalidate"].append((corp_code,))
        self.invalidated.append(corp_code)

    @staticmethod
    def entry(induty_code: str = "30121", acc_mt: str = "12", dividends=None, fin=None) -> dict:
        return {"company": {"induty_code": induty_code, "acc_mt": acc_mt},
                "dividends": _DEFAULT_DIVS if dividends is None else dividends,
                "fin": _DEFAULT_FIN if fin is None else fin}

    @classmethod
    def with_company(cls, code: str = "000270", dividends=None, fin=None, induty_code: str = "30121",
                     acc_mt: str = "12", **kw) -> "FakeDart":
        return cls({code: cls.entry(induty_code, acc_mt, dividends, fin)}, **kw)

    @classmethod
    def two_companies(cls, **kw) -> "FakeDart":
        return cls({"000270": cls.entry(), "030000": cls.entry()}, **kw)

    default = two_companies

    @classmethod
    def many(cls, n: int = 10, **kw) -> "FakeDart":
        return cls({code: cls.entry() for code, _ in _many_codes(n)}, **kw)

    @classmethod
    def exclusion_mix(cls, **kw) -> "FakeDart":
        # 우선주·스팩은 목록 단계에서 걸러져서 DART 자료가 필요 없어요.
        return cls({"000270": cls.entry(), "055550": cls.entry(induty_code="6419"),
                    "007070": cls.entry(acc_mt="03")}, **kw)


def _many_codes(n: int) -> list[tuple[str, str]]:
    return [(f"{100000 + i * 10:06d}", f"종목{i}") for i in range(n)]


def _listed(code: str, name: str, **kw) -> Listed:
    base = dict(code=code, name=name, market="KOSPI", group="주권", kind="보통주", shares=float(SYN_SHARES))
    return Listed(**{**base, **kw})


class FakeKrx:
    """KrxClient 흉내. 날짜별 시세를 미리 넣어 두면 돌려줘요.

    latest_trading_day·year_end·week_ends는 진짜 클라이언트 코드를 그대로 써서, daily()만 가짜로 둬요.
    """

    def __init__(self, listed: list[Listed], days: dict[date, dict[str, PriceRow]] | None = None,
                 weekdays_only: bool = False) -> None:
        self._listed = listed
        self._days = days or {}
        self._weekdays_only = weekdays_only
        self._log: dict[str, list[tuple]] = defaultdict(list)

    def calls_of(self, name: str) -> int:
        return len(self._log[name])

    def listed(self, day: date) -> list[Listed]:
        self._log["listed"].append((day,))
        return list(self._listed)

    def daily(self, day: date) -> dict[str, PriceRow]:
        self._log["daily"].append((day,))
        if self._weekdays_only:
            if day.weekday() >= 5:
                return {}
            close = 50_000.0 + (day.toordinal() % 100) * 100
            return {x.code: PriceRow(day, x.code, x.name, x.market, close, x.shares) for x in self._listed}
        return dict(self._days.get(day, {}))

    def latest_trading_day(self, today: date, max_back: int = 10) -> date:
        return KrxClient.latest_trading_day(self, today, max_back)  # type: ignore[arg-type]

    def year_end(self, year: int) -> date:
        return KrxClient.year_end(self, year)  # type: ignore[arg-type]

    def week_ends(self, until: date, weeks: int = 52) -> list[date]:
        return KrxClient.week_ends(self, until, weeks)  # type: ignore[arg-type]

    @classmethod
    def with_listed(cls, listed: list[Listed]) -> "FakeKrx":
        """합성 회사 시세(2021–2025 연말 종가, 현재가)를 목록의 모든 종목에 똑같이 깔아요."""
        days: dict[date, dict[str, PriceRow]] = {}
        for item in listed:
            for row in (*_YEAR_END.values(), _BASE[6]):
                days.setdefault(row.date, {})[item.code] = replace(
                    row, code=item.code, name=item.name, market=item.market)
        return cls(listed, days)

    @classmethod
    def default(cls) -> "FakeKrx":
        return cls.with_listed([_listed("000270", "기아"), _listed("030000", "제일기획")])

    @classmethod
    def many(cls, n: int = 10) -> "FakeKrx":
        return cls.with_listed([_listed(code, name) for code, name in _many_codes(n)])

    @classmethod
    def exclusion_mix(cls) -> "FakeKrx":
        return cls.with_listed([
            _listed("000270", "기아"), _listed("005935", "삼성전자우", kind="우선주"),
            _listed("123450", "하나30호스팩"), _listed("055550", "신한지주"), _listed("007070", "GS리테일")])

    @classmethod
    def calendar(cls, codes: tuple[str, ...] = ("000270",)) -> "FakeKrx":
        """평일마다 시세가 있고 주말엔 없는 달력."""
        return cls([_listed(code, f"종목{code}") for code in codes], weekdays_only=True)


__all__ = ["D", "KIA_CORP", "FakeDart", "FakeKrx", "SYN_PRICE_DATE", "mem_store", "noop"]
