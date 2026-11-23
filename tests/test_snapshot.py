import gzip
import json
from dataclasses import replace
from datetime import date

import pytest
from helpers import RUN_1114, run, snap_only
from vsf.evaluate import RunResult
from vsf.snapshot import SnapshotNotSaved, load_previous, run_counts, save_snapshot


def test_snapshot_roundtrip_and_same_day_ignored(tmp_path):
    p = save_snapshot(RUN_1114, tmp_path); assert p.name == "2026-11-14.json.gz"
    assert load_previous(tmp_path, date(2026,11,14)) is None
    assert load_previous(tmp_path, date(2026,11,21)).stocks["000270"].inputs == RUN_1114.results["000270"].assembled.inputs


def test_file_is_gzip_json_with_korean_and_no_temp_left(tmp_path):
    p = save_snapshot(RUN_1114, tmp_path)
    doc = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
    assert doc["stocks"]["000270"]["name"] == "기아" and doc["stocks"]["000270"]["state"] == "buy"
    assert "기아" in gzip.decompress(p.read_bytes()).decode("utf-8")
    assert [f.name for f in tmp_path.iterdir()] == ["2026-11-14.json.gz"]


def test_same_day_overwrites(tmp_path):
    save_snapshot(run(kia_price=97000.0), tmp_path)
    save_snapshot(RUN_1114, tmp_path)
    assert load_previous(tmp_path, date(2026, 11, 15)).stocks["000270"].state == "buy"


