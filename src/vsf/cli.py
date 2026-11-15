"""`uv run run.py`: 주간 실행과 `--excel` 내보내기를 이어 붙여요."""
import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from vsf.changes import criteria_changes, detect_changes
from vsf.collect import Collected, collect, collect_one
from vsf.config import ConfigError, Keys, Settings, load_keys, load_settings
from vsf.data.dart import DartClient
from vsf.data.http import NetworkError
from vsf.data.krx import KrxClient, KrxError
from vsf.data.naver import NaverNews
from vsf.data.store import Store
from vsf.engine import compute
from vsf.evaluate import evaluate, evaluate_one
from vsf.export_xlsx import export_xlsx
from vsf.extras import gather_extras
from vsf.report.payload import build_payload, write_report
from vsf.snapshot import SnapshotNotSaved, load_previous, save_snapshot


def _open(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False)


def _keep_awake() -> None:
    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])


@dataclass
class Deps:
    make_dart: Callable[[Keys, Store, Settings], object] = lambda keys, store, settings: DartClient(
        keys.dart, store, daily_budget=settings.dart_daily_budget)
    make_krx: Callable[[Keys, Store], object] = lambda keys, store: KrxClient(keys.krx, store)
    make_naver: Callable[[Keys], NaverNews | None] = lambda keys: (
        NaverNews(keys.naver_id, keys.naver_secret) if keys.naver_id and keys.naver_secret else None)
    today: Callable[[], date] = date.today
    open_path: Callable[[Path], None] = _open
    keep_awake: Callable[[], None] = _keep_awake


class RedactingFormatter(logging.Formatter):
    """로그 글을 파일에 쓰기 직전에 키 글자를 지워요. 키는 로그에 남지 않아요."""

    def __init__(self, secrets: tuple[str | None, ...]) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "REMOVED")
        return text


@contextmanager
def _run_log(path: Path, keys: Keys) -> Iterator[None]:
    """실행하는 동안 vsf 로거 기록(트레이스백 포함)을 path에 남겨요. 남길 기록이 없으면 파일을 만들지 않아요."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    handler.setFormatter(RedactingFormatter((keys.dart, keys.krx, keys.naver_id, keys.naver_secret)))
    logger = logging.getLogger("vsf")
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()


def _weekly(settings: Settings, keys: Keys, store: Store, deps: Deps, today: date,
            runs_dir: Path, no_open: bool, run_log: Path) -> int:
    deps.keep_awake()
    with _run_log(run_log, keys):
        return _weekly_run(settings, keys, store, deps, today, runs_dir, no_open)


def _print_pending(collected: Collected) -> None:
    if collected.pending:
        print(f"오늘 DART 호출 한도 때문에 {len(collected.pending)}개 종목을 못 받았어요. "
              "내일 다시 실행하면 이어서 받아요.")


def _weekly_run(settings: Settings, keys: Keys, store: Store, deps: Deps, today: date,
                runs_dir: Path, no_open: bool) -> int:
    dart, krx, naver = deps.make_dart(keys, store, settings), deps.make_krx(keys, store), deps.make_naver(keys)
    collected = collect(dart, krx, store, today)
    run = evaluate(collected, settings)
    prev = load_previous(runs_dir, today)
    same_day = settings.reports_dir / collected.today.isoformat()
    if not run.results and same_day.exists():
        # 같은 날 다시 실행했는데 한 종목도 못 받았어요 (예: 한도). 오늘 받아 둔 리포트·스냅샷을 지켜요.
        index = same_day / "index.html"
        print(f"오늘 리포트가 이미 있어서 그대로 두었어요: {index}")
        _print_pending(collected)
        if not no_open:
            deps.open_path(index)
        return 0
    changes = detect_changes(prev, run, settings.report)
    crit_changes = criteria_changes(prev.settings_fp, run.settings_fp) if prev else []
    codes = [c for c, r in run.results.items() if r.state in ("buy", "watch")]
    extras = gather_extras(codes, run, dart, krx, naver, today)
    payload = build_payload(run, changes, crit_changes, prev, extras, settings)
    index = write_report(payload, settings.reports_dir)
    try:
        save_snapshot(run, runs_dir, carry_from=prev)
    except SnapshotNotSaved as e:
        print(e)

    buy = sum(1 for r in run.results.values() if r.state == "buy")
    new = sum(1 for c in changes if c.kind == "new_buy")
    print(f"관심 목록 {len(codes)}개, 매수선 이하 {buy}개 (새로 {new}개)")
    print(f"리포트: {index}")
    _print_pending(collected)
    if not no_open:
        deps.open_path(index)
    return 0


def _excel(code: str, settings: Settings, keys: Keys, store: Store, deps: Deps, today: date,
           runs_dir: Path, no_open: bool) -> int:
    if not re.fullmatch(r"[0-9A-Za-z]{6}", code):
        print(f"{code}은(는) 올바른 종목코드가 아니에요.")
        return 1
    snap = load_previous(runs_dir, today + timedelta(days=1))
    held = snap.stocks.get(code) if snap else None
    if held is not None:
        inputs, criteria, extra = held.inputs, held.criteria, held.extra_gate1
        cells = compute(inputs, criteria, extra)
    else:
        got = collect_one(deps.make_dart(keys, store, settings), deps.make_krx(keys, store), store, today, code)
        if isinstance(got, str):
            print(got)
            return 1
        result = evaluate_one(got[0], got[1], settings, None)
        inputs, criteria, extra, cells = got[1].inputs, result.criteria, result.extra_gate1, result.cells
    note = f"업종 안 ROE 순위 판정: {extra}" if extra is not None else ""
    path = export_xlsx(settings.calculator_path, settings.exports_dir, inputs, cells, criteria, today, note)
    print(f"엑셀 파일: {path}")
    if not no_open:
        deps.open_path(path)
    return 0


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="배당주 주간 스크리너")
    ap.add_argument("--excel", metavar="CODE", help="종목 하나를 계산기 엑셀로 내보내요")
    ap.add_argument("--no-open", action="store_true", help="브라우저·Numbers를 열지 않아요")
    ap.add_argument("--settings", type=Path, default=Path("settings.toml"))
    ap.add_argument("--keys", type=Path, default=Path("keys.toml"))
    args = ap.parse_args(argv)
    deps = deps or Deps()
    try:
        settings = load_settings(args.settings)
        keys = load_keys(args.keys)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2

    now = datetime.now()
    log = settings.data_dir / "logs" / f"{now:%Y%m%d-%H%M%S}.log"
    run_log = settings.data_dir / "logs" / f"run-{now:%Y%m%d-%H%M%S}.log"
    runs_dir = settings.data_dir / "runs"
    store = None
    try:
        store = Store(settings.data_dir / "vsf.sqlite3")
        today = deps.today()
        if args.excel:
            return _excel(args.excel, settings, keys, store, deps, today, runs_dir, args.no_open)
        return _weekly(settings, keys, store, deps, today, runs_dir, args.no_open, run_log)
    except Exception as e:  # noqa: BLE001 - 마지막 안전망: 트레이스백은 로그에만
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if isinstance(e, (KrxError, NetworkError)):
            print(f"{e} 자세한 내용은 {log}에 남겼어요.", file=sys.stderr)
        else:
            print(f"예상하지 못한 오류가 났어요: {e}. 자세한 내용은 {log}에 남겼어요.", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
