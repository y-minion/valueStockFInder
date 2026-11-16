import json
from dataclasses import replace
from datetime import date

import pytest
from helpers import RUN_1114, fp, run, settings_with, snap_only

from vsf.changes import Change
from vsf.collect import Collected
from vsf.evaluate import RunResult
from vsf.extras import Extras
from vsf.model import Criteria
from vsf.report.payload import SCHEMA, build_payload, write_report

S = settings_with()


def _multi(specs, **collected_kwargs):
    """종목코드 → (state, ratio) 로 기아 결과를 복제해 여러 종목짜리 실행 결과를 만들어요."""
    base = RUN_1114.results["000270"]
    results = {}
    for code, (state, ratio) in specs.items():
        company = replace(base.company, code=code, name=f"종목{code}")
        results[code] = replace(base, company=company, state=state,
                                summary=replace(base.summary, ratio=ratio))
    c = RUN_1114.collected
    collected = Collected(today=c.today, price_date=c.price_date, total_listed=10, **collected_kwargs)
    return RunResult(collected=collected, settings_fp=RUN_1114.settings_fp, results=results)


def test_watchlist_sorted_by_ratio():
    r = _multi({"B": ("watch", 0.78), "A": ("buy", 0.70), "C": ("out", 0.5)})
    assert build_payload(r, [], [], None, {}, S)["watchlist"] == ["A", "B"]


def test_watchlist_none_ratio_last_and_code_tiebreak():
    r = _multi({"D": ("watch", None), "C": ("buy", 0.7), "B": ("buy", 0.7), "A": ("watch", 0.9)})
    assert build_payload(r, [], [], None, {}, S)["watchlist"] == ["B", "C", "A", "D"]


def test_summary_and_prev_counts():
    prev = snap_only("000270")
    prev = replace(prev, counts={"buy": 1, "near": 2, "watch": 3, "gate12_ok": 40})
    p = build_payload(RUN_1114, [], [], prev, {}, S)
    assert p["summary"]["prev"]["buy"] == 1
    assert p["run"]["first_run"] is False
    p = build_payload(RUN_1114, [], [], None, {}, S)
    assert p["summary"]["prev"] is None and p["run"]["first_run"] is True
    assert set(p["summary"]) == {"buy", "near", "watch", "gate12_ok", "prev"}


def test_run_section_and_stock_entry_shape():
    r = _multi({"000270": ("buy", 0.7)}, excluded={"우선주": [("005935", "삼성전자우")]},
               failed=[("111111", "실패", "사유")], pending=[("222222", "대기")])
    ch = Change("000270", "종목000270", "new", ("주가",))
    crit = [{"key": "required_return", "label": "요구수익률", "old": 0.1, "new": 0.12}]
    p = build_payload(r, [ch], crit, None, {}, S)
    assert p["schema"] == SCHEMA == 1
    run_ = p["run"]
    assert run_["date"] == "2026-11-14" and run_["price_date"] == "2026-11-13"
    assert run_["analyzed"] == 1 and run_["total_listed"] == 10
    assert run_["excluded"] == {"우선주": [["005935", "삼성전자우"]]}
    assert run_["failed"] == [["111111", "실패", "사유"]] and run_["pending"] == [["222222", "대기"]]
    assert run_["partial"] is True and run_["criteria"] == r.settings_fp
    assert run_["criteria_changes"] == crit
    assert p["changes"] == [{"code": "000270", "name": "종목000270", "kind": "new", "causes": ["주가"]}]
    s = p["stocks"]["000270"]
    assert set(s) == {"name", "code", "market", "latest_year", "industry", "inputs", "cells", "summary",
                      "state", "near", "flags", "notes", "sources", "quick_fail", "criteria",
                      "criteria_overridden", "extra_gate1", "extras", "financial"}
    assert s["market"] == "KOSPI" and s["latest_year"] == 2025 and s["industry"] is None
    assert len(s["cells"]) == 152
    assert isinstance(s["flags"], list) and isinstance(s["notes"], list)


def test_flags_and_sources_present():
    base = RUN_1114.results["000270"]
    asm = replace(base.assembled, flags=("주의",), sources={"F27": "DART"})
    r = RunResult(collected=RUN_1114.collected, settings_fp=RUN_1114.settings_fp,
                  results={"000270": replace(base, assembled=asm)})
    s = build_payload(r, [], [], None, {}, S)["stocks"]["000270"]
    assert s["flags"] == ["주의"] and s["sources"]["F27"] == "DART"


