import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from fakes import D, FakeDart, FakeKrx
from helpers import write_settings

from vsf.cli import Deps, main
from vsf.data import store as store_mod
from vsf.data.dart import DartQuotaExceeded
from vsf.snapshot import load_previous

KEYS = '[dart]\napi_key = "fake-dart-key"\n[krx]\nauth_key = "fake-krx-key"\n'


@dataclass
class FakeDeps(Deps):
    opened: list = field(default_factory=list)
    awake: list = field(default_factory=list)
    dart: FakeDart | None = None
    stores: list = field(default_factory=list)


def fake_deps(tmp_path: Path, quota_after: int | None = None) -> FakeDeps:
    d = FakeDeps(make_dart=None, make_krx=None, make_naver=None, today=None, open_path=None, keep_awake=None)
    d.dart = FakeDart.default() if quota_after is None else FakeDart.default(quota_after=quota_after)
    d.make_dart = lambda keys, store, settings: d.dart
    d.make_krx = lambda keys, store: FakeKrx.default()
    d.make_naver = lambda keys: None
    d.today = lambda: D
    d.open_path = d.opened.append
    d.keep_awake = lambda: d.awake.append(1)
    return d


def settings_in(tmp_path: Path) -> Path:
    (tmp_path / "keys.toml").write_text(KEYS, encoding="utf-8")
    return write_settings(tmp_path)


def run(tmp_path, d, *extra, no_open=True):
    args = ["--settings", str(settings_in(tmp_path)), "--keys", str(tmp_path / "keys.toml"), *extra]
    if no_open:
        args.append("--no-open")
    return main(args, deps=d)


INDEX = lambda t: t / "reports" / "2026-11-14" / "index.html"


def report_data(tmp_path: Path, day: str = "2026-11-14") -> dict:
    text = (tmp_path / "reports" / day / "data.js").read_text(encoding="utf-8")
    return json.loads(text.removeprefix("window.VSF_DATA = ").removesuffix(";"))


def test_config_error_exit_code(tmp_path, capsys):
    bad = write_settings(tmp_path, criteria={"safety_margin": '"25%"'})
    assert main(["--settings", str(bad), "--no-open"], deps=fake_deps(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "safety_margin" in err and "Traceback" not in err


def test_missing_keys_exit_code(tmp_path, capsys):
    s = write_settings(tmp_path)
    assert main(["--settings", str(s), "--keys", str(tmp_path / "none.toml"), "--no-open"],
                deps=fake_deps(tmp_path)) == 2
    assert "keys.toml" in capsys.readouterr().err


def test_weekly_run_writes_report_and_snapshot(tmp_path, capsys):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d, no_open=False) == 0
    assert INDEX(tmp_path).exists() and (tmp_path / "data" / "runs" / "2026-11-14.json.gz").exists()
    assert d.opened == [INDEX(tmp_path)]
    out = capsys.readouterr().out
    assert "관심 목록" in out and "매수선 이하" in out and f"리포트: {INDEX(tmp_path)}" in out
    assert d.awake == [1]


def test_no_open(tmp_path):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d) == 0 and d.opened == []


def test_partial_run_message(tmp_path, capsys):
    assert run(tmp_path, fake_deps(tmp_path, quota_after=1)) == 0
    assert "내일 다시 실행하면 이어서 받아요" in capsys.readouterr().out


@pytest.mark.template
def test_excel_uses_snapshot(tmp_path, template_path, capsys):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d) == 0
    d.dart._log.clear()
    d.awake.clear()
    assert run(tmp_path, d, "--excel", "000270") == 0
    assert list((tmp_path / "exports").glob("*000270*.xlsx"))
    assert d.dart.calls_today == 0
    assert d.awake == []
    assert "엑셀 파일:" in capsys.readouterr().out


@pytest.mark.template
def test_excel_without_snapshot_collects_one(tmp_path, template_path):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d, "--excel", "000270") == 0
    assert d.dart.calls_today > 0 and d.awake == []
    assert list((tmp_path / "exports").glob("*000270*.xlsx"))


def test_excel_unknown_code(tmp_path, capsys):
    assert run(tmp_path, fake_deps(tmp_path), "--excel", "999999") == 1
    assert "999999" in capsys.readouterr().out


def test_excel_invalid_code(tmp_path, capsys):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d, "--excel", "12-45") == 1
    assert "12-45은(는) 올바른 종목코드가 아니에요." in capsys.readouterr().out
    assert d.dart.calls_today == 0


def test_unexpected_error_logged(tmp_path, capsys):
    d = fake_deps(tmp_path)

    def boom(keys, store):
        raise RuntimeError("secret-boom")
    d.make_krx = boom
    assert run(tmp_path, d) == 1
    err = capsys.readouterr().err
    logs = list((tmp_path / "data" / "logs").glob("*.log"))
    assert len(logs) == 1 and "예상하지 못한 오류가 났어요: secret-boom" in err
    assert str(logs[0]) in err and "Traceback" not in err
    assert "Traceback" in logs[0].read_text(encoding="utf-8")


