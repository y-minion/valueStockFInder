"""점수 계산: 계산기 칸과 DART 점수 자료로 100점 만점 점수를 매겨요 (점수 순위 설계 5장).

판단 항목(성장 잠재력·경영·브랜드·이익 지속성)은 점수에 넣지 않고 JUDGMENT로 카드와 /자문에 넘겨요.
"""
from __future__ import annotations

from vsf.config import ITEM_OPS, ItemRule, ScoreSettings
from vsf.data.score_facts import ScoreFacts
from vsf.excelfn import is_num

GROUPS = (("cheap", "싼가", ("per", "pbr", "ratio")),
          ("steady", "꾸준히 버나", ("roe", "no_loss", "ttm")),
          ("return", "주주환원", ("yield", "streak", "freq", "buyback", "cancel", "treasury")),
          ("other", "기타", ("subsidiary",)))
LABELS = {"per": "PER", "pbr": "PBR", "ratio": "주가÷적정가", "roe": "ROE 5년 평균",
          "no_loss": "최근 5년 적자 없음", "ttm": "최근 4분기 실적 유지", "yield": "배당수익률",
          "streak": "배당 연속 인상", "freq": "분기·반기 배당", "buyback": "자사주 매입·소각 (최근 3년 매년)",
          "cancel": "연간 소각 비율", "treasury": "자사주 보유 비율", "subsidiary": "상장 자회사 없음"}
JUDGMENT = (  # 점수에 넣지 않는 판단 항목 (key, 질문, 선택지, 평가표 배점) — 카드와 /자문이 그대로 써요
    ("sustain", "이익이 앞으로도 지속 가능한가", ("대체로 지속 가능", "불안정"), (5, 0)),
    ("growth", "미래 성장 잠재력", ("매우 높다", "높다", "보통", "낮다"), (10, 7, 5, 3)),
    ("management", "기업 경영", ("우수한 경영자", "전문 경영자", "실적이 저조한 오너 경영"), (10, 5, 0)),
    ("brand", "세계적 브랜드·경쟁력", ("있다", "없다"), (5, 0)),
)
_OP_WORD = {"lt": "미만", "le": "이하", "ge": "이상", "gt": "초과", "freq": "이상"}
_FREQ = {4: "분기", 2: "반기", 1: "연 1회"}
_UNIT = {"per": "배", "pbr": "배", "roe": "%", "yield": "%", "streak": "년", "cancel": "%", "treasury": "%",
         "freq": "회"}
_SUB_NOTE = "이름으로 맞춘 거라 틀릴 수 있어요"


def _n(v) -> bool:
    return is_num(v)


def eligible(r) -> bool:
    """점수 대상: 빠른 탈락이 아니고 최근 사업연도 보통주 DPS가 0보다 커요."""
    a = r.assembled
    if a.quick_fail or not a.inputs.years:
        return False
    dps = a.inputs.years[-1].dps
    return _n(dps) and dps > 0


def dividend_streak(prior_dps, years_dps) -> int | None:
    """최근 해부터 거꾸로: 늘면 +1, 같으면(동결) 계속, 줄거나 값이 없으면 멈춰요. 최근 해가 없으면 None."""
    seq = list(prior_dps) + list(years_dps)
    if not seq or not _n(seq[-1]):
        return None
    n = 0
    for i in range(len(seq) - 1, 0, -1):
        cur, before = seq[i], seq[i - 1]
        if not _n(before) or cur < before:
            break
        if cur > before:
            n += 1
    return n


def step_points(value: float, rule: ItemRule, op: str) -> float:
    test = {"lt": lambda v, b: v < b, "le": lambda v, b: v <= b, "ge": lambda v, b: v >= b,
            "gt": lambda v, b: v > b, "freq": lambda v, b: v >= b}[op]
    for bound, pts in rule.steps:
        if test(value, bound):
            return float(pts)
    return 0.0


def grade(total: float, cfg: ScoreSettings) -> str:
    return "A" if total > cfg.grade_a else "B" if total > cfg.grade_b else "C" if total > cfg.grade_c else "D"


def rank(scores: dict[str, dict], ratios: dict[str, float | None]) -> list[str]:
    """점수 높은 순 → 주가÷적정가 낮은 순(없으면 뒤) → 종목코드."""
    def key(code: str):
        r = ratios.get(code)
        return (-scores[code]["total"], r is None, r if r is not None else 0.0, code)
    return sorted(scores, key=key)


