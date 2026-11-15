"""시장 전체 자료 모으기. 한도에 걸리면 못 받은 종목을 pending에 남겨 다음 실행이 이어서 받아요."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from vsf.data.assemble import (Assembled, CompanyInfo, assemble, assemble_quick_fail,
                               quick_fail_check)
from vsf.data.dart import DartError, DartQuotaExceeded
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError, Listed
from vsf.data.store import PriceRow, Store
from vsf.data.universe import company_exclusion, holding_exclusion, is_holding, listing_exclusion

FIRST_DIV_YEAR = 2015
PROGRESS_EVERY = 50
YEAR_END_YEARS = 10
NO_CORP = "DART에서 회사 정보를 찾지 못했어요"
NO_PRICE = "주가 자료가 없어요"
NO_FIN = "{year}년 사업보고서 재무제표가 없어요"
UNEXPECTED = "예상하지 못한 오류: {kind}: {error}"

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


def _year_ends(krx, today: date) -> tuple[dict[int, dict[str, PriceRow]], list[int]]:
    """해마다 마지막 거래일의 전체 시장 시세와, 못 받은 해 목록.

    못 받은 해는 건너뛰고 실행은 계속해요. 그해 PER이 비어 적정가 B·C가 빠질 수 있어서 리포트에 알려요.
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
        else:
            missing.append(y)
    return out, missing


def _process(ctx: _Context, item: Listed) -> tuple[CompanyInfo, Assembled]:
    """종목 하나. 제외면 _Excluded, 못 받으면 _Failed, 한도·네트워크 오류는 그대로 올라가요."""
    dart, today, code = ctx.dart, ctx.today, item.code
    reason = listing_exclusion(item)
    if reason:
        raise _Excluded(reason)
    corp = ctx.corp.get(code)
    if not corp:
        raise _Failed(NO_CORP)
    price = ctx.prices.get(code)
    if price is None or price.close is None:
        raise _Failed(NO_PRICE)
    raw = dart.company(corp)
    if raw is None:
        raise _Failed(NO_CORP)
    reason = company_exclusion(raw)
    if reason:
        raise _Excluded(reason)
    info = CompanyInfo(corp_code=corp, code=code, name=item.name, market=item.market,
                       induty_code=str(raw.get("induty_code") or ""), acc_mt=str(raw.get("acc_mt") or ""))

    latest = today.year - 1
    div_reports: dict[int, list[dict]] = {}
    divs = dart.dividends(corp, latest)
    if divs is None:
        divs = dart.dividends(corp, latest - 1)
        if divs is not None:
            latest -= 1
    if divs is not None:
        div_reports[latest] = divs

    if quick_fail_check(divs, latest):
        return info, assemble_quick_fail(info, latest, div_reports, price, ctx.price_date)
    fin_a = dart.financials(corp, latest)
    if fin_a is None:
        raise _Failed(NO_FIN.format(year=latest))
    if is_holding(raw):
        reason = holding_exclusion(fin_a)
        if reason:
            raise _Excluded(reason)
    fin_b = dart.financials(corp, latest - 2)
    for y in range(latest - 2, latest - 9, -2):
        if y >= FIRST_DIV_YEAR:
            rows = dart.dividends(corp, y)
            if rows is not None:
                div_reports[y] = rows
    year_end = {y: rows[code] for y, rows in ctx.year_ends.items() if code in rows}
    return info, assemble(info, latest, fin_a, fin_b, div_reports, year_end, price, ctx.price_date)


def _defer(result: Collected, items: list[Listed]) -> None:
    """못 받은 종목을 pending에. 목록 단계에서 걸러지는 종목은 제외 목록으로 보내요."""
    for item in items:
        reason = listing_exclusion(item)
        if reason:
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


def collect(dart, krx, store: Store, today: date, progress: Callable[[str], None] = print) -> Collected:
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
    ctx = _Context(dart, today, price_date, prices, corp, year_ends)

    def report(done: int) -> None:
        progress(f"{done}/{len(listed)} 종목 처리 중 (오늘 DART 호출 {dart.calls_today:,}회)")

    done = 0
    for i, item in enumerate(listed):
        try:
            result.records[item.code] = _process(ctx, item)
        except _Excluded as e:
            result.excluded.setdefault(str(e), []).append((item.code, item.name))
        except _Failed as e:
            result.failed.append((item.code, item.name, str(e)))
        except DartQuotaExceeded:
            _defer(result, listed[i:])
            break
        except (NetworkError, DartError, KrxError, ValueError) as e:
            result.failed.append((item.code, item.name, str(e)))
        except Exception as e:  # noqa: BLE001 - 한 종목의 뜻밖의 오류로 몇 시간짜리 실행을 멈추지 않아요
            log.exception("%s(%s) 종목을 처리하다 예상하지 못한 오류가 났어요", item.name, item.code)
            result.failed.append((item.code, item.name, UNEXPECTED.format(kind=type(e).__name__, error=e)))
        done = i + 1
        if done % PROGRESS_EVERY == 0:
            report(done)
    if done % PROGRESS_EVERY != 0 or not done:
        report(done)
    return result


def collect_one(dart, krx, store: Store, today: date, code: str) -> tuple[CompanyInfo, Assembled] | str:
    """종목 하나만 받아요 (엑셀 내보내기용). 못 받으면 한국어 사유 글을 돌려줘요."""
    price_date = krx.latest_trading_day(today)
    prices = krx.daily(price_date)
    item = next((x for x in krx.listed(price_date) if x.code == code), None)
    if item is None:
        return f"{code} 종목을 찾지 못했어요"
    try:
        ctx = _Context(dart, today, price_date, prices, dart.corp_codes(), _year_ends(krx, today)[0])
        return _process(ctx, item)
    except _Excluded as e:
        return f"{code}은(는) 분석 대상이 아니에요: {e}"
    except (_Failed, NetworkError, DartError, KrxError, ValueError) as e:
        return str(e)
