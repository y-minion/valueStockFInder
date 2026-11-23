"""주간 스냅샷: 그 주의 입력·기준·상태를 저장하고 지난주 것을 읽어요."""
import dataclasses
import gzip
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from vsf.engine import compute, summarize
from vsf.evaluate import RunResult
from vsf.financial import FinancialGate, gate_from_dict, gate_to_dict
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
    financial: FinancialGate | None = None
    score: float | None = None          # 그 주 점수 총점 (점수 대상이 아니거나 예전 파일이면 None)


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


def _carried_counts(held: list[SnapStock]) -> dict[str, int]:
    """지난 스냅샷에서 옮겨 온 종목의 요약 숫자. run_counts와 같은 뜻이에요."""
    gate12 = 0
    for h in held:
        s = summarize(compute(h.inputs, h.criteria, h.extra_gate1, financial=h.financial))
        gate12 += s.gate1 != "탈락" and s.gate2 != "탈락"
    return {"buy": sum(h.state == "buy" for h in held), "near": sum(h.near for h in held),
            "watch": sum(h.state in ("buy", "watch") for h in held), "gate12_ok": gate12}


NOTHING_TO_SAVE = "분석한 종목이 없어 이번 결과는 저장하지 않았어요."
KEPT_BIGGER = "오늘 이미 저장한 결과가 더 많아서 그대로 두었어요."


class SnapshotNotSaved(Exception):
    """스냅샷을 쓰지 않은 이유. 메시지는 한국어이고 그대로 보여줘요."""


def _stock_doc(name: str, inputs: StockInputs, criteria: Criteria, extra_gate1: str | None,
               state: str, near: bool, financial: FinancialGate | None = None, score: float | None = None) -> dict:
    return {"name": name, "inputs": inputs_to_dict(inputs), "criteria": dataclasses.asdict(criteria),
            "extra_gate1": extra_gate1, "state": state, "near": near,
            "financial": gate_to_dict(financial), "score": score}


def _stock_count(path: Path) -> int:
    """이미 있는 스냅샷의 종목 수. 읽을 수 없는 파일은 0이에요 (지켜 줄 내용이 없어요)."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return len(json.load(f)["stocks"])
    except (OSError, EOFError, ValueError, KeyError, TypeError):
        return 0


def save_snapshot(run: RunResult, runs_dir: Path, carry_from: Snapshot | None = None,
                  scores: dict[str, dict | None] | None = None) -> Path:
    """이번 실행을 그날 스냅샷으로 써요. 다음 주 비교의 기준이 돼요.

    - 하루 한도로 못 받은 종목(pending)은 carry_from(지난 스냅샷)에 있으면 그 값을 그대로 옮겨요.
      그래야 한도에 걸린 주에도 다음 주 비교 기준이 남아요.
    - 저장하는 counts는 옮겨 온 종목까지 센 값이에요 (run_counts는 이번 실행만).
    - scores(종목 → 점수 dict 또는 None)의 총점을 종목마다 남겨요. 옮겨 온 종목은 지난 점수 그대로예요.
    - 종목이 하나도 없으면 쓰지 않아요.
    - 같은 날 스냅샷이 이미 있고 종목이 더 많으면 덮어쓰지 않아요.
    쓰지 않으면 SnapshotNotSaved(한국어 이유)를 던져요.
    """
    runs_dir = Path(runs_dir)
    def total(code: str) -> float | None:
        s = (scores or {}).get(code)
        return None if s is None else s["total"]

    stocks = {code: _stock_doc(r.company.name, r.assembled.inputs, r.criteria, r.extra_gate1, r.state, r.near,
                              r.financial, total(code))
              for code, r in run.results.items()}
    carried: list[SnapStock] = []
    if carry_from is not None:
        for code, _name in run.collected.pending:
            held = carry_from.stocks.get(code)
            if code not in stocks and held is not None:
                stocks[code] = _stock_doc(held.name, held.inputs, held.criteria, held.extra_gate1,
                                          held.state, held.near, held.financial, held.score)
                carried.append(held)
    if not stocks:
        raise SnapshotNotSaved(NOTHING_TO_SAVE)
    path = runs_dir / f"{run.collected.today.isoformat()}{SUFFIX}"
    if path.exists() and _stock_count(path) > len(stocks):
        raise SnapshotNotSaved(KEPT_BIGGER)
    counts = run_counts(run)
    for key, n in _carried_counts(carried).items():
        counts[key] += n
    doc = {"settings_fp": run.settings_fp, "counts": counts, "stocks": stocks}
    runs_dir.mkdir(parents=True, exist_ok=True)
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
                              state=s["state"], near=s["near"],
                              financial=gate_from_dict(s.get("financial")), score=s.get("score"))
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