def test_flags_come_from_stock_result_and_year_end_missing_is_listed():
    base = RUN_1114.results["000270"]
    asm = replace(base.assembled, flags=("조립 단계 표시",))
    collected = replace(RUN_1114.collected, year_end_missing=[2019, 2020])
    r = RunResult(collected=collected, settings_fp=RUN_1114.settings_fp,
                  results={"000270": replace(base, assembled=asm, eval_flags=("계산 뒤 표시",))})
    p = build_payload(r, [], [], None, {}, S)
    assert p["stocks"]["000270"]["flags"] == ["조립 단계 표시", "계산 뒤 표시"]
    assert p["run"]["year_end_missing"] == [2019, 2020]
    assert build_payload(RUN_1114, [], [], None, {}, S)["run"]["year_end_missing"] == []


def test_criteria_overridden_false_then_true():
    p = build_payload(RUN_1114, [], [], None, {}, S)
    assert p["stocks"]["000270"]["criteria_overridden"] is False
    r = run(60000.0, criteria=Criteria(required_return=0.12))
    p = build_payload(r, [], [], None, {}, S)
    assert p["stocks"]["000270"]["criteria_overridden"] is True
    assert p["stocks"]["000270"]["criteria"]["required_return"] == 0.12


def test_extras_none_and_present():
    ex = Extras(disclosures=[{"t": "공시"}], news=[], news_link="http://x", quarterly=None,
                weekly_closes=[("2026-11-13", 60000.0)], notes=("메모",))
    s = build_payload(RUN_1114, [], [], None, {"000270": ex}, S)["stocks"]["000270"]
    assert s["extras"]["weekly_closes"] == [["2026-11-13", 60000.0]]
    assert s["extras"]["notes"] == ["메모"] and s["extras"]["news_link"] == "http://x"
    json.dumps(s["extras"])
    assert build_payload(RUN_1114, [], [], None, {}, S)["stocks"]["000270"]["extras"] is None


def test_write_report_files_and_overwrite(tmp_path):
    r = _multi({"000270": ("buy", 0.7)}, pending=[("222222", "대기")])
    p = build_payload(r, [], [], None, {}, S)
    assert p["run"]["partial"] is True
    idx = write_report(p, tmp_path)
    assert idx == tmp_path / "2026-11-14" / "index.html"
    assert {f.name for f in idx.parent.iterdir()} == {"index.html", "stock.html", "report.js",
                                                      "report.css", "data.js"}
    text = (idx.parent / "data.js").read_text(encoding="utf-8")
    assert text.startswith("window.VSF_DATA = {") and text.endswith(";")
    assert json.loads(text.removeprefix("window.VSF_DATA = ").removesuffix(";"))["schema"] == 1
    for page in ("index.html", "stock.html"):
        html = (idx.parent / page).read_text(encoding="utf-8")
        assert '<meta charset="utf-8">' in html and 'id="app"' in html
        assert html.index('<script src="data.js">') < html.index('<script src="report.js">')
    write_report(p, tmp_path)   # 같은 날 덮어쓰기


def test_nan_raises(tmp_path):
    p = build_payload(RUN_1114, [], [], None, {}, S)
    p["stocks"]["000270"]["summary"]["ratio"] = float("nan")
    with pytest.raises(ValueError):
        write_report(p, tmp_path)


def test_financial_dict_and_started_flag():
    from vsf.financial import CapitalRatio, FinancialGate
    base = RUN_1114.results["000270"]
    p = build_payload(RUN_1114, [], [], None, {}, S)
    assert p["stocks"]["000270"]["financial"] is None
    g = FinancialGate("보험", CapitalRatio(210.5, "2026-09", "FISIS"), 130.0)
    r = RunResult(collected=RUN_1114.collected, settings_fp=RUN_1114.settings_fp,
                  results={"000270": replace(base, financial=g)})
    f = build_payload(r, [], [], None, {}, S)["stocks"]["000270"]["financial"]
    assert f == {"kind": "보험", "capital_label": "지급여력비율(K-ICS)", "capital_min": 130.0,
                 "capital": {"value": 210.5, "base_month": "2026-09", "source": "FISIS"}}
    g2 = FinancialGate("증권", None, 100.0)
    r2 = RunResult(collected=RUN_1114.collected, settings_fp=RUN_1114.settings_fp,
                   results={"000270": replace(base, financial=g2)})
    assert build_payload(r2, [], [], None, {}, S)["stocks"]["000270"]["financial"]["capital"] is None


def test_financial_started_only_for_old_snapshot_with_include():
    from dataclasses import replace as rep
    old = snap_only("000270")
    assert "financial" not in old.settings_fp
    assert build_payload(RUN_1114, [], [], old, {}, S)["run"]["financial_started"] is True
    assert build_payload(RUN_1114, [], [], None, {}, S)["run"]["financial_started"] is False
    new = rep(old, settings_fp={**old.settings_fp, "financial": {}})
    assert build_payload(RUN_1114, [], [], new, {}, S)["run"]["financial_started"] is False
    off = rep(S, financial=rep(S.financial, include=False))
    assert build_payload(RUN_1114, [], [], old, {}, off)["run"]["financial_started"] is False
