"""기준 점검: 기준마다 분포와 통과 수를 보고, 한 칸 바꾸면 어떻게 되는지 다시 계산해요. 판정은 바꾸지 않아요."""
import statistics
from dataclasses import replace

from vsf.boundary import CAPITAL_STEPS, STEPS
from vsf.config import CRITERIA_LABELS, Settings
from vsf.engine import compute, summarize, watch_state
from vsf.evaluate import StockResult
from vsf.excelfn import excel_round, is_num

_RATE_KEYS = ("required_return", "safety_margin", "payout_min", "payout_max")
_RATE_STEPS = {"required_return": 0.01, "safety_margin": 0.05}
# 엄하게 갈 때의 방향: 최소형은 +, 상한형(부채비율·배당성향 상한)은 -
_SIGN = {"debt_ratio_max": -1, "payout_max": -1}
# (기준 키, 계산기 값 칸, 판정 칸, 단위, 보여줄 배율)
_GENERAL = [("roe_min", "B78", "D78", "%", 1.0), ("debt_ratio_max", "B79", "D79", "%", 1.0),
            ("interest_coverage_min", "B80", "D80", "배", 1.0), ("ocf_to_ni_min", "B81", "D81", "배", 1.0),
            ("payout_min", "B88", "D88", "%", 100.0), ("payout_max", "B88", "D88", "%", 100.0),
            ("fcf_to_div_min", "B89", "D89", "배", 1.0)]
_CAP_KEYS = {"bank_cet1_min": ("금융지주", "은행"), "insurer_kics_min": ("보험",), "securities_ncr_min": ("증권",)}
_ROUND = 10


def _dist(values: list[float]) -> dict | None:
    if not values:
        return None
    if len(values) == 1:
        p25 = med = p75 = values[0]
    else:
        p25, med, p75 = statistics.quantiles(values, n=4, method="inclusive")
    return {"n": len(values), "p25": round(p25, 4), "median": round(med, 4), "p75": round(p75, 4)}


def _value(cells, b_cell: str):
    v = cells.get(b_cell)
    if not is_num(v):
        return None
    return excel_round(v, 2) if b_cell == "B88" else v


def _step(key: str, kind: str | None) -> float:
    if key in _RATE_STEPS:
        return _RATE_STEPS[key]
    if key in _CAP_KEYS:
        return CAPITAL_STEPS[kind]
    return STEPS["payout" if key.startswith("payout") else key]


def _judge(r: StockResult, key: str, delta: float, d_cell: str | None, settings: Settings):
    """기준 하나만 delta만큼 바꿔 다시 계산해요. (상태, D칸) 또는 계산할 수 없으면 None."""
    crit, gate = r.criteria, r.financial
    if key in _CAP_KEYS:
        if gate is None or gate.capital_min is None:
            return None
        gate = replace(gate, capital_min=round(gate.capital_min + delta, _ROUND))
    else:
        crit = replace(crit, **{key: round(getattr(crit, key) + delta, _ROUND)})
        if any(not 0 < getattr(crit, k) < 1 for k in _RATE_KEYS) or crit.payout_min >= crit.payout_max:
            return None
    cells = compute(r.assembled.inputs, crit, r.extra_gate1, financial=gate)
    return watch_state(summarize(cells), settings.report), cells.get(d_cell)


def _variant(stocks, key, sign, step, base, d_cell, settings, scale, track_pass) -> dict | None:
    delta = sign * step
    pass_n, ins, outs = 0, [], []
    for r in stocks:
        res = _judge(r, key, delta, d_cell, settings)
        if res is None:
            if key in _CAP_KEYS:
                continue   # 이 종목은 이 기준이 없어요
            return None
        state, d = res
        pass_n += d == "통과"
        was, now = r.state in ("buy", "watch"), state in ("buy", "watch")
        item = [r.company.code, r.company.name]
        if now and not was:
            ins.append(item)
        elif was and not now:
            outs.append(item)
    return {"threshold": round((base + delta) * scale, 4), "pass": pass_n if track_pass else None,
            "watch_in": sorted(ins), "watch_out": sorted(outs)}


def _row(key, label, unit, stocks, base, scale, d_cell, b_cell, settings) -> dict:
    covered = stocks
    if key in _CAP_KEYS:
        covered = [r for r in stocks if r.financial is not None and r.financial.kind in _CAP_KEYS[key]]
    sign = _SIGN.get(key, 1)
    track = d_cell is not None
    dist = pass_now = None
    if track:
        vals = [v for v in (_value(r.cells, b_cell) for r in covered) if v is not None]
        dist = _dist([round(v * scale, 4) for v in vals])
        pass_now = sum(r.cells.get(d_cell) == "통과" for r in covered)
    step = _step(key, _CAP_KEYS[key][0] if key in _CAP_KEYS else None)
    v = {name: _variant(covered, key, s * sign, step, base, d_cell, settings, scale, track)
         for name, s in (("stricter", 1), ("looser", -1))}
    return {"key": key, "label": label, "threshold": round(base * scale, 4), "unit": unit,
            "dist": dist, "pass_now": pass_now, **v}


def _group(name, stocks, settings: Settings) -> dict:
    c, fs = settings.criteria, settings.financial
    label = CRITERIA_LABELS
    rows = []

    def general(key, b, d, unit, scale):
        rows.append(_row(key, label[key], unit, stocks, getattr(c, key), scale, d, b, settings))

    spec = {k: (b, d, u, s) for k, b, d, u, s in _GENERAL}
    tail = ("required_return", "safety_margin")
    if name == "일반 회사":
        for k, *_ in _GENERAL:
            general(k, *spec[k][:2], *spec[k][2:])
    else:
        general("roe_min", *spec["roe_min"][:2], *spec["roe_min"][2:])
        kinds = {r.financial.kind for r in stocks}
        for key, ks in _CAP_KEYS.items():
            if kinds & set(ks):
                rows.append(_row(key, label[key], "%", stocks, getattr(fs, key), 1.0, "F_CAP_D", "F_CAP_B", settings))
        for k in ("payout_min", "payout_max"):
            general(k, *spec[k][:2], *spec[k][2:])
    for k in tail:
        rows.append(_row(k, label[k], "%", stocks, getattr(c, k), 100.0, None, None, settings))
    return {"group": name, "n": len(stocks), "rows": rows}


def criteria_check(results: dict[str, StockResult], settings: Settings, partial: bool) -> dict:
    pop = [r for r in results.values() if not r.assembled.quick_fail]
    general = [r for r in pop if r.financial is None]
    fin = [r for r in pop if r.financial is not None]
    groups = [_group(n, s, settings) for n, s in (("일반 회사", general), ("금융회사", fin)) if s]
    inds = {}
    for r in pop:
        if r.industry is not None:
            inds.setdefault(r.industry.group_code, r.industry)
    industry = [{"group_name": i.group_name, "size": i.size, "roe_median": i.roe_median}
                for i in sorted(inds.values(), key=lambda i: (-i.size, i.group_name))]
    return {"partial": partial, "groups": groups, "industry": industry}
