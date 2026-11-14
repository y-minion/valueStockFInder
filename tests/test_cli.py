from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fakes import D, FakeDart, FakeKrx
from helpers import write_settings

from vsf.cli import Deps, main
from vsf.data import store as store_mod

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
