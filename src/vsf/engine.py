"""엑셀 '분석_빈칸' 시트 수식을 옮긴 계산 엔진. 블록(행 묶음)마다 함수 하나예요."""
from vsf.excelfn import average, count, excel_round, excel_text, is_num
from vsf.model import Criteria, SheetValues, StockInputs, to_cells

COLS = "BCDEF"
Cells = dict  # 주소 → 값 (입력 칸 + 지금까지 계산한 칸). None은 빈칸이나 "".


def _rng(v: Cells, row: int, cols: str = COLS) -> list:
    return [v.get(f"{c}{row}") for c in cols]


def _num(*xs) -> bool:
    return all(is_num(x) for x in xs)


def _ratio(a, b):
    """IF(AND(ISNUMBER(a),ISNUMBER(b)),IF(b>0,a/b-1,""),"") 의 b>0 비교 뒤 부분."""
    return a / b - 1 if b > 0 else None


def _yearly(v: Cells, c: Criteria) -> None:
    """43–55행: 해마다 계산한 값. B96(평균 EPS)은 아래 평균 블록에서 먼저 구해요."""
    prev = dict(zip("CDEF", "BCDE"))
    for col in "CDEF":
        p = prev[col]
        a, b = v.get(f"{col}42"), v.get(f"{p}42")
        v[f"{col}43"] = _ratio(a, b) if _num(a, b) else None
    for col in COLS:
        v[f"{col}46"] = v.get(f"{col}26") or None
        eps, per = v.get(f"{col}27"), v.get(f"{col}28")
        dps = v.get(f"{col}29")
        v[f"{col}47"] = per * eps if _num(per, eps) and eps > 0 else None
        e47 = v[f"{col}47"]
        v[f"{col}48"] = dps / e47 if _num(dps, e47) and e47 > 0 else None
        v[f"{col}49"] = dps / eps if _num(dps, eps) and eps > 0 else None
    f42 = v.get("F42")
    for col in COLS:
        dps = v.get(f"{col}29")
        if col == "B":
            v["B50"] = _ratio(dps, f42) if _num(dps, f42) else None
        else:
            p = prev[col]
            pd = v.get(f"{p}29")
            v[f"{col}50"] = _ratio(dps, pd) if _num(dps, pd) else None
    for col in COLS:
        ocf, capex = v.get(f"{col}34"), v.get(f"{col}35")
        v[f"{col}51"] = ocf - capex if _num(ocf, capex) else None
        fcf_in, ni = v.get(f"{col}36"), v.get(f"{col}33")
        if is_num(fcf_in):
            v[f"{col}52"] = fcf_in
        else:
            r = v[f"{col}49"]
            v[f"{col}52"] = ni * r if _num(ni, r) else None
    b96 = v.get("B96")
    for col in COLS:
        eps = v.get(f"{col}27")
        if not is_num(eps):
            v[f"{col}53"] = None
        elif v.get(f"{col}37"):
            v[f"{col}53"] = "제외(직접)"
        elif eps <= 0 or eps < c.abnormal_ratio * b96:
            v[f"{col}53"] = "비정상"
        else:
            v[f"{col}53"] = "정상"
        s53 = v[f"{col}53"]
        if s53 is None:
            v[f"{col}54"] = None
        else:
            ok = s53 == "정상" and not v.get(f"{col}38") and is_num(v.get(f"{col}29"))
            v[f"{col}54"] = "넣음" if ok else "뺌"
        v[f"{col}55"] = b96 if _num(eps, b96) else None


def _averages(v: Cells) -> None:
    """94–100행: 평균값. 53·54행(해마다 값)에 기대는 것은 그 뒤에 구해요."""
    eps = _rng(v, 27)
    v["B94"] = average(eps) if count(eps) else None
    v["B96"] = v["B95"] if is_num(v.get("B95")) else v["B94"]


def _averages_filtered(v: Cells) -> None:
    def avg_if(avg_row: int, crit_row: int, want: str):
        vals = [a for a, k in zip(_rng(v, avg_row), _rng(v, crit_row)) if k == want]
        return average(vals)

    v["B97"] = avg_if(28, 53, "정상")
    v["B98"] = avg_if(48, 54, "넣음")
    v["B99"] = avg_if(49, 54, "넣음")
    b96, b99 = v["B96"], v["B99"]
    v["B100"] = b96 * b99 if _num(b96, b99) else None


