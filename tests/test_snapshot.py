import gzip
import json
from datetime import date

from helpers import RUN_1114, run
from vsf.snapshot import load_previous, run_counts, save_snapshot


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
