"""DART 사업보고서·배당 자료와 KRX 주가로 계산기 입력(StockInputs)을 만들어요.

칸마다 출처 글(sources)을 남기고, 의심스러운 숫자는 '숫자 확인 필요' 사유(flags)로,
참고할 점은 메모(notes)로 남겨요. 못 가져온 숫자는 None이에요. 0은 '실제로 0'일 때만 써요.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from vsf.data.accounts import PERIODS, Sourced, extract, parse_amount
from vsf.data.dart import FinRows
from vsf.data.splits import SPLIT_FLAG, check_splits, close_factor, confirmed_split
from vsf.data.store import PriceRow
from vsf.excelfn import excel_round
from vsf.financial import CapitalRatio
from vsf.model import StockInputs, YearRow

QUICK_FAIL_NOTE = "최근 3년 중 배당을 안 준 해가 있어 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요."
OFS_NOTE = "별도 재무제표 기준이에요"
PBR_NOTE = "PBR은 추정값이에요"
ROE_END_NOTE = "{y}년 ROE는 기말 자본 기준이에요"
INTEREST_PAID_NOTE = "{y}년 이자보상배율은 '이자의 지급'으로 계산했어요"
SPECIAL_DIVIDEND_NOTE = "{y}년 배당성향이 100%를 넘어요(특별배당 의심)"
DPS_FLAG = "{y}년 DPS가 보고서마다 달라요. 확인해 주세요."
DPS_TEXT_FLAG = "{y}년 주당 현금배당금 값을 읽지 못했어요('{text}'). 확인해 주세요."
DPS_ROW_FLAG = "{year}년 사업보고서 배당 표에서 보통주 주당 현금배당금을 찾지 못했어요. 확인해 주세요."
CURRENCY_FLAG = "원화가 아닌 재무제표예요(통화: {currency}). 숫자를 확인해 주세요."
EQUITY_FLAG = "{y}년 자본이 0 이하예요. ROE·부채비율을 확인해 주세요."
SIGN_FLAG = "{y}년 EPS와 순이익의 부호가 달라요. 숫자를 확인해 주세요."
PER_UNIT_FLAG = "{y}년 연말 PER이 {per:g}배로 비정상적이에요(단위 오류 가능성). 숫자를 확인해 주세요."
OVERLAP_FLAG = "{y}년 {name}이(가) 보고서마다 달라요(정정·재작성 가능성). 확인해 주세요."
REBASE_NOTE = "{y}년 말 뒤 주식 수가 {r:g}배가 돼서 EPS·배당을 지금 주식 수 기준으로 나눴어요"
REBASE_SOURCE = " ÷ {r:g}(액면분할·무상증자 조정, {y}년 말 뒤)"
MERGE_NOTE = "{y}년 말 뒤 주식 수가 1/{n:g}로 줄어서 EPS·배당을 지금 주식 수 기준으로 곱했어요"
MERGE_SOURCE = " × {n:g}(주식 병합 조정, {y}년 말 뒤)"
FACE_NOTE = "{years}년 배당은 액면가 {old:,.0f}원 기준이라 지금 액면가 {now:,.0f}원 기준으로 맞췄어요"
FACE_SOURCE = " × {now:,.0f}/{old:,.0f}(액면분할 조정)"

NO_INTEREST_COVERAGE = 999.0   # 엑셀 규칙: 이자비용이 0이면 999
DPS_TOLERANCE = 0.02           # 보고서끼리 같은 해 DPS가 이보다 많이 다르면 확인 표시
OVERLAP_TOLERANCE = 0.02       # 겹치는 해 순이익·영업현금흐름도 마찬가지
PER_MAX, PER_MIN = 1000, 0.5   # 연말 PER이 이 범위 밖이면 단위 오류를 의심해요

_COLS = "BCDEF"
_FS_NAME = {"CFS": "연결", "OFS": "별도"}
_DPS_COLUMNS = ("thstrm", "frmtrm", "lwfr")
_DASHES = frozenset("-－–—‐−")   # 배당 표의 대시 = 그해 배당을 안 줬다는 뜻(0원)
_AMOUNT_ROWS = (("net_income", 33), ("ocf", 34), ("capex", 35), ("dividends_paid", 36))


@dataclass(frozen=True)
class CompanyInfo:
    corp_code: str
    code: str
    name: str
    market: str
    induty_code: str
    acc_mt: str
    financial_kind: str | None = None


@dataclass(frozen=True)
class Assembled:
    inputs: StockInputs
    flags: tuple[str, ...]        # '숫자 확인 필요' 사유
    notes: tuple[str, ...]        # 참고 메모
    sources: dict[str, str]       # 입력 칸 주소 → 출처 글
    quick_fail: bool
    latest_year: int
    capital: CapitalRatio | None = None


def _receipt(rcept_no: str | None) -> str:
    """출처 글에 붙이는 ", 접수번호 …". 접수번호가 없으면 빈 글자예요 (스펙 6.6)."""
    number = str(rcept_no or "").strip()
    return f", 접수번호 {number}" if number else ""


# ---- 배당 보고서 ----

def _dps_row(rows: list[dict]) -> dict | None:
    """보통주 '주당 현금배당금' 줄.

    - 주식 종류가 '보통'으로 시작하는 줄 (보통주·보통주식).
    - 종류 칸이 빈 줄('-' 포함)이 정확히 둘이면 첫 줄. 공시 서식이 보통주 줄을 우선주 줄보다 먼저 적어요
      (한국쉘석유·SK텔레콤·오뚜기 등). 셋 이상이면 어느 줄인지 몰라요.
    - 그 밖에는 줄이 하나뿐이고 우선주가 아닐 때만 그 줄.
    """
    per_share = [r for r in rows if "주당현금배당금" in (r.get("se") or "").replace(" ", "")]
    kinds = [(r.get("stock_knd") or "").strip() for r in per_share]
    common = [r for r, kind in zip(per_share, kinds, strict=True) if kind.startswith("보통")]
    if common:
        return common[0]
    if len(per_share) == 2 and all(kind == "" or kind in _DASHES for kind in kinds):
        return per_share[0]
    if len(per_share) == 1 and "우선" not in kinds[0]:
        return per_share[0]
    return None


def _dps_number(text: str) -> float | None:
    """DPS 글 하나(앞뒤 공백을 뗀 것). 대시 모양("-", "－", "–", "—", "‐", "−")은 0.0, 빈 글·숫자가 아닌 글은 None."""
    return 0.0 if text in _DASHES else parse_amount(text)


def _dps_values(row: dict | None, year: int) -> tuple[dict[int, float | None], list[tuple[int, str]]]:
    """줄 하나 → ({해: DPS}, [(해, 숫자로 읽지 못한 글)]). 빈칸은 None이고 읽지 못한 글로 치지 않아요."""
    out: dict[int, float | None] = {}
    unreadable: list[tuple[int, str]] = []
    for back, column in enumerate(_DPS_COLUMNS):
        raw = (row or {}).get(column)
        text = "" if raw is None else str(raw).strip()
        out[year - back] = _dps_number(text)
        if out[year - back] is None and text:
            unreadable.append((year - back, text))
    return out, unreadable


def _face_values(rows: list[dict], year: int) -> dict[int, float | None]:
    """배당 보고서 하나의 해별 '주당액면가액'. 줄이 없거나, 대시·무액면처럼 0보다 큰 숫자가 아니면 None.

    공시는 해마다 칸을 따로 적어요. 분할 전 해를 옛 액면가로 적은 보고서는 그 칸의 DPS도 옛 기준이에요.
    """
    row = next((r for r in rows or [] if "액면가액" in (r.get("se") or "").replace(" ", "")
                and ((r.get("stock_knd") or "").strip() in ("", *_DASHES)
                     or (r.get("stock_knd") or "").strip().startswith("보통"))), None)
    faces: dict[int, float | None] = {}
    for back, column in enumerate(_DPS_COLUMNS):
        text = "" if row is None or row.get(column) is None else str(row.get(column)).strip()
        value = None if text in _DASHES else parse_amount(text)
        faces[year - back] = value if value is not None and value > 0 else None
    return faces


def _faces(div_reports: dict[int, list[dict]]) -> tuple[float | None, dict[int, float]]:
    """(지금 액면가, 해 → 그해 말 액면가). 지금 액면가는 가장 최근 보고서의 당기 값이에요.

    그해 말 액면가는 그해를 담은 가장 이른 보고서 값이에요 (나중 보고서는 분할 뒤 기준으로 고쳐 적어요).
    """
    reports = sorted(y for y, rows in div_reports.items() if rows)
    now = _face_values(div_reports[reports[-1]], reports[-1])[reports[-1]] if reports else None
    at_year: dict[int, float] = {}
    for report_year in reports:
        for y, face in _face_values(div_reports[report_year], report_year).items():
            if face is not None and y not in at_year:
                at_year[y] = face
    return now, at_year


def dps_from_report(rows: list[dict], year: int) -> dict[int, float | None]:
    """배당 보고서 하나 → {year: 당기, year−1: 전기, year−2: 전전기}. 대시는 0.0, 값이 없거나 못 읽으면 None."""
    return _dps_values(_dps_row(rows or []), year)[0]


def _merge_dps(div_reports: dict[int, list[dict]]
               ) -> tuple[dict[int, float | None], dict[int, str], list[str], dict[int, float]]:
    """해마다 DPS, 그 값의 출처 글, 플래그, {해: 맞추기 전 액면가}. 겹치는 해는 더 최근 보고서 값이 먼저예요.

    값을 못 읽은 칸과, 보통주 주당 현금배당금 줄이 없는 보고서는 확인 표시를 달아요.
    그대로 두면 배당을 거른 해가 빈칸이 되어 관문 ②에서 조용히 빠져요.
    칸의 액면가가 지금 액면가와 다르면(액면분할·병합) DPS를 지금 액면가 기준으로 맞춘 뒤 비교해요.
    """
    values: dict[int, float | None] = {}
    origin: dict[int, str] = {}
    flags: list[str] = []
    scaled: dict[int, float] = {}
    now, _ = _faces(div_reports)

    def flag(text: str) -> None:
        if text not in flags:
            flags.append(text)

    for report_year in sorted(div_reports, reverse=True):
        rows = div_reports[report_year]
        if rows is None:
            continue
        row = _dps_row(rows)
        if row is None:
            flag(DPS_ROW_FLAG.format(year=report_year))
        read, unreadable = _dps_values(row, report_year)
        for y, text in unreadable:
            flag(DPS_TEXT_FLAG.format(y=y, text=text))
        receipt = _receipt((row or {}).get("rcept_no"))
        faces = _face_values(rows, report_year)
        for y, v in read.items():
            old = faces.get(y)
            rescale = v is not None and now is not None and old is not None and old != now
            if rescale:
                v = v * now / old
            kept = values.get(y)
            if kept is None:            # 처음 보는 해이거나, 더 최근 보고서에 값이 없던 해
                values[y] = v
                if v is not None:
                    origin[y] = f"{report_year} 사업보고서 배당에 관한 사항(보통주{receipt})"
                    if rescale:
                        origin[y] += FACE_SOURCE.format(now=now, old=old)
                        scaled[y] = old
            elif v is not None and abs(v - kept) > DPS_TOLERANCE * abs(kept):
                flag(DPS_FLAG.format(y=y))
    return values, origin, flags, scaled


def dps_by_year(div_reports: dict[int, list[dict]]) -> tuple[dict[int, float | None], tuple[str, ...]]:
    values, _, flags, _ = _merge_dps(div_reports)
    return values, tuple(flags)


def quick_fail_check(latest_div_rows: list[dict] | None, latest_year: int) -> bool:
    """최근 3년 중 보통주 DPS가 0인 해(대시 모양 포함)가 있으면 True. 값이 없는 해(None)는 0으로 보지 않아요."""
    if not latest_div_rows:
        return False
    return any(v == 0 for v in dps_from_report(latest_div_rows, latest_year).values())


# ---- 재무제표 기간과 출처 글 ----

@dataclass(frozen=True)
class _Period:
    """보고서 하나에 적힌 한 해의 계정들."""

    report_year: int
    fs: str
    rcept_no: str
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
    return {report_year - back: _Period(report_year, fin.fs, fin.rcept_no, extract(fin, period))
            for back, period in enumerate(PERIODS)}


def _net_income(p: _Period) -> Sourced:
    """지배주주 순이익. 그 줄이 없으면 당기순이익: 별도 재무제표이거나, 연결이지만 비지배지분이 없을 때 (S-Oil)."""
    s = p.acc["net_income_parent"]
    if s.value is not None:
        return s
    if p.fs == "OFS":
        return p.acc["profit_loss"]
    total = p.acc["profit_loss"]
    if total.value is not None and _no_minority(p):
        return Sourced(total.value, f"{total.account}(비지배지분 없음)", total.how)
    return s


def _no_minority(p: _Period) -> bool:
    """비지배 순이익 줄이 없거나 0이고, 지배기업 자본이 자본총계와 원 단위까지 같으면 비지배지분이 없는 회사예요.

    비지배지분이 조금이라도 있으면 두 자본이 달라요. 그때 당기순이익을 쓰면 그만큼 부풀어서 쓰지 않아요.
    """
    nci = p.acc["net_income_nci"].value
    parent, total = p.acc["equity_parent"].value, p.acc["equity_total"].value
    return not nci and parent is not None and parent == total


def _equity(p: _Period) -> Sourced:
    """ROE·PBR의 자본: 지배주주 자본 (별도 재무제표면 자본총계)."""
    return p.acc["equity_total" if p.fs == "OFS" else "equity_parent"]


def _begin_equity(p: _Period) -> Sourced:
    """자본변동표의 기초자본. _equity와 같은 기준(지배주주, 별도면 자본 전체)이에요."""
    return p.acc["equity_begin_total" if p.fs == "OFS" else "equity_begin_parent"]


def _sce_consistent(report: dict[int, _Period]) -> bool:
    """한 보고서의 자본변동표 기초자본이 재무상태표 기말 자본과 맞는지.

    (당기 기초 vs 전기 기말)과 (전기 기초 vs 전전기 기말)이 모두 숫자이고 0.5% 안에서 같아야 해요.
    """
    years = sorted(report, reverse=True)
    if len(years) < 3:
        return False
    for newer, older in zip(years, years[1:]):
        begin, end = _begin_equity(report[newer]).value, _equity(report[older]).value
        if begin is None or end is None or abs(begin - end) > 0.005 * abs(end):
            return False
    return True


def _acc(name: str) -> Callable[[_Period], Sourced]:
    return lambda p: p.acc[name]


def _field(main: dict[int, _Period], b: dict[int, _Period], y: int, latest: int,
           get: Callable[[_Period], Sourced]) -> tuple[_Period | None, Sourced | None]:
    """y년 계정 하나와 그 값을 적은 보고서.

    겹치는 해(L−2)는 A 보고서(전전기) 값을 쓰고, A에 그 계정 값이 없으면 B 보고서(당기) 값을 써요.
    계정마다 따로 정해서, 출처 글도 실제로 값을 가져온 보고서를 가리켜요.
    """
    p = main.get(y)
    s = get(p) if p is not None else None
    if y == latest - 2 and (s is None or s.value is None) and y in b and b[y] is not p:
        other = get(b[y])
        if other.value is not None:
            return b[y], other
    return p, s


def _label(*periods: _Period) -> str:
    """"2025 사업보고서(연결, 접수번호 …)". 두 보고서를 함께 쓰면 최근 것부터 쉼표로 이어요."""
    ordered = sorted(periods, key=lambda p: -p.report_year)
    names = (f"{p.report_year} 사업보고서({_FS_NAME.get(p.fs, p.fs)}{_receipt(p.rcept_no)})" for p in ordered)
    return ", ".join(dict.fromkeys(names))


def _account(s: Sourced) -> str:
    return s.account if s.how in ("id", "derived") else f"{s.account}(이름으로 찾음)"


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
                   price: PriceRow, latest: int, out: _Out,
                   faces: tuple[float | None, dict[int, float]] = (None, {})) -> tuple[float, float]:
    """(B 보고서 EPS를 나눌 배수, L년 말 뒤 분할 배수). 주식 수가 크게 바뀐 해가 있으면 확인 표시를 달아요.

    L년 말 뒤 분할이 주가로도 확인되면 표시 대신 메모를 남기고, 주당 값을 지금 주식 수 기준으로 나눌 배수를 돌려줘요.
    확인되지 않으면 그 배수는 1이고 확인 표시를 달아요.
    """
    newer = a[latest - 2].acc["eps"].value if latest - 2 in a else None
    older = b[latest - 2].acc["eps"].value if latest - 2 in b else None
    shares = {y: year_end[y].shares for y in range(latest - 9, latest + 1) if y in year_end}
    now_face, face_at = faces
    for y in range(latest - 9, latest - 4):   # 배당만 쓰는 옛 5년: 액면가 변화로 설명되는 주식 수 변화는 이미 배당에 맞췄어요
        if shares.get(y) and now_face and face_at.get(y):
            shares[y] = shares[y] * face_at[y] / now_face
    check = check_splits(newer, older, shares, latest)
    out.flag(*check.flags)
    end = year_end.get(latest)
    after = confirmed_split(end.shares, price.shares, end.close, price.close) if end is not None else None
    if after is not None and _report_on_year_end_basis(a.get(latest), end.shares, price.shares):
        out.note(REBASE_NOTE.format(y=latest, r=round(after, 2)) if after >= 1
                 else MERGE_NOTE.format(y=latest, n=round(1 / after, 2)))
        return check.eps_divisor_older, after
    if end is not None and close_factor(end.shares, price.shares) != 1.0:
        out.flag(SPLIT_FLAG)   # L년 말 뒤에 주식 수가 크게 바뀌었는데 주가로 확인되지 않아요
    return check.eps_divisor_older, 1.0


def _report_on_year_end_basis(p: _Period | None, shares_then: float, shares_now: float) -> bool:
    """A 보고서 EPS가 L년 말 주식 수 기준인지: 순이익 ÷ EPS(보고서가 쓴 주식 수)가 지금보다 L년 말 주식 수에 가까운지 (로그 거리).

    분할이 사업보고서 승인 전에 끝났으면 EPS가 이미 새 주식 수 기준이라 또 나누면 안 돼요.
    순이익이나 EPS가 없거나 0 이하면 확인할 수 없어서 False예요.
    """
    if p is None:
        return False
    income, e = _net_income(p).value, p.acc["eps"].value
    if income is None or e is None or income <= 0 or e <= 0:
        return False
    implied = income / e
    return abs(math.log(implied / shares_then)) < abs(math.log(implied / shares_now))


def _eps(main: dict[int, _Period], b: dict[int, _Period], divisor: float, latest: int,
         out: _Out) -> dict[int, float | None]:
    """L…L−2는 A 보고서 그대로, L−3·L−4(와 A에 없는 L−2)는 B 보고서 값을 divisor로 나눠요."""
    eps: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p, s = _field(main, b, y, latest, _acc("eps"))
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


def _dps_cell(y: int, latest: int) -> str:
    """y년 DPS 칸: 29행(최근 5년) 또는 42행(그 이전 5년)."""
    return _cell(y, latest, 29) if y > latest - 5 else f"{_COLS[y - latest + 9]}42"


def _dps(div_reports: dict[int, list[dict]], latest: int, years: range, out: _Out) -> dict[int, float | None]:
    """years의 DPS. 출처는 29행(최근 5년)과 42행(그 이전 5년)에 남겨요."""
    values, origin, flags, scaled = _merge_dps(div_reports)
    out.flag(*flags)
    for y in years:
        if values.get(y) is not None:
            out.sources[_dps_cell(y, latest)] = origin[y]
    now, _ = _faces(div_reports)
    for old in sorted({scaled[y] for y in years if y in scaled}, reverse=True):
        shown = "·".join(str(y) for y in years if scaled.get(y) == old)
        out.note(FACE_NOTE.format(years=shown, old=old, now=now))
    return {y: values.get(y) for y in years}


def _rebase(values: dict[int, float | None], r: float, latest: int, cell: Callable[[int], str],
            out: _Out) -> dict[int, float | None]:
    """L년 말 뒤 분할: 주당 값을 r로 나눠 지금 주식 수 기준으로 맞추고, 그 칸 출처 글에 덧붙여요."""
    tail = (REBASE_SOURCE.format(r=round(r, 2), y=latest) if r >= 1
            else MERGE_SOURCE.format(n=round(1 / r, 2), y=latest))
    rebased: dict[int, float | None] = {}
    for y, v in values.items():
        rebased[y] = None if v is None else v / r
        if v is not None and cell(y) in out.sources:
            out.sources[cell(y)] += tail
    return rebased


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
        p, s = _field(main, b, y, latest, _net_income)
        cur, prev = year_end_equity(y), year_end_equity(y - 1)
        income = s.value if s is not None else None
        roe[y] = None
        if income is None or cur is None:
            continue
        begin = None   # 전해 말 자본이 보고서에 없으면, 같은 보고서 자본변동표의 기초자본으로 대신해요
        if prev is None and _begin_equity(cur).value is not None:
            report = a if any(cur is q for q in a.values()) else b
            if _sce_consistent(report):
                begin = _begin_equity(cur).value
        if prev is not None:
            equity = (_equity(cur).value + _equity(prev).value) / 2
        elif begin is not None:
            equity = (_equity(cur).value + begin) / 2
        else:
            equity = _equity(cur).value
        if equity <= 0:
            out.flag(EQUITY_FLAG.format(y=y))
            continue
        roe[y] = excel_round(income / equity * 100, 2)
        if prev is None and begin is None:
            out.note(ROE_END_NOTE.format(y=y))
        if prev is not None:
            how = f"{y - 1}·{y}년 말 평균 자본"
        elif begin is not None:
            how = f"{y - 1}·{y}년 말 평균 자본({y - 1}년 말은 자본변동표 기초자본)"
        else:
            how = f"{y}년 말 자본"
        used = [p, cur, prev] if prev is not None else [p, cur]
        out.sources[_cell(y, latest, 30)] = f"{_label(*used)} · 순이익 ÷ {how}"
    return roe


def _debt_ratio(main: dict[int, _Period], b: dict[int, _Period], latest: int,
                out: _Out) -> dict[int, float | None]:
    """부채총계 ÷ 자본총계 × 100."""
    debt: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        p_liab, liab = _field(main, b, y, latest, _acc("liabilities"))
        p_eq, eq = _field(main, b, y, latest, _acc("equity_total"))
        liabilities = liab.value if liab is not None else None
        equity = eq.value if eq is not None else None
        debt[y] = None
        if liabilities is None or equity is None:
            continue
        if equity <= 0:
            out.flag(EQUITY_FLAG.format(y=y))
            continue
        debt[y] = excel_round(liabilities / equity * 100, 2)
        out.sources[_cell(y, latest, 31)] = f"{_label(p_liab, p_eq)} · 부채총계 ÷ 자본총계"
    return debt


def _coverage(main: dict[int, _Period], b: dict[int, _Period], latest: int,
              out: _Out) -> dict[int, float | None]:
    """영업이익 ÷ 이자비용. 이자비용이 없으면 '이자의 지급'(절댓값)으로, 분모가 0이면 999."""
    cov: dict[int, float | None] = {}
    for y in range(latest - 4, latest + 1):
        cov[y] = None
        p_inc, inc = _field(main, b, y, latest, _acc("operating_income"))
        p_den, exp = _field(main, b, y, latest, _acc("interest_expense"))
        income = inc.value if inc is not None else None
        expense = exp.value if exp is not None else None
        if expense is not None:
            denom, name = expense, "이자비용"
        else:
            p_den, paid = _field(main, b, y, latest, _acc("interest_paid"))
            denom, name = (paid.value if paid is not None else None), "이자의 지급"
        if income is None or denom is None:
            continue
        denom = abs(denom)
        cov[y] = NO_INTEREST_COVERAGE if denom == 0 else excel_round(income / denom, 2)
        if expense is None:
            out.note(INTEREST_PAID_NOTE.format(y=y))
        zero = "(0이라 999)" if denom == 0 else ""
        out.sources[_cell(y, latest, 32)] = f"{_label(p_inc, p_den)} · 영업이익 ÷ {name}{zero}"
    return cov


def _amounts(main: dict[int, _Period], b: dict[int, _Period], latest: int, out: _Out,
             only: tuple[str, ...] | None = None) -> dict[str, dict[int, float | None]]:
    """순이익·영업현금흐름·설비투자·배당금 지급 총액을 억 원으로."""
    got: dict[str, dict[int, float | None]] = {field: {} for field, _ in _AMOUNT_ROWS}
    for y in range(latest - 4, latest + 1):
        for field, row in _AMOUNT_ROWS:
            if only is not None and field not in only:
                continue
            p, s = _field(main, b, y, latest, _net_income if field == "net_income" else _acc(field))
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


def _number_checks(a: dict[int, _Period], b: dict[int, _Period], main: dict[int, _Period],
                   eps: dict[int, float | None], per: dict[int, float | None], latest: int, out: _Out,
                   financial: bool = False) -> None:
    """스펙 6.6: 의심스러운 숫자에 '숫자 확인 필요'를 달아요. 값은 그대로 두고 표시만 해요."""
    for y in range(latest - 4, latest + 1):
        _, s = _field(main, b, y, latest, _net_income)          # 33행과 같은 순이익
        e, income = eps.get(y), (s.value if s is not None else None)
        if e and income and (e > 0) != (income > 0):       # 0은 부호가 없어서 건너뛰어요
            out.flag(SIGN_FLAG.format(y=y))
        v = per.get(y)
        if v is not None and (v > PER_MAX or 0 < v < PER_MIN):
            out.flag(PER_UNIT_FLAG.format(y=y, per=v))
    y = latest - 2                                          # A·B 보고서가 함께 적은 해
    if y in a and y in b:
        checked = (("순이익", _net_income),) if financial else (
            ("순이익", _net_income), ("영업활동현금흐름", lambda p: p.acc["ocf"]))   # 금융회사는 영업현금흐름을 비워요
        for name, value in checked:
            kept, other = value(a[y]).value, value(b[y]).value
            if kept and other and abs(other - kept) > OVERLAP_TOLERANCE * abs(kept):
                out.flag(OVERLAP_FLAG.format(y=y, name=name))


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
             price_date: date, capital: CapitalRatio | None = None) -> Assembled:
    """L년(fin_a)·L−2년(fin_b) 사업보고서, 배당 보고서들, KRX 주가로 계산기 입력을 만들어요.

    fin_a가 없으면 재무 숫자는 모두 비워요 (B만으로는 최근 기준과 맞춰 볼 수 없어요). 실패로 볼지는 부르는 쪽이 정해요.
    """
    L = latest_year
    out = _Out()
    a = _periods(fin_a, L)
    b = _periods(fin_b, L - 2) if a else {}
    main = {**b, **a}                                  # 해 → 쓰는 기간. 겹치는 L−2는 A예요 (계정이 없으면 B, _field).
    if any(p.fs == "OFS" for p in main.values()):
        out.note(OFS_NOTE)
    _currency([fin for fin, used in ((fin_a, a), (fin_b, b)) if used], out)
    divisor, after = _split_divisor(a, b, year_end, price, L, out, _faces(div_reports))
    eps = _eps(main, b, divisor, L, out)
    dps = _dps(div_reports, L, range(L - 9, L + 1), out)
    per = _per(eps, year_end, L, out)        # 연말 종가와 같은 (L년 말) 기준 EPS로 — PER은 주식 수 기준과 무관해요
    if after != 1.0:                         # L년 말 뒤 분할: 주당 값을 현재가·현재 주식 수 기준으로 맞춰요
        eps = _rebase(eps, after, L, lambda y: _cell(y, L, 27), out)
        dps = _rebase(dps, after, L, lambda y: _dps_cell(y, L), out)
    roe = _roe(a, b, main, L, out)
    years_range = range(L - 4, L + 1)
    if company.financial_kind is None:
        debt = _debt_ratio(main, b, L, out)
        cov = _coverage(main, b, L, out)
        amounts = _amounts(main, b, L, out)
    else:      # 금융회사는 부채비율·이자보상배율·영업현금흐름·설비투자가 업종과 맞지 않아 비워요 (계산 자체를 건너뛰어 메모도 안 남겨요).
        debt, cov = dict.fromkeys(years_range), dict.fromkeys(years_range)
        amounts = {field: dict.fromkeys(years_range) for field, _ in _AMOUNT_ROWS}
        kept = ("net_income", "dividends_paid")
        amounts.update({f: v for f, v in _amounts(main, b, L, out, only=kept).items() if f in kept})
    pbr = _pbr(a, eps, L, price, price_date, out)
    _number_checks(a, b, main, eps, per, L, out, financial=company.financial_kind is not None)
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
    return Assembled(inputs, tuple(out.flags), tuple(out.notes), out.sources, False, L, capital)


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