def test_krx_error_prints_own_message(tmp_path, capsys):
    from vsf.data.krx import KrxError
    d = fake_deps(tmp_path)

    def boom(keys, store):
        raise KrxError("KRX 승인이 안 됐어요")
    d.make_krx = boom
    assert run(tmp_path, d) == 1
    err = capsys.readouterr().err
    assert "KRX 승인이 안 됐어요" in err and "data" in err and "Traceback" not in err


def test_store_closed(tmp_path, monkeypatch):
    closed = []
    orig = store_mod.Store.close
    monkeypatch.setattr(store_mod.Store, "close", lambda self: (closed.append(1), orig(self))[1])
    assert run(tmp_path, fake_deps(tmp_path)) == 0
    assert closed == [1]


def test_unexpected_stock_error_goes_to_run_log_without_keys(tmp_path):
    d = fake_deps(tmp_path)
    d.dart = FakeDart.default(raise_for={"000270": TypeError("unsupported operand")})
    assert run(tmp_path, d) == 0                                  # 한 종목 오류로 실행이 멈추지 않아요
    logs = list((tmp_path / "data" / "logs").glob("*.log"))
    assert len(logs) == 1 and re.fullmatch(r"run-\d{8}-\d{6}\.log", logs[0].name)
    text = logs[0].read_text(encoding="utf-8")
    assert "Traceback" in text and "TypeError: unsupported operand" in text and "기아(000270)" in text
    assert "fake-dart-key" not in text and "fake-krx-key" not in text
    assert ["000270", "기아", "예상하지 못한 오류: TypeError: unsupported operand"] in report_data(tmp_path)["run"]["failed"]
    assert not [h for h in logging.getLogger("vsf").handlers if isinstance(h, logging.FileHandler)]   # 실행 뒤 떼요


def test_clean_weekly_run_leaves_no_run_log(tmp_path):
    assert run(tmp_path, fake_deps(tmp_path)) == 0
    assert not list((tmp_path / "data" / "logs").glob("*.log"))


def test_run_log_formatter_removes_keys():
    from vsf.cli import RedactingFormatter
    rec = logging.LogRecord("vsf.collect", logging.ERROR, __file__, 1, "요청 실패: %s", ("?crtfc_key=fake-dart-key",), None)
    text = RedactingFormatter(("fake-dart-key", "fake-krx-key", None)).format(rec)
    assert "fake-dart-key" not in text and "crtfc_key=REMOVED" in text


QUOTA_AT_START = {"filings": DartQuotaExceeded(), "corp_codes": DartQuotaExceeded()}
SNAP = lambda t: t / "data" / "runs" / "2026-11-14.json.gz"


def test_same_day_rerun_at_quota_keeps_report_and_snapshot(tmp_path, capsys):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d) == 0
    data_js = INDEX(tmp_path).parent / "data.js"
    report_before, snap_before = data_js.read_bytes(), SNAP(tmp_path).read_bytes()
    capsys.readouterr()
    d.dart = FakeDart.default(raise_in=QUOTA_AT_START)               # 같은 날 다시 실행했는데 한도에 걸림
    assert run(tmp_path, d, no_open=False) == 0
    out = capsys.readouterr().out
    assert f"오늘 리포트가 이미 있어서 그대로 두었어요: {INDEX(tmp_path)}" in out
    assert data_js.read_bytes() == report_before and SNAP(tmp_path).read_bytes() == snap_before
    assert report_data(tmp_path)["run"]["analyzed"] == 2
    assert d.opened == [INDEX(tmp_path)]                              # 있던 리포트를 열어요
    assert len(load_previous(tmp_path / "data" / "runs", D + timedelta(days=7)).stocks) == 2


def test_same_day_rerun_at_quota_no_open(tmp_path):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d) == 0
    d.dart = FakeDart.default(raise_in=QUOTA_AT_START)
    assert run(tmp_path, d) == 0 and d.opened == []


def test_first_run_at_quota_saves_no_snapshot(tmp_path, capsys):
    d = fake_deps(tmp_path)
    d.dart = FakeDart.default(raise_in=QUOTA_AT_START)
    assert run(tmp_path, d) == 0
    assert "분석한 종목이 없어 이번 결과는 저장하지 않았어요." in capsys.readouterr().out
    assert not list((tmp_path / "data" / "runs").glob("*.json.gz"))
    assert INDEX(tmp_path).exists() and report_data(tmp_path)["run"]["analyzed"] == 0


def test_partial_week_carries_pending_stocks_into_snapshot(tmp_path):
    d = fake_deps(tmp_path)
    assert run(tmp_path, d) == 0                                      # 지난주: 두 종목
    d.today = lambda: D + timedelta(days=7)
    d.dart = FakeDart.default(quota_after=1)                         # 이번 주: 기아만 받고 한도
    assert run(tmp_path, d) == 0
    week2 = load_previous(tmp_path / "data" / "runs", D + timedelta(days=8))
    week1 = load_previous(tmp_path / "data" / "runs", D + timedelta(days=1))
    assert week2.date == D + timedelta(days=7) and set(week2.stocks) == {"000270", "030000"}
    assert week2.stocks["030000"] == week1.stocks["030000"]