def _gate1(v: Cells, c: Criteria, extra_gate1: str | None) -> None:
    """78–82행: 관문 ① 수익성·재무."""
    roe = _rng(v, 30)
    v["B78"] = average(roe) if count(roe) else None
    v["C78"] = f"≥ {excel_text(c.roe_min, '0')}%"
    v["D78"] = ("입력 필요" if v["B78"] is None
                else "통과" if v["B78"] >= c.roe_min else "탈락")

    f31 = v.get("F31")
    v["B79"] = f31 if is_num(f31) else None
    v["C79"] = f"< {excel_text(c.debt_ratio_max, '0')}%"
    v["D79"] = ("입력 필요" if v["B79"] is None
                else "통과" if v["B79"] < c.debt_ratio_max else "탈락")

    f32 = v.get("F32")
    v["B80"] = f32 if is_num(f32) else None
    v["C80"] = f"≥ {excel_text(c.interest_coverage_min, '0.0')}배"
    v["D80"] = ("입력 필요" if v["B80"] is None
                else "통과" if v["B80"] >= c.interest_coverage_min else "탈락")

    ni, ocf = _rng(v, 33), _rng(v, 34)
    if count(ni) == 0 or count(ni) != count(ocf):
        v["B81"] = None
    else:
        s_ni = sum(x for x in ni if is_num(x))
        v["B81"] = ("순이익 합계 0 이하" if s_ni <= 0
                    else sum(x for x in ocf if is_num(x)) / s_ni)
    v["C81"] = f"≥ {excel_text(c.ocf_to_ni_min, '0.0')}배"
    b81 = v["B81"]
    v["D81"] = ("입력 필요" if b81 is None
                else "통과" if is_num(b81) and b81 >= c.ocf_to_ni_min else "탈락")

    items = [v["D78"], v["D79"], v["D80"], v["D81"]]
    if extra_gate1 is not None:
        items.append(extra_gate1)
    v["D82"] = ("탈락" if "탈락" in items
                else "확인 필요" if "입력 필요" in items else "통과")


def _gate2(v: Cells, c: Criteria) -> None:
    """86–90행: 관문 ② 배당."""
    dps, prior = _rng(v, 29), _rng(v, 42)
    zeros = lambda xs: sum(1 for x in xs if is_num(x) and x == 0)  # noqa: E731
    negs = lambda xs: sum(1 for x in xs if is_num(x) and x < 0)  # noqa: E731
    has = count(dps) > 0
    v["B86"] = float(zeros(dps) + zeros(prior)) if has else None
    v["D86"] = ("입력 필요" if v["B86"] is None
                else "통과" if v["B86"] == 0 else "탈락")
    v["B87"] = (float(negs(_rng(v, 50)) + negs(_rng(v, 43, "CDEF")))
                if has else None)
    v["D87"] = ("입력 필요" if v["B87"] is None
                else "통과" if v["B87"] == 0 else "직접 확인")

    v["B88"] = v["B99"]
    v["C88"] = f"{excel_text(c.payout_min, '0%')} ~ {excel_text(c.payout_max, '0%')}"
    b88 = v["B88"]
    if not is_num(b88):
        v["D88"] = "입력 필요"
    else:
        r = excel_round(b88, 2)
        v["D88"] = "통과" if c.payout_min <= r <= c.payout_max else "탈락"

    ocf, capex, f52 = _rng(v, 34), _rng(v, 35), _rng(v, 52)
    if count(ocf) == 0 or count(capex) < count(ocf) or count(f52) == 0:
        v["B89"] = None
    else:
        s52 = sum(x for x in f52 if is_num(x))
        v["B89"] = (None if s52 <= 0
                    else sum(x for x in _rng(v, 51) if is_num(x)) / s52)
    v["C89"] = f"≥ {excel_text(c.fcf_to_div_min, '0.0')}배"
    v["D89"] = ("입력 필요" if v["B89"] is None
                else "통과" if v["B89"] >= c.fcf_to_div_min else "탈락")

    d = [v["D86"], v["D87"], v["D88"], v["D89"]]
    v["D90"] = ("탈락" if "탈락" in d
                else "확인 필요" if "입력 필요" in d or "직접 확인" in d else "통과")


def compute(inputs: StockInputs, criteria: Criteria,
            extra_gate1: str | None = None) -> SheetValues:
    """입력과 기준으로 수식 칸 값을 계산해요 (지금은 PART_A: 43–55, 78–90, 94–100행)."""
    v: Cells = {a: float(x) if is_num(x) else x for a, x in to_cells(inputs).items()}
    _averages(v)             # B94, B96 (53행이 B96을 써요)
    _yearly(v, criteria)     # 43–55행
    _averages_filtered(v)    # B97–B100 (53·54행을 써요)
    _gate1(v, criteria, extra_gate1)
    _gate2(v, criteria)
    return {k: x for k, x in v.items() if x is None or isinstance(x, (float, str))}
