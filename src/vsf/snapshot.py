"""주간 스냅샷: 그 주의 입력·기준·상태를 저장하고 지난주 것을 읽어요."""
import dataclasses
import gzip
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from vsf.evaluate import RunResult
from vsf.model import Criteria, StockInputs, inputs_from_dict, inputs_to_dict

SUFFIX = ".json.gz"


@dataclass(frozen=True)
class SnapStock:
    name: str
    inputs: StockInputs
    criteria: Criteria
    extra_gate1: str | None
    state: str
    near: bool


@dataclass(frozen=True)
class Snapshot:
    date: date
    settings_fp: dict
    counts: dict[str, int]
    stocks: dict[str, SnapStock]


def run_counts(run: RunResult) -> dict[str, int]:
    rs = list(run.results.values())
    return {
        "buy": sum(r.state == "buy" for r in rs),
        "near": sum(r.near for r in rs),
        "watch": sum(r.state in ("buy", "watch") for r in rs),
        "gate12_ok": sum(r.summary.gate1 != "탈락" and r.summary.gate2 != "탈락" for r in rs),
    }


def save_snapshot(run: RunResult, runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "settings_fp": run.settings_fp,
        "counts": run_counts(run),
        "stocks": {
            code: {"name": r.company.name, "inputs": inputs_to_dict(r.assembled.inputs),
                   "criteria": dataclasses.asdict(r.criteria), "extra_gate1": r.extra_gate1,
                   "state": r.state, "near": r.near}
            for code, r in run.results.items()},
    }
    path = runs_dir / f"{run.collected.today.isoformat()}{SUFFIX}"
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def _read(path: Path, day: date) -> Snapshot:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    stocks = {code: SnapStock(name=s["name"], inputs=inputs_from_dict(s["inputs"]),
                              criteria=Criteria(**s["criteria"]), extra_gate1=s["extra_gate1"],
                              state=s["state"], near=s["near"])
              for code, s in doc["stocks"].items()}
    return Snapshot(date=day, settings_fp=doc["settings_fp"], counts=doc["counts"], stocks=stocks)


def load_previous(runs_dir: Path, before: date) -> Snapshot | None:
    best: tuple[date, Path] | None = None
    for p in Path(runs_dir).glob(f"*{SUFFIX}"):
        try:
            day = date.fromisoformat(p.name.removesuffix(SUFFIX))
        except ValueError:
            continue
        if day < before and (best is None or day > best[0]):
            best = (day, p)
    return _read(best[1], best[0]) if best else None
