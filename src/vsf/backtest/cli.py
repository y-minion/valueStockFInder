"""`uv run backtest.py`: 과거 실제 자료로 계산기를 검증해요 (2026-11-24 백테스트 설계 7장).

자료 받기는 하루 한도(DART·KRX)에 닿으면 멈추고, 다음 날 같은 명령으로 이어서 받아요.
받은 자료는 주간 실행과 같은 저장소(data/vsf.sqlite3)에 남아서 서로 나눠 써요.
"""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime

from vsf.backtest.benchmark import benchmark
from vsf.backtest.filings import annual_filing_dates
from vsf.backtest.market import Market, MarketPaused
from vsf.backtest.report import Row, annual, money, summarize_row, write_backtest_report
from vsf.backtest.simulate import Rules, simulate
from vsf.backtest.vintage import build_vintages
from vsf.cli import Deps, _run_log
from vsf.config import ConfigError, Keys, Settings, load_keys, load_settings
from vsf.data.dart import DartQuotaExceeded
from vsf.data.fisis import FisisClient
from vsf.data.store import Store

PAUSE = ("오늘 자료 받기 한도에 닿아 여기서 멈췄어요. 받은 자료는 저장했으니, 내일 `uv run backtest.py`를 다시 "
         "실행하면 이어서 받아요.")


def _fisis_for(keys: Keys, store: Store) -> Callable[[date], object | None]:
    """그날을 '오늘'로 보는 FISIS 클라이언트 (클라이언트 하나를 날짜만 바꿔 써요)."""
    if not keys.fisis:
        return lambda day: None
    holder: dict[str, date] = {}
    client = FisisClient(keys.fisis, store, today=lambda: holder.get("day") or date.today())

    def at(day: date):
        holder["day"] = day
        return client
    return at


def _cma_growth(market: Market, schedule: tuple[tuple[str, date], ...]) -> Callable[[date, date], float]:
    """그날 쓰는 CMA 대용 ETF의 종가 비율. 두 날 중 하나라도 시세가 없으면 1.0이에요."""
    def growth(prev: date, day: date) -> float:
        code = next((c for c, since in reversed(schedule) if since <= day), None)
        if code is None:
            return 1.0
        a, b = market.etf_close(prev, code), market.etf_close(day, code)
        return b / a if a and b else 1.0
    return growth


def _closer(market: Market, target: str) -> Callable[[date], float | None]:
    kind, _, name = target.partition(":")
    if kind == "etf":
        return lambda d: market.etf_close(d, name)
    return lambda d: market.index_close(d, name)


def _reason(text: str) -> str:
    """못 만든 묶음 사유를 묶어 세려고 해마다 다른 연도 글자를 지워요."""
    return re.sub(r"\d{4}년", "그해", text)


def _rows(settings: Settings, market: Market, vintages, days: list[date], month_starts: set[date],
          benchmarks: tuple[tuple[str, str], ...]) -> list[Row]:
    bt = settings.backtest
    rules = Rules(bt.monthly, bt.max_holdings, bt.cost_rate, bt.min_trade)
    listed = lambda d: {x.code for x in market.listing(d)}     # noqa: E731
    cma = _cma_growth(market, bt.cma)
    rows = [summarize_row(name, "규칙", simulate(days, market.stocks, vintages, name, rules, cma, listed, month_starts))
            for name, _ in bt.variants]
    rows += [summarize_row(label, "비교", benchmark(days, _closer(market, target), rules, month_starts))
             for label, target in benchmarks]
    return rows


def _run(settings: Settings, keys: Keys, store: Store, deps: Deps, no_open: bool) -> int:
    bt = settings.backtest
    today = deps.today()
    dart, krx = deps.make_dart(keys, store, settings), deps.make_krx(keys, store)
    market = Market(krx, store, bt.start, bt.end, today=today)
    try:
        print(f"KRX 시세를 받아요 ({bt.start} ~ {bt.end})")
        market.download(progress=print)
        universe = {}
        for d in market.month_starts():
            for x in market.listing(d):
                universe[x.code] = x
        print(f"사업보고서 공시일을 받아요 (종목 {len(universe):,}개)")
        filings = annual_filing_dates(dart, store, range(bt.start.year, bt.end.year + 1), today)
        vintages, failures = build_vintages(universe, filings, range(bt.start.year - 1, bt.end.year), market, dart,
                                            settings, _fisis_for(keys, store), progress=print)
    except (DartQuotaExceeded, MarketPaused):
        print(PAUSE)
        return 0
    days = market.trading_days()
    starts = set(market.month_starts())
    main_rows = _rows(settings, market, vintages, days, starts, bt.benchmarks)
    second_days = [d for d in days if d >= bt.second_start]
    second_starts = {d for d in starts if d >= bt.second_start} | set(second_days[:1])
    second_rows = (_rows(settings, market, vintages, second_days, second_starts, bt.benchmarks + bt.second_benchmarks)
                   if second_days else [])
    meta = {"start": bt.start, "end": bt.end, "second_start": bt.second_start,
            "vintages": sum(len(v) for v in vintages.values()),
            "substitutes": sum(1 for vs in vintages.values() for v in vs if v.substitute),
            "failures": dict(Counter(_reason(r) for _, _, r in failures))}
    path = write_backtest_report(main_rows, second_rows, meta, settings.reports_dir, today)
    for r in main_rows:
        print(f"{r.label}: 넣은 돈 {money(r.invested)} → {money(r.final)} ({annual(r.xirr)})")
    print(f"리포트: {path}")
    if not no_open:
        deps.open_path(path)
    return 0


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backtest.py", description="계산기 백테스트")
    ap.add_argument("--no-open", action="store_true", help="브라우저를 열지 않아요")
    ap.add_argument("--settings", default="settings.toml")
    ap.add_argument("--keys", default="keys.toml")
    args = ap.parse_args(argv)
    deps = deps or Deps()
    try:
        settings = load_settings(args.settings)
        keys = load_keys(args.keys)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2
    store = Store(settings.data_dir / "vsf.sqlite3")
    now = datetime.now()
    run_log = settings.data_dir / "logs" / f"backtest-{now:%Y%m%d-%H%M%S}.log"
    try:
        with _run_log(run_log, keys):
            return _run(settings, keys, store, deps, args.no_open)
    except Exception as e:  # noqa: BLE001 - 마지막 안전망: 트레이스백은 로그에만, 키는 지워요
        log = settings.data_dir / "logs" / f"backtest-error-{now:%Y%m%d-%H%M%S}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        text, message = traceback.format_exc(), str(e)
        for secret in (keys.dart, keys.krx, keys.naver_id, keys.naver_secret, keys.fisis):
            if secret:
                text, message = text.replace(secret, "REMOVED"), message.replace(secret, "REMOVED")
        log.write_text(text, encoding="utf-8")
        print(f"예상하지 못한 오류가 났어요: {message}. 받은 자료는 저장돼 있어요. 자세한 내용은 {log}에 남겼어요.",
              file=sys.stderr)
        return 1
    finally:
        store.close()