def _g(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _rule_text(key: str, rule: ItemRule) -> str:
    op = ITEM_OPS[key]
    if op == "flag":
        return f"예 {_g(rule.points)} · 아니오 0"
    parts = []
    if key == "treasury" and rule.none_points is not None:
        parts.append(f"없음 {_g(rule.none_points)}")
    unit = _UNIT.get(key, "")
    parts += [f"{_g(b)}{unit} {_OP_WORD[op]} {_g(p)}" for b, p in rule.steps]
    return " · ".join(parts)


def _values(r, facts: ScoreFacts | None, cfg: ScoreSettings) -> dict[str, tuple]:
    """항목 키 → (점수를 매길 값 또는 None, 보여줄 글, 출처, 특수 점수 또는 None)."""
    a, c = r.assembled, r.cells
    i = a.inputs
    latest = i.years[-1] if i.years else None
    eps = latest.eps if latest else None
    yr = latest.year if latest else a.latest_year
    out: dict[str, tuple] = {}

    if _n(i.price) and _n(eps):
        out["per"] = (None, "적자", f"현재가 ÷ {yr}년 EPS", 0.0) if eps <= 0 else \
            (i.price / eps, f"{_g(round(i.price / eps, 1))}배", f"현재가 ÷ {yr}년 EPS", None)
    if _n(i.pbr):
        out["pbr"] = (i.pbr, f"{_g(round(i.pbr, 2))}배", "카드의 PBR", None)
    if _n(c.get("B108")):
        out["ratio"] = (c["B108"], f"{c['B108']:.2f}", "계산기 B108", None)
    if _n(c.get("B78")):
        out["roe"] = (c["B78"], f"{_g(round(c['B78'], 1))}%", "계산기 B78", None)
    eps5 = [y.eps for y in i.years]
    if eps5 and all(_n(e) for e in eps5):
        ok = all(e > 0 for e in eps5)
        out["no_loss"] = (None, "적자 없음" if ok else "적자 있음", "카드 5년 EPS",
                          cfg.items["no_loss"].points if ok else 0.0)
    if facts is not None:
        if facts.ttm_is_annual:
            out["ttm"] = (None, "최근 연간이 가장 최신", facts.sources.get("ttm", ""), cfg.items["ttm"].points)
        elif _n(facts.ttm_eps) and _n(eps):
            if eps <= 0:
                out["ttm"] = (None, f"최근 4분기 EPS {facts.ttm_eps:,.0f}원 (최근 연간 적자)",
                              facts.sources.get("ttm", ""), 0.0)
            else:
                ratio = facts.ttm_eps / eps
                out["ttm"] = (ratio, f"{facts.ttm_eps:,.0f}원 ÷ {eps:,.0f}원 = {ratio:.2f} ({facts.ttm_label})",
                              facts.sources.get("ttm", ""), None)
    if _n(c.get("B115")):
        out["yield"] = (c["B115"] * 100, f"{c['B115'] * 100:.1f}%", "계산기 B115", None)
    streak = dividend_streak(i.prior_dps, [y.dps for y in i.years])
    if streak is not None:
        out["streak"] = (streak, f"{streak}년", "카드 10년 DPS", None)
    if facts is not None:
        if facts.payout_per_year is not None:
            out["freq"] = (facts.payout_per_year, _FREQ.get(facts.payout_per_year, f"{facts.payout_per_year}회"),
                           facts.sources.get("freq", ""), None)
        if all(y is not None for y in facts.buyback_years):
            ok = all(facts.buyback_years)
            marks = " · ".join("있음" if y else "없음" for y in facts.buyback_years)
            out["buyback"] = (None, f"최근부터 {marks}", facts.sources.get("buyback", ""),
                              cfg.items["buyback"].points if ok else 0.0)
        if _n(facts.cancelled) and _n(facts.issued):
            pct = facts.cancelled / (facts.issued + facts.cancelled) * 100
            out["cancel"] = (pct, f"{pct:.2f}%", facts.sources.get("cancel", ""), None)
        if _n(facts.treasury) and _n(facts.issued):
            if facts.treasury == 0:
                rule = cfg.items["treasury"]
                out["treasury"] = (None, "없음", facts.sources.get("treasury", ""),
                                   rule.none_points if rule.none_points is not None else rule.points)
            else:
                pct = facts.treasury / facts.issued * 100
                out["treasury"] = (pct, f"{pct:.2f}%", facts.sources.get("treasury", ""), None)
        if facts.subsidiaries is not None:
            if facts.subsidiaries:
                names = ", ".join(f"{n} {_g(s)}%" for n, s in facts.subsidiaries)
                out["subsidiary"] = (None, f"있음: {names} ({_SUB_NOTE})", facts.sources.get("subsidiary", ""), 0.0)
            else:
                out["subsidiary"] = (None, "없음", facts.sources.get("subsidiary", ""),
                                     cfg.items["subsidiary"].points)
    return out


def score_stock(r, facts: ScoreFacts | None, cfg: ScoreSettings) -> dict | None:
    """점수 대상이 아니면 None. 자료 없는 항목은 status "no_data", 0점으로 더하고 그 배점을 missing에 모아요."""
    if not eligible(r):
        return None
    vals = _values(r, facts, cfg)
    items, groups, missing = [], {}, 0.0
    for gkey, _label, keys in GROUPS:
        groups[gkey] = 0.0
        for key in keys:
            rule = cfg.items[key]
            got = vals.get(key)
            if got is None:
                pts, status, shown, source = 0.0, "no_data", "자료 없음", ""
                missing += rule.points
            else:
                value, shown, source, fixed = got
                pts = float(fixed) if fixed is not None else step_points(value, rule, ITEM_OPS[key])
                status = "ok"
            groups[gkey] += pts
            items.append({"key": key, "label": LABELS[key], "group": gkey, "value": shown,
                          "rule": _rule_text(key, rule), "points": pts, "max": float(rule.points),
                          "status": status, "source": source})
    total = sum(groups.values())
    return {"total": total, "max": float(sum(rule.points for rule in cfg.items.values())),
            "grade": grade(total, cfg), "missing": missing, "groups": groups, "items": items}
