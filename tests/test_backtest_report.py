"""백테스트 결과 페이지 (2026-11-24 백테스트 설계 6장)."""
from datetime import date

import pytest
from vsf.backtest.report import Row, annual, money, signed, summarize_row, write_backtest_report
from vsf.backtest.simulate import FLAG_GATES, SimResult, Trade

DAYS = [date(2020, 1, 2), date(2020, 1, 3), date(2021, 1, 4)]
META = {"start": date(2018, 4, 1), "end": date(2026, 11, 20), "second_start": date(2020, 11, 2),
        "vintages": 12000, "substitutes": 240, "failures": {"결산월이 12월이 아니에요": 30, "주가 자료가 없어요": 4}}


def _trade(code="000270", name="기아", reason="적정가 도달", flags=()):
    sold = reason != "보유 중"
    return Trade(code=code, name=name, first_buy=date(2020, 1, 2), last_buy=date(2020, 1, 2), invested=1_300_000.0,
                 shares=100.0, sell_date=date(2021, 1, 4) if sold else None, sell_price=17_000.0 if sold else None,
                 proceeds=1_695_750.0 if sold else None, dividends=50_000.0, reason=reason,
                 basis="2019 사업보고서 · C 과거 배당수익률 · 적정가 17,000원 · 매수선 12,750원", flags=tuple(flags))


def _result(trades=()):
    return SimResult(days=DAYS, value=[1_300_000.0, 1_352_000.0, 1_745_750.0], cash=[0.0, 0.0, 1_745_750.0],
                     deposits=[(DAYS[0], 1_300_000.0)], trades=list(trades), flags=[])


def _row(label, kind, trades=()):
    return Row(label=label, kind=kind, result=_result(trades), invested=103_000_000.0, final=135_200_000.0,
               xirr=0.0731, mdd=(-0.342, date(2020, 3, 19)), yearly={2020: 0.04, 2021: 0.2913}, cash_share=0.12)


def test_money_and_percent_formatting():
    assert money(135_200_000) == "1억 3,520만 원" and money(100_000_000) == "1억 원"
    assert money(52_000_000) == "5,200만 원" and money(9_500) == "9,500원"
    assert annual(0.0731) == "연 7.3%" and annual(None) == "—"
    assert signed(-0.342) == "−34.2%" and signed(0.05) == "+5.0%"


def test_summarize_row_computes_money_weighted_and_time_weighted_numbers():
    r = summarize_row("지금 규칙", "규칙", _result())
    assert (r.invested, r.final) == (1_300_000.0, 1_745_750.0)
    assert r.xirr == pytest.approx(1_745_750 / 1_300_000 - 1, rel=0.02)
    assert r.yearly[2021] == pytest.approx(1_745_750 / 1_352_000 - 1)
    assert r.mdd == (0.0, None) and r.cash_share == pytest.approx(1 / 3)


def test_report_has_summary_rows_chart_and_warnings(tmp_path):
    path = write_backtest_report([_row("지금 규칙", "규칙"), _row("나스닥100 (TIGER 미국나스닥100)", "비교")], [], META,
                                 tmp_path, date(2026, 11, 24))
    html = path.read_text(encoding="utf-8")
    assert path == tmp_path / "backtest" / "2026-11-24" / "index.html"
    for s in ("지금 규칙", "나스닥100", "연 7.3%", "1억 3,520만 원", "−34.2%", "2020-03-19", "분배금(배당)이 빠진",
              "관문 ④", "<svg", "12,000", "결산월이 12월이 아니에요 30", "+29.1%"):
        assert s in html, s


def test_trades_table_shows_basis_reason_flags_and_escapes_names(tmp_path):
    trades = [_trade(), _trade("005930", "<b>이상한</b>", "보유 중", flags=(FLAG_GATES,))]
    path = write_backtest_report([_row("지금 규칙", "규칙", trades)], [_row("지금 규칙", "규칙")], META, tmp_path,
                                 date(2026, 11, 24))
    html = path.read_text(encoding="utf-8")
    for s in ("적정가 도달", "2019 사업보고서 · C 과거 배당수익률", "보유 중", FLAG_GATES, "&lt;b&gt;이상한&lt;/b&gt;",
              "+34.3%", "2020-11-02"):
        assert s in html, s
    assert "<b>이상한</b>" not in html

def test_blocked_bundles_are_counted_on_the_page(tmp_path):
    path = write_backtest_report([_row("지금 규칙", "규칙")], [], {**META, "blocked": 7}, tmp_path, date(2026, 11, 24))
    assert "사는 데 쓰지 않은 묶음 7개" in path.read_text(encoding="utf-8")
