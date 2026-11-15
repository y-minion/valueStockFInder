"""엑셀 '분석_빈칸' 시트 수식을 옮긴 계산 엔진. 블록(행 묶음)마다 함수 하나예요."""
from dataclasses import dataclass
from datetime import date
from typing import Literal

from vsf.config import ReportSettings
from vsf.excelfn import average, count, excel_round, excel_text, is_num
from vsf.financial import CAPITAL_HELP, CAPITAL_LABELS, FIN_CELLS, FinancialGate
from vsf.model import FORMULA_CELLS, Cell, Criteria, Num, SheetValues, StockInputs, to_cells

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


def _gate3(v: Cells, c: Criteria) -> None:
    """102–109행·D110: 관문 ③ 가격."""
    b96, b97, b98, b100 = v["B96"], v["B97"], v["B98"], v["B100"]
    price = v.get("B20")
    v["B102"] = b96 / c.required_return if is_num(b96) else None
    v["B103"] = b96 * b97 if _num(b96, b97) else None
    v["B104"] = b100 / b98 if _num(b100, b98) and b98 > 0 else None
    if not is_num(b96):
        v["B105"] = None
    elif b96 <= 0:
        v["B105"] = "계산 불가"
    else:
        nums = [x for x in (v["B102"], v["B103"], v["B104"]) if is_num(x)]
        v["B105"] = min(nums) if nums else None
    b105 = v["B105"]
    if is_num(b105):
        v["B106"] = ("A 이론" if b105 == v["B102"]
                     else "B 과거 PER" if b105 == v["B103"] else "C 과거 배당수익률")
    else:
        v["B106"] = None
    v["B107"] = b105 * (1 - c.safety_margin) if is_num(b105) else None
    b107 = v["B107"]
    v["B108"] = price / b105 if _num(b105, price) else None
    v["C108"] = f"≤ {excel_text(1 - c.safety_margin, '0.00')}배"
    v["B109"] = (max(0.0, 1 - b107 / price)
                 if _num(b107, price) and price > 0 else None)
    v["D110"] = ("탈락" if b105 == "계산 불가"
                 else "입력 필요" if not _num(b105, price)
                 else "통과" if price <= b107 else "탈락")


def _reference(v: Cells, c: Criteria) -> None:
    """112–118행: 참고 지표."""
    price, b96 = v.get("B20"), v["B96"]
    v["B112"] = price * c.required_return if is_num(price) else None
    b112 = v["B112"]
    v["B113"] = b112 / b96 if _num(b112, b96) and b96 > 0 else None
    f27, f29 = v.get("F27"), v.get("F29")
    v["B114"] = price / f27 if _num(price, f27) and f27 > 0 else None
    v["B115"] = f29 / price if _num(price, f29) and price > 0 else None
    pbr = v.get("B22")
    v["B116"] = pbr * c.required_return if is_num(pbr) else None
    b78 = v["B78"]
    v["B117"] = b78 / 100 if is_num(b78) else None
    b105 = v["B105"]
    v["B118"] = b105 / b96 if _num(b105, b96) and b96 > 0 else None


def _scenarios(v: Cells, c: Criteria) -> None:
    """120–126행: 5-3 EPS 시나리오."""
    eps = [x for x in _rng(v, 27) if is_num(x)]
    b96, b118, price = v["B96"], v["B118"], v.get("B20")
    v["B120"] = min(eps) if eps else None
    v["B121"] = b96 * 0.8 if is_num(b96) else None
    v["B122"] = b96
    f27 = v.get("F27")
    v["B123"] = f27 if is_num(f27) else None
    v["B124"] = max(eps) if eps else None
    # B125는 입력 칸(내 EPS)이에요.
    v["B126"] = (price / (b118 * (1 - c.safety_margin))
                 if _num(price, b118) and b118 > 0 else None)
    for row in range(120, 127):
        b = v.get(f"B{row}")
        cc = b * b118 if _num(b, b118) else None
        d = cc * (1 - c.safety_margin) if is_num(cc) else None
        e = price / cc if _num(cc, price) and cc > 0 else None
        v[f"C{row}"], v[f"D{row}"], v[f"E{row}"] = cc, d, e
        v[f"F{row}"] = (None if not is_num(e)
                        else "싸요" if e <= 1 - c.safety_margin + 0.0000001
                        else "제값" if e <= 1 else "비싸요")


def _num_text(x) -> str:
    """엑셀이 숫자를 글자에 이어 붙일 때의 모양 (정수면 소수점 없이)."""
    return str(int(x)) if float(x).is_integer() else str(x)


