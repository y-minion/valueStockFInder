"""리포트 자료(payload)를 만들고 리포트 폴더에 써요."""
import json
import shutil
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from vsf.changes import Change
from vsf.evaluate import RunResult, StockResult
from vsf.extras import Extras
from vsf.model import inputs_to_dict
from vsf.snapshot import Snapshot, run_counts

SCHEMA = 1


def _extras(e: Extras | None) -> dict | None:
    if e is None:
        return None
    d = asdict(e)
    d["weekly_closes"] = [list(w) for w in d["weekly_closes"]]
    d["notes"] = list(d["notes"])
    return d


def _stock(r: StockResult, extras: Extras | None, settings) -> dict:
    a = r.assembled
    return {
        "name": r.company.name, "code": r.company.code, "market": r.company.market,
        "latest_year": a.latest_year,
        "industry": asdict(r.industry) if r.industry else None,
        "inputs": inputs_to_dict(a.inputs), "cells": dict(r.cells), "summary": asdict(r.summary),
        "state": r.state, "near": r.near, "flags": list(a.flags), "notes": list(a.notes),
        "sources": dict(a.sources), "quick_fail": a.quick_fail,
        "criteria": asdict(r.criteria), "criteria_overridden": r.criteria != settings.criteria,
        "extra_gate1": r.extra_gate1, "extras": _extras(extras),
    }


def build_payload(run: RunResult, changes: list[Change], crit_changes: list[dict],
                  prev: Snapshot | None, extras: dict[str, Extras], settings) -> dict:
    c = run.collected
    watch = [(code, r) for code, r in run.results.items() if r.state in ("buy", "watch")]
    watch.sort(key=lambda kv: (kv[1].summary.ratio is None, kv[1].summary.ratio or 0.0, kv[0]))
    return {
        "schema": SCHEMA,
        "run": {
            "date": c.today.isoformat(), "price_date": c.price_date.isoformat(),
            "analyzed": len(run.results), "total_listed": c.total_listed,
            "excluded": {why: [list(x) for x in v] for why, v in c.excluded.items()},
            "failed": [list(x) for x in c.failed], "pending": [list(x) for x in c.pending],
            "partial": bool(c.pending), "first_run": prev is None,
            "criteria": run.settings_fp, "criteria_changes": crit_changes,
        },
        "summary": {**run_counts(run), "prev": prev.counts if prev else None},
        "changes": [{"code": x.code, "name": x.name, "kind": x.kind, "causes": list(x.causes)}
                    for x in changes],
        "watchlist": [code for code, _ in watch],
        "stocks": {code: _stock(r, extras.get(code), settings) for code, r in run.results.items()},
    }


def write_report(payload: dict, reports_dir: Path) -> Path:
    # 직렬화를 먼저 해서, 실패하면 폴더를 건드리지 않아요 (NaN이면 ValueError).
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    out = Path(reports_dir) / payload["run"]["date"]
    out.mkdir(parents=True, exist_ok=True)
    for asset in (resources.files("vsf.report") / "assets").iterdir():
        if asset.is_file():
            with resources.as_file(asset) as src:
                shutil.copyfile(src, out / asset.name)
    (out / "data.js").write_text(f"window.VSF_DATA = {data};", encoding="utf-8")
    return out / "index.html"
