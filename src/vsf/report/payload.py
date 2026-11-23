"""리포트 자료(payload)를 만들고 리포트 폴더에 써요."""
import json
import shutil
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from vsf.boundary import boundaries, near_miss_state
from vsf.changes import Change
from vsf.criteria_check import criteria_check
from vsf.evaluate import RunResult, StockResult
from vsf.extras import Extras
from vsf.financial import CAPITAL_LABELS
from vsf.liquidity import THIN_TRADING_WON
from vsf.model import inputs_to_dict
from vsf.score import GROUPS, JUDGMENT, rank
from vsf.snapshot import Snapshot, run_counts

SCHEMA = 1


def _extras(e: Extras | None) -> dict | None:
    if e is None:
        return None
    d = asdict(e)
    d["weekly_closes"] = [list(w) for w in d["weekly_closes"]]
    d["notes"] = list(d["notes"])
    return d


def _financial(r: StockResult) -> dict | None:
    g = r.financial
    if g is None:
        return None
    return {"kind": g.kind, "capital_label": CAPITAL_LABELS.get(g.kind), "capital_min": g.capital_min,
            "capital": None if g.capital is None else
            {"value": g.capital.value, "base_month": g.capital.base_month, "source": g.capital.source}}


def _stock(r: StockResult, extras: Extras | None, settings) -> dict:
    a = r.assembled
    return {
        "name": r.company.name, "code": r.company.code, "market": r.company.market,
        "latest_year": a.latest_year,
        "industry": asdict(r.industry) if r.industry else None,
        "inputs": inputs_to_dict(a.inputs), "cells": dict(r.cells), "summary": asdict(r.summary),
        "state": r.state, "near": r.near, "flags": list(r.flags), "notes": list(a.notes),
        "sources": dict(a.sources), "quick_fail": a.quick_fail,
        "criteria": asdict(r.criteria), "criteria_overridden": r.criteria != settings.criteria,
        "extra_gate1": r.extra_gate1, "extras": _extras(extras),
        "financial": _financial(r),
        "boundaries": [asdict(b) for b in boundaries(r.cells, r.criteria, r.financial)],
    }


def _share(r: StockResult, results: dict[str, StockResult],
           liquidity: dict[str, tuple[float, int]]) -> dict:
    """우선주 칸: 보통주 코드·주가·최근 해 DPS, 거래대금 평균 (우선주 설계 8장)."""
    common = r.company.common_code
    held = results.get(common) if common else None
    ci = held.assembled.inputs if held is not None else None
    liq = liquidity.get(r.company.code)
    return {"share_class": "우선" if common else "보통", "common_code": common,
            "common_price": ci.price if ci else None,
            "common_dps": ci.years[-1].dps if ci and ci.years else None,
            "liquidity": None if liq is None else {"avg": liq[0], "days": liq[1], "thin": liq[0] < THIN_TRADING_WON}}


def _score_summary(scores: dict[str, dict | None], partial: bool, changed: bool, settings) -> dict:
    got = [s for s in scores.values() if s is not None]
    return {"eligible": len(got), **{g: sum(s["grade"] == g for s in got) for g in "ABCD"},
            "partial": partial, "top_n": settings.score.top_n, "settings_changed": changed,
            "groups": [[key, label] for key, label, _ in GROUPS],
            "judgment": [[key, q, list(choices), list(points)] for key, q, choices, points in JUDGMENT]}


def build_payload(run: RunResult, changes: list[Change], crit_changes: list[dict],
                  prev: Snapshot | None, extras: dict[str, Extras], settings,
                  scores: dict[str, dict | None] | None = None, score_partial: bool = False,
                  liquidity: dict[str, tuple[float, int]] | None = None) -> dict:
    """scores: 종목 → 점수 dict(점수 대상이 아니면 None). score_partial: 하루 한도로 점수 자료를 다 못 받음."""
    c = run.collected
    scores = scores or {}
    liquidity = liquidity or {}
    scored = {code: s for code, s in scores.items() if s is not None and code in run.results}
    score_rank = rank(scored, {code: run.results[code].summary.ratio for code in scored})
    changed = bool(prev is not None and "score" in prev.settings_fp
                   and prev.settings_fp["score"] != run.settings_fp.get("score"))

    def score_prev(code: str) -> float | None:
        if prev is None or changed or code not in scored:
            return None
        held = prev.stocks.get(code)
        return None if held is None else held.score

    watch = [(code, r) for code, r in run.results.items() if r.state in ("buy", "watch")]
    watch.sort(key=lambda kv: (kv[1].summary.ratio is None, kv[1].summary.ratio or 0.0, kv[0]))
    near = [(code, r) for code, r in run.results.items() if r.state == "out" and near_miss_state(
        r.cells, boundaries(r.cells, r.criteria, r.financial), settings.report, r.extra_gate1) in ("buy", "watch")]
    near.sort(key=lambda kv: (kv[1].summary.ratio is None, kv[1].summary.ratio or 0.0, kv[0]))
    return {
        "schema": SCHEMA,
        "run": {
            "date": c.today.isoformat(), "price_date": c.price_date.isoformat(),
            "analyzed": len(run.results), "total_listed": c.total_listed,
            "excluded": {why: [list(x) for x in v] for why, v in c.excluded.items()},
            "failed": [list(x) for x in c.failed], "pending": [list(x) for x in c.pending],
            "partial": bool(c.pending), "first_run": prev is None,
            "year_end_missing": list(c.year_end_missing),
            "criteria": run.settings_fp, "criteria_changes": crit_changes,
            "financial_started": bool(prev is not None and "financial" not in prev.settings_fp
                                      and settings.financial.include),
            "thin_trading_won": THIN_TRADING_WON,
        },
        "summary": {**run_counts(run), "prev": prev.counts if prev else None},
        "changes": [{"code": x.code, "name": x.name, "kind": x.kind, "causes": list(x.causes)}
                    for x in changes],
        "watchlist": [code for code, _ in watch],
        "near_miss": [code for code, _ in near],
        "stocks": {code: {**_stock(r, extras.get(code), settings), "score": scored.get(code),
                          "score_prev": score_prev(code), **_share(r, run.results, liquidity)}
                   for code, r in run.results.items()},
        "score_rank": score_rank,
        "score_summary": _score_summary(scored, score_partial, changed, settings),
        "criteria_check": criteria_check(run.results, settings, partial=bool(c.pending)),
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
