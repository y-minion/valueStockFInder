"""uv run backtest.py — 자료 받기·멈춤·결과 페이지 (2026-11-24 백테스트 설계 7장)."""
import re
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fakes import _BASE, FakeDart, FakeKrx, _listed, corp_of, mem_store
from helpers import write_settings
from vsf.backtest.cli import _cma_growth, main
from vsf.backtest.market import Market
from vsf.cli import Deps

KEYS = '[dart]\napi_key = "fake-dart-key"\n[krx]\nauth_key = "fake-krx-key"\n'
TODAY = date(2026, 11, 24)
START, END = date(2026, 3, 2), date(2026, 5, 29)
ITEMS = [_listed("000270", "기아"), _listed("030000", "제일기획")]


def _settings(tmp_path: Path) -> Path:
    (tmp_path / "keys.toml").write_text(KEYS, encoding="utf-8")
    path = write_settings(tmp_path)
    text = path.read_text(encoding="utf-8")
    for key, value in (("start", START), ("end", END), ("second_start", date(2026, 4, 1))):
        text = re.sub(rf"^{key} = \S+", f"{key} = {value.isoformat()}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")
    return path


def _krx() -> FakeKrx:
    days, etf, index = {}, {}, {}
    for row in _BASE[5].values():
        days[row.date] = {x.code: replace(row, code=x.code, name=x.name) for x in ITEMS}
    d, k = START, 0
    while d <= END:
        if d.weekday() < 5:
            days[d] = {x.code: replace(_BASE[6], date=d, code=x.code, name=x.name) for x in ITEMS}
            etf[d] = {"214980": 100_000.0 + k, "357870": 50_000.0 + k, "133690": 150_000.0 + 50 * k,
                      "143850": 70_000.0 + 10 * k, "161510": 21_000.0, "360750": 23_000.0 + 5 * k}
            index[d] = {"코스피": 4000.0 + k}
            k += 1
        d += timedelta(days=1)
    return FakeKrx(ITEMS, days, etf=etf, index=index)


def _dart(**kw) -> FakeDart:
    filings = [{"corp_code": corp_of(x.code), "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260310"} for x in ITEMS]
    return FakeDart({"000270": FakeDart.entry(), "030000": FakeDart.entry()}, filings=filings, **kw)


def _deps(dart: FakeDart, opened: list) -> Deps:
    return Deps(make_dart=lambda keys, store, settings: dart, make_krx=lambda keys, store: _krx(),
                make_naver=lambda keys: None, make_fisis=lambda keys, store: None, today=lambda: TODAY,
                open_path=opened.append, keep_awake=lambda: None)


def _run(tmp_path, dart, opened=None, *extra):
    args = ["--settings", str(_settings(tmp_path)), "--keys", str(tmp_path / "keys.toml"), *extra]
    return main(args, deps=_deps(dart, opened if opened is not None else []))


PAGE = lambda t: t / "reports" / "backtest" / TODAY.isoformat() / "index.html"   # noqa: E731


def test_end_to_end_small_market_writes_report(tmp_path, capsys):
    opened: list = []
    assert _run(tmp_path, _dart(), opened) == 0
    html = PAGE(tmp_path).read_text(encoding="utf-8")
    for s in ("계산기 백테스트", "지금 규칙", "배당성향 하한 없음", "나스닥100", "코스피", "S&amp;P500 환노출", "2026-04-01부터",
              "정상 EPS = 5년 평균과 최근 해 중 낮은 값", "관문 ①② 탈락하면 팔기", "코스피 200 배당 포함 (25/50 NTR)",
              "배당을 다시 넣은 지수"):
        assert s in html, s
    assert opened == [PAGE(tmp_path)]
    out = capsys.readouterr().out
    assert "지금 규칙" in out and "리포트" in out


def test_no_open_flag(tmp_path):
    opened: list = []
    assert _run(tmp_path, _dart(), opened, "--no-open") == 0 and opened == []


def test_quota_stop_says_how_to_resume(tmp_path, capsys):
    assert _run(tmp_path, _dart(quota_after=1), None, "--no-open") == 0
    out = capsys.readouterr().out
    assert "내일" in out and "uv run backtest.py" in out and "이어서" in out
    assert not PAGE(tmp_path).exists()
    assert _run(tmp_path, _dart(), None, "--no-open") == 0 and PAGE(tmp_path).exists()      # 같은 저장소로 다시 돌리면 끝나요


def test_keys_are_not_printed_or_logged(tmp_path, capsys):
    _run(tmp_path, _dart(raise_for={"030000": TypeError("boom")}), None, "--no-open")
    captured = capsys.readouterr()
    logs = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "data" / "logs").glob("*.log"))
    for text in (captured.out, captured.err, logs):
        assert "fake-dart-key" not in text and "fake-krx-key" not in text


def test_unexpected_error_is_logged_without_keys(tmp_path, capsys):
    def broken(keys, store):
        raise RuntimeError("뜻밖의 고장 fake-krx-key")
    deps = replace(_deps(_dart(), []), make_krx=broken)
    args = ["--settings", str(_settings(tmp_path)), "--keys", str(tmp_path / "keys.toml"), "--no-open"]
    assert main(args, deps=deps) == 1
    err = capsys.readouterr().err
    assert "예상하지 못한 오류" in err and "fake-krx-key" not in err
    logs = list((tmp_path / "data" / "logs").glob("backtest-error-*.log"))
    assert len(logs) == 1 and "Traceback" in logs[0].read_text(encoding="utf-8")
    assert "fake-krx-key" not in logs[0].read_text(encoding="utf-8")


def test_page_header_follows_the_backtest_settings(tmp_path):
    path = _settings(tmp_path)
    text = path.read_text(encoding="utf-8")
    for key, value in (("monthly", "1000000"), ("max_holdings", "3"), ("cost_rate", "0.001"), ("max_weight", "0.3"),
                       ("min_trading_value", "200000000")):
        text = re.sub(rf"^{key} = \S+", f"{key} = {value}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")
    assert main(["--settings", str(path), "--keys", str(tmp_path / "keys.toml"), "--no-open"],
                deps=_deps(_dart(), [])) == 0
    page = PAGE(tmp_path).read_text(encoding="utf-8")
    assert "매달 첫 거래일에 100만 원" in page and "최대 3개" in page and "각각 0.1%를" in page
    assert "한 종목은 전체의 30%까지" in page and "20일 평균 거래대금 2억 원 미만은 사지 않아요" in page
    assert "130만" not in page and "0.25%" not in page


def test_cma_growth_keeps_the_return_over_a_day_without_a_close():
    # CMA 대용 ETF 시세가 하루 비어도, 다음 날 그 전 종가와 비교해서 이자를 잃지 않아요.
    d1, d2, d3 = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)
    rows = {d: {"000270": replace(_BASE[6], date=d)} for d in (d1, d2, d3)}
    krx = FakeKrx(ITEMS[:1], rows, etf={d1: {"214980": 100.0}, d3: {"214980": 102.0}})
    growth = _cma_growth(Market(krx, mem_store(), d1, d3, today=TODAY), (("214980", date(2018, 1, 1)),))
    assert growth(d1, d2) == 1.0 and growth(d2, d3) == pytest.approx(1.02)
