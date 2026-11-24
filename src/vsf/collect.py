"""시장 전체 자료 모으기. 한도에 걸리면 못 받은 종목을 pending에 남겨 다음 실행이 이어서 받아요."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

from vsf.data.assemble import (Assembled, CompanyInfo, PreferredShare, assemble, assemble_quick_fail,
                               preferred_kind, quick_fail_check)
from vsf.data.dart import DartError, DartQuotaExceeded
from vsf.data.fisis import TABLES, FisisAuthError, FisisError
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError, Listed
from vsf.data.store import PriceRow, Store
from vsf.data.universe import (company_exclusion, financial_kind, is_financial_holding, is_holding_like,
                               listing_exclusion)
from vsf.financial import CapitalRatio

FIRST_DIV_YEAR = 2015
PROGRESS_EVERY = 50
YEAR_END_YEARS = 10
NO_CORP = "DART에서 회사 정보를 찾지 못했어요"
NO_PRICE = "주가 자료가 없어요"
NO_FIN = "{year}년 사업보고서 재무제표가 없어요"
FISIS_KEY_NOTE = "금감원 FISIS 인증키가 맞지 않아 자본비율을 가져오지 못했어요. keys.toml의 [fisis] 값을 확인해 주세요."
FISIS_FAIL_NOTE = "자본비율을 금감원 FISIS에서 받지 못했어요"
UNEXPECTED = "예상하지 못한 오류: {kind}: {error}"
PREFERRED = "우선주"                     # listing_exclusion이 우선주에 주는 사유
NO_COMMON = "우선주(보통주 없음)"
NO_COMMON_PRICE = "보통주 주가 자료가 없어요"


def preferred_base(code: str) -> str:
    """우선주 코드 → 같은 회사 보통주 코드 (앞 다섯 자리 + "0"). 2026-11-20 목록 109개 모두 이 규칙이에요."""
    return code[:5] + "0"

log = logging.getLogger("vsf.collect")


@dataclass
class Collected:
    today: date
    price_date: date
    records: dict[str, tuple[CompanyInfo, Assembled]] = field(default_factory=dict)
    excluded: dict[str, list[tuple[str, str]]] = field(default_factory=dict)       # 사유 → [(코드, 이름)]
    failed: list[tuple[str, str, str]] = field(default_factory=list)               # (코드, 이름, 사유)
    pending: list[tuple[str, str]] = field(default_factory=list)                   # 하루 한도로 못 받은 종목
    total_listed: int = 0
    year_end_missing: list[int] = field(default_factory=list)                     # 연말 주가를 못 받은 해


class _Excluded(Exception):
    pass


class _Failed(Exception):
    pass


@dataclass
class _Context:
    dart: object
    today: date
    price_date: date
    prices: dict[str, PriceRow]
    corp: dict[str, str]
    year_ends: dict[int, dict[str, PriceRow]]
    include_financial: bool = True
    fisis: object = None
    fisis_key_bad: bool = False


PER_BANNER_YEARS = 6


def _year_ends(krx, today: date) -> tuple[dict[int, dict[str, PriceRow]], list[int]]:
    """해마다 마지막 거래일의 전체 시장 시세와, 못 받은 해 목록.

    못 받은 해는 건너뛰고 실행은 계속해요. 그해 PER이 비어 적정가 B·C가 빠질 수 있어서 리포트에 알려요.
    PER에는 최근 5년(마지막 사업연도가 올해−1 또는 올해−2)만 쓰여서, 알림에는 올해−6년부터만 넣어요.
    더 오래된 해도 주식 수·분할 확인에 쓰니 모두 받아 봐요.
    """
    out: dict[int, dict[str, PriceRow]] = {}
    missing: list[int] = []
    for y in range(today.year - YEAR_END_YEARS, today.year):
        try:
            rows = krx.daily(krx.year_end(y))
        except (KrxError, NetworkError):
            rows = {}
        if rows:
            out[y] = rows
        elif y >= today.year - PER_BANNER_YEARS:
            missing.append(y)
    return out, missing


@dataclass(frozen=True)
class _Prepared:
    """종목 하나의 회사 확인을 마친 값 (사업연도를 고르기 전)."""
    corp: str
    base: str
    price: PriceRow
    base_price: PriceRow
    raw: dict
    info: CompanyInfo
    kind: str


def _prepare(ctx: _Context, item: Listed, common: str | None) -> _Prepared:
    """제외·고유번호·주가·회사 정보 확인. 제외면 _Excluded, 못 받으면 _Failed예요."""
    dart, code = ctx.dart, item.code
    if common is None:
        reason = listing_exclusion(item)
        if reason:
            raise _Excluded(reason)
    base = common or code
    corp = ctx.corp.get(base)
    if not corp:
        raise _Failed(NO_CORP)
    price = ctx.prices.get(code)
    if price is None or price.close is None:
        raise _Failed(NO_PRICE)
    base_price = ctx.prices.get(base) if common else price      # 분할 확인은 보통주 시세로 해요
    if base_price is None or base_price.close is None:
        raise _Failed(NO_COMMON_PRICE)
    raw = dart.company(corp)
    if raw is None:
        raise _Failed(NO_CORP)
    reason = company_exclusion(raw, ctx.include_financial)
    if reason:
        raise _Excluded(reason)
    info = CompanyInfo(corp_code=corp, code=code, name=item.name, market=item.market,
                       induty_code=str(raw.get("induty_code") or ""), acc_mt=str(raw.get("acc_mt") or ""),
                       financial_kind=financial_kind(raw) if ctx.include_financial else None, common_code=common,
                       est_dt=str(raw.get("est_dt") or ""))
    return _Prepared(corp, base, price, base_price, raw, info, preferred_kind(item.name) if common else "보통")


def _assemble_year(ctx: _Context, item: Listed, common: str | None, prep: _Prepared, latest: int,
                   divs: list[dict] | None, quick_fail: bool) -> tuple[CompanyInfo, Assembled]:
    """사업연도 latest로 조립해요. divs는 latest년 배당 보고서(없으면 None)예요."""
    dart, code, corp, info = ctx.dart, item.code, prep.corp, prep.info
    div_reports: dict[int, list[dict]] = {}
    if divs is not None:
        div_reports[latest] = divs
    if quick_fail and quick_fail_check(divs, latest, prep.kind):
        return info, assemble_quick_fail(info, latest, div_reports, prep.price, ctx.price_date, prep.kind)
    fin_a = dart.financials(corp, latest)
    if fin_a is None:
        raise _Failed(NO_FIN.format(year=latest))
    if is_holding_like(prep.raw):     # 64992와 큰 분류 649…: 유동자산이 없으면 금융지주, 있으면 일반 회사
        if is_financial_holding(fin_a):
            if not ctx.include_financial:
                raise _Excluded("금융지주")
            info = replace(info, financial_kind="금융지주")
    fin_b = dart.financials(corp, latest - 2)
    for y in range(latest - 2, latest - 9, -2):
        if y >= FIRST_DIV_YEAR:
            rows = dart.dividends(corp, y)
            if rows is not None:
                div_reports[y] = rows
    base = prep.base
    year_end = {y: rows[base] for y, rows in ctx.year_ends.items() if base in rows}
    pref = None if common is None else PreferredShare(
        code, item.name, prep.price, {y: rows[code] for y, rows in ctx.year_ends.items() if code in rows})
    capital, notes = _capital(ctx, info, prep.raw, item)
    got = assemble(info, latest, fin_a, fin_b, div_reports, year_end, prep.base_price, ctx.price_date, capital,
                   preferred=pref)
    if notes:
        got = replace(got, notes=got.notes + notes)
    return info, got


def _process(ctx: _Context, item: Listed, common: str | None = None) -> tuple[CompanyInfo, Assembled]:
    """종목 하나. 제외면 _Excluded, 못 받으면 _Failed, 한도·네트워크 오류는 그대로 올라가요.

    common: 우선주면 같은 회사 보통주 코드. 회사 정보·재무는 보통주 회사 것, 주가·배당은 우선주 것이에요.
    """
    prep = _prepare(ctx, item, common)
    latest = ctx.today.year - 1
    divs = ctx.dart.dividends(prep.corp, latest)
    if divs is None:
        divs = ctx.dart.dividends(prep.corp, latest - 1)
        if divs is not None:
            latest -= 1
    return _assemble_year(ctx, item, common, prep, latest, divs, quick_fail=True)


def assemble_for_year(ctx: _Context, item: Listed, latest: int, common: str | None = None, *,
                      divs: list[dict] | None = None, quick_fail: bool = True) -> tuple[CompanyInfo, Assembled]:
    """사업연도 latest로 종목 하나를 조립해요. _process는 '오늘'로 latest를 고른 뒤 같은 조립을 해요.

    divs: 이미 받은 latest년 배당 보고서 (다시 받지 않게). 없으면 여기서 받아요.
    quick_fail=False면 최근 해 배당이 0이어도 재무를 받아 끝까지 조립해요 (백테스트: 들고 있던 종목의 적정가).
    제외면 _Excluded, 못 받으면 _Failed가 그대로 올라가요.
    """
    prep = _prepare(ctx, item, common)
    if divs is None:
        divs = ctx.dart.dividends(prep.corp, latest)
    return _assemble_year(ctx, item, common, prep, latest, divs, quick_fail)


def context_for(dart, krx, day: date, corp: dict[str, str], *, include_financial: bool = True,
                fisis=None) -> _Context:
    """그날 기준 조립 문맥: today·price_date=day, 그날 시세, 그 전 10년 연말 시세."""
    return _Context(dart, day, day, krx.daily(day), corp, _year_ends(krx, day)[0], include_financial, fisis)


def _capital(ctx: _Context, info: CompanyInfo, raw: dict, item: Listed) -> tuple[CapitalRatio | None, tuple[str, ...]]:
    """금융회사 자본비율을 FISIS에서. 못 받아도 종목은 그대로 분석하고 메모만 남겨요."""
    if ctx.fisis is None or info.financial_kind not in TABLES:
        return None, ()
    if ctx.fisis_key_bad:
        return None, (FISIS_KEY_NOTE,)
    try:
        return ctx.fisis.capital_ratio(info.financial_kind, (str(raw.get("corp_name") or ""),
                                                              str(raw.get("corp_name_eng") or ""), item.name)), ()
    except FisisAuthError:
        ctx.fisis_key_bad = True              # 남은 종목은 FISIS를 부르지 않아요
        return None, (FISIS_KEY_NOTE,)
    except (FisisError, NetworkError):
        return None, (FISIS_FAIL_NOTE,)
    except Exception:                         # FISIS 때문에 종목이 빠지면 안 돼요
        log.exception("FISIS 자본비율 처리 중 예기치 못한 오류 (%s)", item.code)
        return None, (FISIS_FAIL_NOTE,)


def _defer(result: Collected, items: list[Listed]) -> None:
    """못 받은 종목을 pending에. 목록 단계에서 걸러지는 종목은 제외 목록으로 보내요 (우선주는 다음에 받아요)."""
    for item in items:
        reason = listing_exclusion(item)
        if reason and reason != PREFERRED:
            result.excluded.setdefault(reason, []).append((item.code, item.name))
        else:
            result.pending.append((item.code, item.name))


def _check_filings(dart, store: Store, today: date) -> None:
    since = store.get_meta("filings_checked")
    if since:
        seen: dict[str, None] = {}
        for filing in dart.filings(date.fromisoformat(since), today, "A001"):
            seen[filing["corp_code"]] = None
        for corp in seen:
            dart.invalidate(corp)
    store.set_meta("filings_checked", today.isoformat())


def collect(dart, krx, store: Store, today: date, progress: Callable[[str], None] = print,
            *, include_financial: bool = True, fisis=None) -> Collected:
    price_date = krx.latest_trading_day(today)
    prices = krx.daily(price_date)
    listed = krx.listed(price_date)
    result = Collected(today=today, price_date=price_date, total_listed=len(listed))
    try:
        _check_filings(dart, store, today)
        corp = dart.corp_codes()
    except DartQuotaExceeded:
        _defer(result, listed)
        progress(f"0/{len(listed)} 종목 처리 중 (오늘 DART 호출 {dart.calls_today:,}회)")
        return result
    year_ends, result.year_end_missing = _year_ends(krx, today)
    ctx = _Context(dart, today, price_date, prices, corp, year_ends, include_financial, fisis)

    def report(done: int) -> None:
        progress(f"{done}/{len(listed)} 종목 처리 중 (오늘 DART 호출 {dart.calls_today:,}회)")

    # 보통주를 먼저 다 받고, 우선주는 그 뒤에 받아요 (같은 회사 재무는 캐시를 다시 써요).
    codes = {x.code for x in listed}
    prefs: list[Listed] = []
    done, stopped = 0, False
    for i, item in enumerate(listed):
        if listing_exclusion(item) == PREFERRED:
            prefs.append(item)
        else:
            try:
                _one(ctx, result, item)
            except DartQuotaExceeded:
                _defer(result, listed[i:])
                result.pending[:0] = [(x.code, x.name) for x in prefs]
                stopped = True
                break
        done = i + 1
        if done % PROGRESS_EVERY == 0:
            report(done)
    if not stopped:
        for j, item in enumerate(prefs):
            base = preferred_base(item.code)
            if base not in codes:
                result.excluded.setdefault(NO_COMMON, []).append((item.code, item.name))
                continue
            try:
                _one(ctx, result, item, base)
            except DartQuotaExceeded:
                result.pending.extend((x.code, x.name) for x in prefs[j:])
                break
    if done % PROGRESS_EVERY != 0 or not done:
        report(done)
    return result


def _one(ctx: _Context, result: Collected, item: Listed, common: str | None = None) -> None:
    """종목 하나를 처리해 결과에 넣어요. 하루 한도 예외만 위로 올려요."""
    try:
        result.records[item.code] = _process(ctx, item, common)
    except _Excluded as e:
        result.excluded.setdefault(str(e), []).append((item.code, item.name))
    except _Failed as e:
        result.failed.append((item.code, item.name, str(e)))
    except DartQuotaExceeded:
        raise
    except (NetworkError, DartError, KrxError, ValueError) as e:
        result.failed.append((item.code, item.name, str(e)))
    except Exception as e:  # noqa: BLE001 - 한 종목의 뜻밖의 오류로 몇 시간짜리 실행을 멈추지 않아요
        log.exception("%s(%s) 종목을 처리하다 예상하지 못한 오류가 났어요", item.name, item.code)
        result.failed.append((item.code, item.name, UNEXPECTED.format(kind=type(e).__name__, error=e)))


def collect_one(dart, krx, store: Store, today: date, code: str, *,
                include_financial: bool = True, fisis=None) -> tuple[CompanyInfo, Assembled] | str:
    """종목 하나만 받아요 (엑셀 내보내기용). 못 받으면 한국어 사유 글을 돌려줘요."""
    price_date = krx.latest_trading_day(today)
    prices = krx.daily(price_date)
    listed = krx.listed(price_date)
    item = next((x for x in listed if x.code == code), None)
    if item is None:
        return f"{code} 종목을 찾지 못했어요"
    is_pref = listing_exclusion(item) == PREFERRED
    if is_pref and not any(x.code == preferred_base(code) for x in listed):
        return f"{code}은(는) 분석 대상이 아니에요: {NO_COMMON}"
    try:
        ctx = _Context(dart, today, price_date, prices, dart.corp_codes(), _year_ends(krx, today)[0],
                       include_financial, fisis)
        return _process(ctx, item, preferred_base(code) if is_pref else None)
    except _Excluded as e:
        return f"{code}은(는) 분석 대상이 아니에요: {e}"
    except (_Failed, NetworkError, DartError, KrxError, ValueError) as e:
        return str(e)
