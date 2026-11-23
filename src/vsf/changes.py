"""지난주와 비교해 이번 주 변화와 그 원인을 찾아요."""
from dataclasses import dataclass, replace
from typing import Literal

from vsf.config import CRITERIA_LABELS, ReportSettings
from vsf.evaluate import RunResult, state_of
from vsf.financial import FinancialGate
from vsf.snapshot import Snapshot

Kind = Literal["new_buy", "new_watch", "above_buy", "left"]

_SECTIONS = ("criteria", "report", "industry", "financial")


@dataclass(frozen=True)
class Change:
    code: str
    name: str
    kind: Kind
    causes: tuple[str, ...]


def _kind(s0: str, s1: str) -> Kind | None:
    if s1 == "buy" and s0 != "buy":
        return "new_buy"
    if s0 == "out" and s1 == "watch":
        return "new_watch"
    if s0 == "buy" and s1 == "watch":
        return "above_buy"
    if s0 != "out" and s1 == "out":
        return "left"
    return None


def detect_changes(prev: Snapshot | None, run: RunResult, report: ReportSettings) -> list[Change]:
    if prev is None:
        return []
    out: list[Change] = []
    for code, cur in run.results.items():
        p = prev.stocks.get(code)
        s0, s1 = (p.state if p else "out"), cur.state
        kind = _kind(s0, s1)
        if kind is None:
            continue
        name = cur.company.name
        if p is None:
            out.append(Change(code, name, kind, ("새로 분석됨",)))
            continue
        cur_in = cur.assembled.inputs
        if cur.financial is None:
            gate = None
        elif p.financial is None:
            gate = cur.financial
        else:   # 지난주 자료를 이번 주 기준선으로 본 판정
            gate = FinancialGate(p.financial.kind, p.financial.capital, cur.financial.capital_min)
        s_a = state_of(p.inputs, cur.criteria, cur.extra_gate1, report, gate)
        repriced = replace(p.inputs, price=cur_in.price, price_date=cur_in.price_date)
        s_b = state_of(repriced, cur.criteria, cur.extra_gate1, report, gate)
        steps = (("기준 변경", s0 != s_a), ("주가", s_a != s_b), ("재무 갱신", s_b != s1))
        out.append(Change(code, name, kind, tuple(label for label, hit in steps if hit)))
    for code, p in prev.stocks.items():
        if code not in run.results and p.state != "out":
            out.append(Change(code, p.name, "left", ("이번에 분석 안 됨",)))
    return out


def _score_rule(d: dict | None, key: str) -> str | None:
    """점수 항목 설정 → "15점: 5배 미만 15 · 8배 미만 11" (기준 변경 알림용)."""
    if d is None:
        return None
    from vsf.config import ItemRule
    from vsf.score import rule_text
    rule = ItemRule(d["points"], tuple(tuple(s) for s in d.get("steps") or ()), d.get("none_points"))
    return f"{rule.points:g}점: {rule_text(key, rule)}"


def _score_changes(old: dict, new: dict) -> list[dict]:
    from vsf.score import LABELS
    out = []
    for key, val in new.items():
        if key == "items":
            old_items = old.get("items") or {}
            for item, body in val.items():
                if old_items.get(item) != body:
                    out.append({"key": f"score.{item}", "label": f"점수 {LABELS.get(item, item)}",
                                "old": _score_rule(old_items.get(item), item), "new": _score_rule(body, item)})
        elif old.get(key) != val:
            out.append({"key": key, "label": CRITERIA_LABELS.get(key, key), "old": old.get(key), "new": val})
    return out


def criteria_changes(prev_fp: dict, cur_fp: dict) -> list[dict]:
    out = []
    for section in _SECTIONS:
        if section not in prev_fp:
            continue
        old_sec, new_sec = prev_fp[section], cur_fp.get(section, {})
        for key, new in new_sec.items():
            old = old_sec.get(key)
            if old != new:
                label = CRITERIA_LABELS.get(key, key)
                out.append({"key": key, "label": label, "old": old, "new": new})
    if "score" in prev_fp:
        out += _score_changes(prev_fp["score"], cur_fp.get("score", {}))
    return out