def _gate4(v: Cells) -> None:
    """131·132행 참고 글과 D135: 관문 ④."""
    f31, f32 = v.get("F31"), v.get("F32")
    v["C131"] = (f"참고: 최근 부채비율 {excel_text(f31, '0')}%, "
                 f"이자보상배율 {excel_text(f32, '#,##0.0')}배" if _num(f31, f32)
                 else "참고: 1번에 부채비율과 이자보상배율을 넣으면 여기에 보여요")
    b99, b89, b87 = v["B99"], v["B89"], v["B87"]
    v["C132"] = (
        f"참고: 배당성향 평균 {excel_text(b99, '0%') if is_num(b99) else '?'}, "
        f"잉여현금흐름÷배당 {excel_text(b89, '0.0') + '배' if is_num(b89) else '?'}, "
        f"배당을 줄인 해 {_num_text(b87) + '번' if is_num(b87) else '?'}")
    blank = lambda x: x is None or x == ""  # noqa: E731
    if blank(v.get("B129")) or any(blank(v.get(f"B{r}")) for r in range(130, 134)):
        v["D135"] = "입력 필요"
    else:
        ok = (v["B130"] == "예" and v["B131"] == "예" and v["B132"] == "예"
              and v["B133"] == "일시적")
        v["D135"] = "통과" if ok else "탈락"


def _glance(v: Cells, c: Criteria) -> None:
    """6–15행: 한눈에 보기."""
    name, code = v.get("B18"), v.get("B19")
    v["B6"] = ("(0번에 종목명을 입력하세요)" if name in (None, "")
               else f"{name} ({code})" if code not in (None, "") else name)
    d82, d90, d110, d135 = v["D82"], v["D90"], v["D110"], v["D135"]
    v["B7"], v["B8"], v["B9"], v["B10"] = d82, d90, d110, d135
    price, pdate = v.get("B20"), v.get("B21")
    v["B11"] = price if is_num(price) else None
    if isinstance(pdate, date):
        v["C11"] = f"기준일 {excel_text(pdate, 'yyyy-mm-dd')}"
    else:
        v["C11"] = f"기준일 {pdate}" if pdate not in (None, "") else None
    b105, b106, b107, b108, b109 = v["B105"], v["B106"], v["B107"], v["B108"], v["B109"]
    v["B12"] = b105
    v["C12"] = f"정한 방법: {b106}" if b106 not in (None, "") else None
    v["B13"] = b107
    v["C13"] = (f"지금보다 {excel_text(b109, '0%')} 내려야 닿아요"
                if is_num(b109) else None)
    v["B14"] = b108
    v["C14"] = f"통과 기준: {excel_text(1 - c.safety_margin, '0.00')}배 이하"
    buy = excel_text(b107, "#,##0") if is_num(b107) else ""
    drop = excel_text(b109, "0%") if is_num(b109) else ""
    if d82 == "탈락":
        s = "관문 ①에서 탈락했어요. 좋은 회사 기준을 넘지 못했으니 더 볼 필요가 없어요."
    elif d90 == "탈락":
        s = "관문 ②에서 탈락했어요. 배당이 오래 갈지 믿기 어려워서 배당주 칸에는 맞지 않아요."
    elif d110 == "입력 필요":
        s = "관문 ③을 계산하려면 0번의 현재 주가와 1번의 EPS·PER·배당을 넣어야 해요."
    elif d110 == "탈락":
        s = (f"아직 비싸요. 매수선 {buy}원(지금보다 {drop} 낮은 가격)에 가격 알림을 걸어두고, "
             "그동안 들어오는 돈은 배당 ETF에 넣어요.")
    elif d82 == "확인 필요" or d90 == "확인 필요":
        s = ("관문 ③은 통과했어요. ①②에서 '입력 필요'나 '직접 확인'으로 나온 항목을 먼저 확인하고, "
             "그다음 6번에서 ④를 판단해요.")
    elif d135 == "통과":
        s = ("네 관문을 모두 통과했어요. 7번 투자 메모를 쓰고, 개별 종목 비중(ISA의 "
             f"{excel_text(c.isa_weight_max, '0%')} 이내) 안에서 매수를 검토해요.")
    elif d135 == "탈락":
        s = "숫자는 모두 통과했지만, ④에서 '싼 이유가 일시적'이라고 판단하지 못했어요. 사지 않아요."
    else:
        s = "①②③을 통과했어요. 이제 6번에서 ④(싼 이유가 일시적인가)를 직접 판단해요."
    v["B15"] = s


def _combine(items: list) -> str:
    return ("탈락" if "탈락" in items
            else "확인 필요" if "입력 필요" in items or "직접 확인" in items else "통과")


