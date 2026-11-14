"""DART 사업보고서·배당 자료와 KRX 주가로 계산기 입력(StockInputs)을 만들어요.

칸마다 출처 글(sources)을 남기고, 의심스러운 숫자는 '숫자 확인 필요' 사유(flags)로,
참고할 점은 메모(notes)로 남겨요. 못 가져온 숫자는 None이에요. 0은 '실제로 0'일 때만 써요.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from vsf.data.accounts import PERIODS, Sourced, extract, parse_amount
from vsf.data.dart import FinRows
from vsf.data.splits import SPLIT_FLAG, check_splits, close_factor
from vsf.data.store import PriceRow
from vsf.excelfn import excel_round
from vsf.model import StockInputs, YearRow

QUICK_FAIL_NOTE = "최근 3년 중 배당을 안 준 해가 있어 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요."
OFS_NOTE = "별도 재무제표 기준이에요"
PBR_NOTE = "PBR은 추정값이에요"
ROE_END_NOTE = "{y}년 ROE는 기말 자본 기준이에요"
INTEREST_PAID_NOTE = "{y}년 이자보상배율은 '이자의 지급'으로 계산했어요"
SPECIAL_DIVIDEND_NOTE = "{y}년 배당성향이 100%를 넘어요(특별배당 의심)"
DPS_FLAG = "{y}년 DPS가 보고서마다 달라요. 확인해 주세요."
CURRENCY_FLAG = "원화가 아닌 재무제표예요(통화: {currency}). 숫자를 확인해 주세요."
EQUITY_FLAG = "{y}년 자본이 0 이하예요. ROE·부채비율을 확인해 주세요."

NO_INTEREST_COVERAGE = 999.0   # 엑셀 규칙: 이자비용이 0이면 999
DPS_TOLERANCE = 0.02           # 보고서끼리 같은 해 DPS가 이보다 많이 다르면 확인 표시

_COLS = "BCDEF"
_FS_NAME = {"CFS": "연결", "OFS": "별도"}
_DPS_COLUMNS = ("thstrm", "frmtrm", "lwfr")
_AMOUNT_ROWS = (("net_income", 33), ("ocf", 34), ("capex", 35), ("dividends_paid", 36))


@dataclass(frozen=True)
class CompanyInfo:
    corp_code: str
    code: str
    name: str
    market: str
    induty_code: str
    acc_mt: str


@dataclass(frozen=True)
class Assembled:
    inputs: StockInputs
    flags: tuple[str, ...]        # '숫자 확인 필요' 사유
    notes: tuple[str, ...]        # 참고 메모
    sources: dict[str, str]       # 입력 칸 주소 → 출처 글
    quick_fail: bool
    latest_year: int


# ---- 배당 보고서 ----

def _dps_row(rows: list[dict]) -> dict | None:
    """보통주 '주당 현금배당금' 줄. 없으면 그 줄이 하나뿐이고 우선주가 아닐 때만 그 줄."""
    per_share = [r for r in rows if "주당현금배당금" in (r.get("se") or "").replace(" ", "")]
    common = [r for r in per_share if (r.get("stock_knd") or "").strip() == "보통주"]
    if common:
        return common[0]
    if len(per_share) == 1 and "우선" not in (per_share[0].get("stock_knd") or ""):
        return per_share[0]
    return None


def dps_from_report(rows: list[dict], year: int) -> dict[int, float | None]:
    """배당 보고서 하나 → {year: 당기, year−1: 전기, year−2: 전전기}. "-"는 0.0, 값이 없으면 None."""
    row = _dps_row(rows or []) or {}
    out: dict[int, float | None] = {}
    for back, column in enumerate(_DPS_COLUMNS):
        text = row.get(column) or ""
        out[year - back] = 0.0 if text.strip() == "-" else parse_amount(text)
    return out


def _merge_dps(div_reports: dict[int, list[dict]]
               ) -> tuple[dict[int, float | None], dict[int, int], list[str]]:
    """해마다 DPS, 그 값을 준 보고서 연도, 플래그. 겹치는 해는 더 최근 보고서 값이 먼저예요."""
    values: dict[int, float | None] = {}
    origin: dict[int, int] = {}
    flags: list[str] = []
    for report_year in sorted(div_reports, reverse=True):
        for y, v in dps_from_report(div_reports[report_year], report_year).items():
            kept = values.get(y)
            if kept is None:            # 처음 보는 해이거나, 더 최근 보고서에 값이 없던 해
                values[y] = v
                if v is not None:
                    origin[y] = report_year
            elif v is not None and abs(v - kept) > DPS_TOLERANCE * abs(kept):
                flag = DPS_FLAG.format(y=y)
                if flag not in flags:
                    flags.append(flag)
    return values, origin, flags


def dps_by_year(div_reports: dict[int, list[dict]]) -> tuple[dict[int, float | None], tuple[str, ...]]:
    values, _, flags = _merge_dps(div_reports)
    return values, tuple(flags)


def quick_fail_check(latest_div_rows: list[dict] | None, latest_year: int) -> bool:
    """최근 3년 중 보통주 DPS가 0인 해가 있으면 True. 값이 없는 해(None)는 0으로 보지 않아요."""
    if not latest_div_rows:
        return False
    return any(v == 0 for v in dps_from_report(latest_div_rows, latest_year).values())


# ---- 재무제표 기간과 출처 글 ----

@dataclass(frozen=True)
class _Period:
    """보고서 하나에 적힌 한 해의 계정들."""

    report_year: int
    fs: str
    acc: dict[str, Sourced]


class _Out:
    """확인 표시·메모·출처를 모아요. 같은 글은 한 번만 넣어요."""

    def __init__(self) -> None:
        self.flags: list[str] = []
        self.notes: list[str] = []
        self.sources: dict[str, str] = {}

    def flag(self, *texts: str) -> None:
        for text in texts:
            if text not in self.flags:
                self.flags.append(text)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


def _periods(fin: FinRows | None, report_year: int) -> dict[int, _Period]:
    """보고서 → {해: 그해 계정}. 당기·전기·전전기가 report_year, −1, −2예요."""
    if fin is None:
        return {}
    return {report_year - back: _Period(report_year, fin.fs, extract(fin, period))
            for back, period in enumerate(PERIODS)}


def _net_income(p: _Period) -> Sourced:
    """지배주주 순이익. 별도 재무제표라 그 줄이 없으면 당기순이익."""
    s = p.acc["net_income_parent"]
    return p.acc["profit_loss"] if s.value is None and p.fs == "OFS" else s


def _equity(p: _Period) -> Sourced:
    """ROE·PBR의 자본: 지배주주 자본 (별도 재무제표면 자본총계)."""
    return p.acc["equity_total" if p.fs == "OFS" else "equity_parent"]


def _label(*periods: _Period) -> str:
    """"2025 사업보고서(연결)". 두 보고서를 함께 쓰면 "2025·2023 사업보고서(연결)"."""
    ordered = sorted(periods, key=lambda p: -p.report_year)
    years = dict.fromkeys(str(p.report_year) for p in ordered)
    kinds = dict.fromkeys(_FS_NAME.get(p.fs, p.fs) for p in ordered)
    return f"{'·'.join(years)} 사업보고서({'·'.join(kinds)})"


def _account(s: Sourced) -> str:
    return s.account if s.how == "id" else f"{s.account}(이름으로 찾음)"


def _cell(y: int, latest: int, row: int) -> str:
    """1번 표(26–36행)에서 y년 칸 주소. B열이 latest−4년이에요."""
    return f"{_COLS[y - latest + 4]}{row}"


# ---- 칸 묶음별 계산 ----

def _currency(fins: list[FinRows], out: _Out) -> None:
    for fin in fins:
        for row in fin.rows:
            currency = (row.get("currency") or "").strip()
            if currency and currency != "KRW":
                out.flag(CURRENCY_FLAG.format(currency=currency))


def _split_divisor(a: dict[int, _Period], b: dict[int, _Period], year_end: dict[int, PriceRow],
                   price: PriceRow, latest: int, out: _Out) -> float:
    """B 보고서 EPS를 나눌 배수. 주식 수가 크게 바뀐 해가 있으면 확인 표시를 달아요."""
    newer = a[latest - 2].acc["eps"].value if latest - 2 in a else None
    older = b[latest - 2].acc["eps"].value if latest - 2 in b else None
    shares = {y: year_end[y].shares for y in range(latest - 9, latest + 1) if y in year_end}
    check = check_splits(newer, older, shares, latest)
    out.flag(*check.flags)
    end = year_end.get(latest)
    if end is not None and close_factor(end.shares, price.shares) != 1.0:
        out.flag(SPLIT_FLAG)   # L년 말 뒤에 주식 수가 크게 바뀌어 현재가와 EPS의 기준이 달라요
    return check.eps_divisor_older


def _eps(main: dict[int, _Period], divisor: float, latest: int, out: _Out) -> dict[int, float | None]:
    """L…L−2는 A 보고서 그대로, L−3·L−4는 B 보고서 값을 divisor로 나눠요."""
    eps: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p = main.get(y)
        s = p.acc["eps"] if p is not None else None
        eps[y] = None
        if s is None or s.value is None:
            continue
        source = f"{_label(p)} · {_account(s)}"
        eps[y] = s.value
        if p.report_year != latest and divisor != 1.0:
            eps[y] = s.value / divisor
            source += f" ÷ {divisor:g}(액면분할 조정)"
        out.sources[_cell(y, latest, 27)] = source
    return eps


def _dps(div_reports: dict[int, list[dict]], latest: int, years: range, out: _Out) -> dict[int, float | None]:
    """years의 DPS. 출처는 29행(최근 5년)과 42행(그 이전 5년)에 남겨요."""
    values, origin, flags = _merge_dps(div_reports)
    out.flag(*flags)
    for y in years:
        if values.get(y) is not None:
            addr = _cell(y, latest, 29) if y > latest - 5 else f"{_COLS[y - latest + 9]}42"
            out.sources[addr] = f"{origin[y]} 사업보고서 배당에 관한 사항(보통주)"
    return {y: values.get(y) for y in years}


def _per(eps: dict[int, float | None], year_end: dict[int, PriceRow], latest: int,
         out: _Out) -> dict[int, float | None]:
    """연말 종가(L년 말 주식 수 기준으로 맞춤) ÷ EPS. EPS > 0이고 종가가 있을 때만."""
    now = year_end.get(latest)
    per: dict[int, float | None] = {}
    for y, e in eps.items():
        row = year_end.get(y)
        per[y] = None
        if row is None or row.close is None or e is None or e <= 0:
            continue
        factor = close_factor(row.shares, now.shares) if now is not None else 1.0
        per[y] = excel_round(row.close * factor / e, 2)
        adjusted = "" if factor == 1.0 else f" × {factor:.4g}(주식 수 변화 반영)"
        out.sources[_cell(y, latest, 28)] = f"{row.date} 종가{adjusted} ÷ EPS"
    return per


def _roe(a: dict[int, _Period], b: dict[int, _Period], main: dict[int, _Period], latest: int,
         out: _Out) -> dict[int, float | None]:
    """순이익 ÷ 그해·전해 말 자본의 평균 × 100. 연말 자본은 A 보고서에 없으면 B에서 찾아요."""
    def year_end_equity(y: int) -> _Period | None:
        return next((p for p in (a.get(y), b.get(y)) if p is not None and _equity(p).value is not None), None)

    roe: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p, cur, prev = main.get(y), year_end_equity(y), year_end_equity(y - 1)
        income = _net_income(p).value if p is not None else None
        roe[y] = None
        if income is None or cur is None:
            continue
        equity = _equity(cur).value if prev is None else (_equity(cur).value + _equity(prev).value) / 2
        if equity <= 0:
            out.flag(EQUITY_FLAG.format(y=y))
            continue
        roe[y] = excel_round(income / equity * 100, 2)
        if prev is None:
            out.note(ROE_END_NOTE.format(y=y))
        how = f"{y}년 말 자본" if prev is None else f"{y - 1}·{y}년 말 평균 자본"
        used = [p, cur] if prev is None else [p, cur, prev]
        out.sources[_cell(y, latest, 30)] = f"{_label(*used)} · 순이익 ÷ {how}"
    return roe


def _debt_ratio(main: dict[int, _Period], latest: int, out: _Out) -> dict[int, float | None]:
    """부채총계 ÷ 자본총계 × 100."""
    debt: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p = main.get(y)
        liabilities = p.acc["liabilities"].value if p is not None else None
        equity = p.acc["equity_total"].value if p is not None else None
        debt[y] = None
        if liabilities is None or equity is None:
            continue
        if equity <= 0:
            out.flag(EQUITY_FLAG.format(y=y))
            continue
        debt[y] = excel_round(liabilities / equity * 100, 2)
        out.sources[_cell(y, latest, 31)] = f"{_label(p)} · 부채총계 ÷ 자본총계"
    return debt


def _coverage(main: dict[int, _Period], latest: int, out: _Out) -> dict[int, float | None]:
    """영업이익 ÷ 이자비용. 이자비용이 없으면 '이자의 지급'(절댓값)으로, 분모가 0이면 999."""
    cov: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p = main.get(y)
        cov[y] = None
        if p is None:
            continue
        income, expense = p.acc["operating_income"].value, p.acc["interest_expense"].value
        denom, name = (expense, "이자비용") if expense is not None else (p.acc["interest_paid"].value, "이자의 지급")
        if income is None or denom is None:
            continue
        denom = abs(denom)
        cov[y] = NO_INTEREST_COVERAGE if denom == 0 else excel_round(income / denom, 2)
        if expense is None:
            out.note(INTEREST_PAID_NOTE.format(y=y))
        zero = "(0이라 999)" if denom == 0 else ""
        out.sources[_cell(y, latest, 32)] = f"{_label(p)} · 영업이익 ÷ {name}{zero}"
    return cov


def _amounts(main: dict[int, _Period], latest: int, out: _Out) -> dict[str, dict[int, float | None]]:
    """순이익·영업현금흐름·설비투자·배당금 지급 총액을 억 원으로."""
    got: dict[str, dict[int, float | None]] = {field: {} for field, _ in _AMOUNT_ROWS}
    for y in range(latest - 4, latest + 1):
        p = main.get(y)
        for field, row in _AMOUNT_ROWS:
            s = None if p is None else (_net_income(p) if field == "net_income" else p.acc[field])
            value = None if s is None or s.value is None else excel_round(s.value / 1e8, 2)
            got[field][y] = value
            if value is not None:
                out.sources[_cell(y, latest, row)] = f"{_label(p)} · {_account(s)}"
    return got


def _pbr(a: dict[int, _Period], eps: dict[int, float | None], latest: int, price: PriceRow,
         price_date: date, out: _Out) -> float | None:
    """현재가 ÷ 추정 BPS. BPS = 자본 ÷ (순이익 ÷ EPS). 넷 다 양수일 때만."""
    p = a.get(latest)
    if p is None:
        return None
    close, income, equity, e = price.close, _net_income(p).value, _equity(p).value, eps.get(latest)
    if any(v is None or v <= 0 for v in (close, income, equity, e)):
        return None
    out.note(PBR_NOTE)
    out.sources["B22"] = f"{price_date} 종가 ÷ 추정 BPS({_label(p)} · 자본 ÷ (순이익 ÷ EPS))"
    return excel_round(close / (equity / (income / e)), 2)


def _special_dividends(eps: dict[int, float | None], dps: dict[int, float | None], out: _Out) -> None:
    for y, e in eps.items():
        d = dps.get(y)
        if d is not None and e is not None and e > 0 and d / e > 1:
            out.note(SPECIAL_DIVIDEND_NOTE.format(y=y))


def _basic_sources(company: CompanyInfo, price: PriceRow, price_date: date, latest: int, out: _Out) -> None:
    """이름·코드·주가·날짜·연도 칸의 출처."""
    listed = f"KRX 종목 목록 · DART 고유번호 {company.corp_code}"
    if company.name:
        out.sources["B18"] = listed
    if company.code:
        out.sources["B19"] = listed
    if price.close is not None:
        out.sources["B20"] = f"KRX {price_date} 종가"
    out.sources["B21"] = f"KRX {price_date} 종가"
    for col in _COLS:
        out.sources[f"{col}26"] = out.sources[f"{col}41"] = f"최근 사업연도 {latest} 기준"


def _memo(latest: int, report_years: list[int], div_reports: dict[int, list[dict]], price_date: date,
          flags: list[str]) -> str:
    reports = "·".join(map(str, report_years)) or "자료 없음"
    dividends = "·".join(map(str, sorted(div_reports))) or "자료 없음"
    head = f"자동 수집 {price_date}: DART 사업보고서 {reports}, 배당 {dividends}, 주가 KRX {price_date} 종가."
    return head + "".join(f" {flag}" for flag in flags)


# ---- 조립 ----

def assemble(company: CompanyInfo, latest_year: int, fin_a: FinRows | None, fin_b: FinRows | None,
             div_reports: dict[int, list[dict]], year_end: dict[int, PriceRow], price: PriceRow,
             price_date: date) -> Assembled:
    """L년(fin_a)·L−2년(fin_b) 사업보고서, 배당 보고서들, KRX 주가로 계산기 입력을 만들어요.

    fin_a가 없으면 재무 숫자는 모두 비워요 (B만으로는 최근 기준과 맞춰 볼 수 없어요). 실패로 볼지는 부르는 쪽이 정해요.
    """
    L = latest_year
    out = _Out()
    a = _periods(fin_a, L)
    b = _periods(fin_b, L - 2) if a else {}
    main = {**b, **a}                                  # 해 → 쓰는 기간. 겹치는 L−2는 A예요.
    if any(p.fs == "OFS" for p in main.values()):
        out.note(OFS_NOTE)
    _currency([fin for fin, used in ((fin_a, a), (fin_b, b)) if used], out)
    eps = _eps(main, _split_divisor(a, b, year_end, price, L, out), L, out)
    dps = _dps(div_reports, L, range(L - 9, L + 1), out)
    per = _per(eps, year_end, L, out)
    roe = _roe(a, b, main, L, out)
    debt = _debt_ratio(main, L, out)
    cov = _coverage(main, L, out)
    amounts = _amounts(main, L, out)
    pbr = _pbr(a, eps, L, price, price_date, out)
    _special_dividends(eps, dps, out)
    years = tuple(YearRow(year=y, eps=eps[y], per=per[y], dps=dps[y], roe=roe[y], debt_ratio=debt[y],
                          interest_coverage=cov[y], **{field: amounts[field][y] for field, _ in _AMOUNT_ROWS})
                  for y in range(L - 4, L + 1))
    _basic_sources(company, price, price_date, L, out)
    out.sources["B23"] = "프로그램이 쓴 자동 수집 메모"
    prior = range(L - 9, L - 4)
    memo = _memo(L, [y for y, used in ((L, a), (L - 2, b)) if used], div_reports, price_date, out.flags)
    inputs = StockInputs(name=company.name, code=company.code, price=price.close, price_date=price_date,
                         pbr=pbr, memo=memo, years=years, prior_years=tuple(prior),
                         prior_dps=tuple(dps[y] for y in prior))
    return Assembled(inputs, tuple(out.flags), tuple(out.notes), out.sources, False, L)


def assemble_quick_fail(company: CompanyInfo, latest_year: int, div_reports: dict[int, list[dict]],
                        price: PriceRow, price_date: date) -> Assembled:
    """관문 ② 탈락이 확실한 종목: 이름·코드·주가·날짜·연도와 D–F열 DPS만 채워요."""
    L = latest_year
    out = _Out()
    dps = _dps(div_reports, L, range(L - 2, L + 1), out)
    years = tuple(YearRow(year=y, dps=dps.get(y)) for y in range(L - 4, L + 1))
    _basic_sources(company, price, price_date, L, out)
    out.note(QUICK_FAIL_NOTE)
    inputs = StockInputs(name=company.name, code=company.code, price=price.close, price_date=price_date,
                         years=years, prior_years=tuple(range(L - 9, L - 4)))
    return Assembled(inputs, tuple(out.flags), tuple(out.notes), out.sources, True, L)