def test_load_previous_picks_latest_before_and_skips_non_dates(tmp_path):
    for d in ("2026-10-31", "2026-11-07"):
        doc = {"settings_fp": {}, "counts": {"buy": int(d[-2:])}, "stocks": {}}
        (tmp_path / f"{d}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))
    (tmp_path / "notes.json.gz").write_bytes(b"junk")
    assert load_previous(tmp_path, date(2026, 11, 14)).counts == {"buy": 7}
    assert load_previous(tmp_path, date(2026, 11, 7)).counts == {"buy": 31}
    assert load_previous(tmp_path, date(2026, 10, 31)) is None


def test_run_counts():
    assert run_counts(RUN_1114) == {"buy": 1, "near": 1, "watch": 1, "gate12_ok": 1}
    assert run_counts(run(kia_price=97000.0)) == {"buy": 0, "near": 0, "watch": 0, "gate12_ok": 1}


def _partial(pending, results=True):
    """기아는 분석하고 pending 종목은 하루 한도로 못 받은 실행."""
    base = run(kia_price=60000.0)
    return RunResult(collected=replace(base.collected, pending=list(pending)), settings_fp=base.settings_fp,
                     results=base.results if results else {})


def _prev_with_cheil():
    """지난주 스냅샷: 기아·제일기획·SK(999999, 이번 주 목록에 없음)."""
    prev = snap_only("030000", state="watch", name="제일기획")
    kia = snap_only("000270", state="out").stocks["000270"]
    gone = snap_only("000270", state="buy", name="없어진 종목").stocks["000270"]
    return replace(prev, stocks={**prev.stocks, "000270": kia, "999999": gone})


def test_partial_run_carries_pending_stocks_from_previous(tmp_path):
    prev = _prev_with_cheil()
    save_snapshot(_partial([("030000", "제일기획")]), tmp_path, carry_from=prev)
    got = load_previous(tmp_path, date(2026, 11, 15))
    assert set(got.stocks) == {"000270", "030000"}                 # 999999는 pending이 아니라서 안 옮겨요
    assert got.stocks["030000"] == prev.stocks["030000"]           # 지난 값 그대로
    assert got.stocks["000270"].state == "buy"                     # 이번에 분석한 종목은 이번 결과
    assert got.counts["watch"] == run_counts(_partial([]))["watch"] + 1   # 옮겨 온 종목도 센다 (제일기획: watch)


def test_saved_counts_include_carried_stocks_but_run_counts_does_not(tmp_path):
    from vsf.engine import compute, summarize
    prev = snap_only("030000", state="buy", name="제일기획")
    held = prev.stocks["030000"]
    s = summarize(compute(held.inputs, held.criteria, held.extra_gate1))
    assert s.gate1 != "탈락" and s.gate2 != "탈락"                   # 옮겨 온 종목은 ①②를 통과해요
    run_ = _partial([("030000", "제일기획")])
    base = run_counts(run_)
    save_snapshot(run_, tmp_path, carry_from=prev)
    saved = load_previous(tmp_path, date(2026, 11, 15)).counts
    assert saved["buy"] == base["buy"] + 1 and saved["gate12_ok"] == base["gate12_ok"] + 1
    assert saved["watch"] == base["watch"] + 1 and saved["near"] == base["near"]
    assert run_counts(run_) == base                                  # 이번 주 타일은 이번 실행만


def test_zero_stock_run_writes_no_snapshot(tmp_path):
    with pytest.raises(SnapshotNotSaved, match="^분석한 종목이 없어 이번 결과는 저장하지 않았어요.$"):
        save_snapshot(_partial([("000270", "기아")], results=False), tmp_path)
    with pytest.raises(SnapshotNotSaved):                           # 지난주에도 없던 종목만 대기 중
        save_snapshot(_partial([("123450", "새 종목")], results=False), tmp_path, carry_from=_prev_with_cheil())
    assert list(tmp_path.iterdir()) == []


def test_carried_stocks_alone_are_saved(tmp_path):
    p = save_snapshot(_partial([("030000", "제일기획"), ("000270", "기아")], results=False), tmp_path,
                      carry_from=_prev_with_cheil())
    assert set(load_previous(tmp_path, date(2026, 11, 15)).stocks) == {"000270", "030000"} and p.exists()


def test_smaller_same_day_snapshot_keeps_the_bigger_one(tmp_path):
    first = save_snapshot(_partial([("030000", "제일기획")]), tmp_path, carry_from=_prev_with_cheil())
    before = first.read_bytes()
    with pytest.raises(SnapshotNotSaved, match="^오늘 이미 저장한 결과가 더 많아서 그대로 두었어요.$"):
        save_snapshot(RUN_1114, tmp_path)                           # 1종목 < 2종목
    assert first.read_bytes() == before
    assert [f.name for f in tmp_path.iterdir()] == ["2026-11-14.json.gz"]


def test_unreadable_same_day_snapshot_is_replaced(tmp_path):
    (tmp_path / "2026-11-14.json.gz").write_bytes(b"not gzip")
    save_snapshot(RUN_1114, tmp_path)
    assert set(load_previous(tmp_path, date(2026, 11, 15)).stocks) == {"000270"}


def _loss_inputs():
    from helpers import _kia_inputs
    inputs = _kia_inputs(60000.0)
    years = list(inputs.years)
    years[0] = replace(years[0], net_income=-100.0)
    return replace(inputs, years=tuple(years))


def test_financial_gate_round_trips_through_snapshot(tmp_path):
    from vsf.financial import CapitalRatio, FinancialGate
    gate = FinancialGate("보험", CapitalRatio(180.5, "2026-06", "FISIS"), 130.0)
    r = RUN_1114
    res = replace(r.results["000270"], financial=gate)
    save_snapshot(replace(r, results={"000270": res}), tmp_path)
    assert load_previous(tmp_path, date(2026, 11, 21)).stocks["000270"].financial == gate


def test_old_snapshot_without_financial_reads_none(tmp_path):
    save_snapshot(RUN_1114, tmp_path)
    p = tmp_path / "2026-11-14.json.gz"
    doc = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
    for s in doc["stocks"].values():
        del s["financial"]
    p.write_bytes(gzip.compress(json.dumps(doc).encode()))
    assert load_previous(tmp_path, date(2026, 11, 21)).stocks["000270"].financial is None


def test_carried_financial_stock_counts_with_sector_verdict():
    from vsf.config import ReportSettings
    from vsf.evaluate import state_of
    from vsf.financial import FinancialGate
    from vsf.model import Criteria
    from vsf.snapshot import SnapStock, _carried_counts
    inputs = _loss_inputs()
    gate = FinancialGate("은행", None, 9.0)
    kw = dict(name="기아", inputs=inputs, criteria=Criteria(), extra_gate1=None, state="out", near=False)
    assert _carried_counts([SnapStock(**kw, financial=gate)])["gate12_ok"] == 0
    assert _carried_counts([SnapStock(**kw)])["gate12_ok"] == 1


# ---- 점수 ----

def test_snapshot_stores_score_and_carries_it(tmp_path):
    save_snapshot(RUN_1114, tmp_path, scores={"000270": {"total": 62.0}})
    assert load_previous(tmp_path, date(2026, 11, 21)).stocks["000270"].score == 62.0
    prev = _prev_with_cheil()
    prev = replace(prev, stocks={**prev.stocks, "030000": replace(prev.stocks["030000"], score=40.0)})
    save_snapshot(_partial([("030000", "제일기획")]), tmp_path, carry_from=prev, scores={"000270": None})
    got = load_previous(tmp_path, date(2026, 11, 22))
    assert got.stocks["030000"].score == 40.0 and got.stocks["000270"].score is None


def test_old_snapshot_without_score_reads_none(tmp_path):
    save_snapshot(RUN_1114, tmp_path)
    p = tmp_path / "2026-11-14.json.gz"
    doc = json.loads(gzip.decompress(p.read_bytes()))
    del doc["stocks"]["000270"]["score"]
    p.write_bytes(gzip.compress(json.dumps(doc).encode()))
    assert load_previous(tmp_path, date(2026, 11, 21)).stocks["000270"].score is None