def _financial_overlay(v: Cells, g: FinancialGate, extra_gate1: str | None) -> None:
    """금융회사: 맞지 않는 줄(79·80·81·89행)을 '해당 없음'으로 바꾸고 적자·자본비율 판정을 더해요."""
    for row in (79, 80, 81, 89):
        v[f"B{row}"] = None
        v[f"C{row}"] = v[f"D{row}"] = "해당 없음"
    ni = [x for x in _rng(v, 33) if is_num(x)]
    v["F_LOSS_B"] = float(sum(1 for x in ni if x <= 0)) if ni else None
    v["F_LOSS_C"] = "5년 모두 흑자"
    v["F_LOSS_D"] = ("탈락" if any(x <= 0 for x in ni)
                     else "입력 필요" if len(ni) < 5 else "통과")
    cap, cmin = g.capital, g.capital_min
    v["F_CAP_B"] = cap.value if cap is not None else None
    v["F_CAP_C"] = "기준 없음" if cmin is None else f"≥ {cmin:g}%"
    v["F_CAP_D"] = ("직접 확인" if cap is None or cmin is None
                    else "통과" if cap.value >= cmin else "탈락")
    v["F_CAP_SRC"] = f"{cap.source} ({cap.base_month} 기준)" if cap is not None else CAPITAL_HELP
    v["D82"] = _combine([v["D78"], v["F_LOSS_D"], v["F_CAP_D"]]
                        + ([extra_gate1] if extra_gate1 is not None else []))
    v["D90"] = _combine([v["D86"], v["D87"], v["D88"]])


def _financial_hints(v: Cells, g: FinancialGate) -> None:
    """금융회사: 관문 ④ 참고 글(131·132행)을 자본비율 기준으로 바꿔요."""
    cap = (f"{g.capital.value:g}%, {g.capital.base_month} 기준" if g.capital is not None
           else "직접 확인")
    v["C131"] = f"참고: 금융회사는 부채비율·이자보상배율 대신 자본비율을 봐요 ({CAPITAL_LABELS[g.kind]} {cap})"
    b99, b87 = v["B99"], v["B87"]
    v["C132"] = (
        f"참고: 배당성향 평균 {excel_text(b99, '0%') if is_num(b99) else '?'}, "
        f"배당을 줄인 해 {_num_text(b87) + '번' if is_num(b87) else '?'} "
        "(금융회사라 잉여현금흐름÷배당은 보지 않아요)")


def compute(inputs: StockInputs, criteria: Criteria, extra_gate1: str | None = None,
            *, financial: FinancialGate | None = None) -> SheetValues:
    """입력과 기준으로 수식 칸 152개를 모두 계산해요. financial이 있으면 금융회사 칸 7개(FIN_CELLS)가 더 붙어요."""
    v: Cells = {a: float(x) if is_num(x) else x for a, x in to_cells(inputs).items()}
    _averages(v)             # B94, B96 (53행이 B96을 써요)
    _yearly(v, criteria)     # 43–55행
    _averages_filtered(v)    # B97–B100 (53·54행을 써요)
    _gate1(v, criteria, extra_gate1)
    _gate2(v, criteria)
    if financial is not None:
        _financial_overlay(v, financial, extra_gate1)
    _gate3(v, criteria)
    _reference(v, criteria)
    _scenarios(v, criteria)
    _gate4(v)
    if financial is not None:
        _financial_hints(v, financial)
    _glance(v, criteria)
    cells = {a: v.get(a) for a in FORMULA_CELLS}
    if financial is not None:
        cells.update({a: v.get(a) for a in FIN_CELLS})
    return cells


@dataclass(frozen=True)
class Summary:
    gate1: str
    gate2: str
    gate3: str
    gate4: str
    price: Num
    fair_value: Cell
    method: str | None
    buy_line: Num
    ratio: Num
    drop: Num
    next_step: str
    roe_avg: Num
    payout_avg: Num
    yield_now: Num


def summarize(cells: SheetValues) -> Summary:
    g = cells.get
    return Summary(
        gate1=g("D82"), gate2=g("D90"), gate3=g("D110"), gate4=g("D135"),
        price=g("B11"), fair_value=g("B105"), method=g("B106"),
        buy_line=g("B107"), ratio=g("B108"), drop=g("B109"), next_step=g("B15"),
        roe_avg=g("B78"), payout_avg=g("B99"), yield_now=g("B115"))


def _not_failed(s: Summary) -> bool:
    return s.gate1 != "탈락" and s.gate2 != "탈락"


def watch_state(s: Summary, r: ReportSettings) -> Literal["buy", "watch", "out"]:
    if _not_failed(s) and s.gate3 == "통과":
        return "buy"
    if _not_failed(s) and is_num(s.drop) and s.drop <= r.watch_range:
        return "watch"
    return "out"


def is_near(s: Summary, r: ReportSettings) -> bool:
    return is_num(s.drop) and s.drop <= r.near_range
