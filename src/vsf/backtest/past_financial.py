"""DART 재무제표 API에 없는 해의 금융회사 입력 (2026-11-24 백테스트 설계 4장).

DART 재무제표 API에는 대략 2021 사업연도 이전 금융회사(은행·금융지주·보험) 자료가 없어요.
그 해들은 같은 사업보고서의 '배당에 관한 사항'에 있는 (연결)주당순이익·당기순이익·DPS와
금감원 FISIS ROE로 계산기 입력을 채워요. 금융회사 관문은 ROE·적자 여부·자본비율·배당만 봐서
부채비율·이자보상배율·현금흐름은 비워 둬요.
"""
from __future__ import annotations

from datetime import date

from vsf.data.accounts import parse_amount
from vsf.data.assemble import Assembled, CompanyInfo, PreferredShare, dividend_history, preferred_kind
from vsf.data.fisis import EQUITY_TABLES, ROE_TABLES
from vsf.data.store import PriceRow
from vsf.excelfn import excel_round
from vsf.financial import CapitalRatio
from vsf.model import StockInputs, YearRow

SUBSTITUTE_NOTE = ("DART 재무제표 API에 이 해 금융회사 자료가 없어 배당 공시의 주당순이익·순이익·DPS와 "
                   "금감원 FISIS ROE로 채웠어요")
_COLUMNS = ("thstrm", "frmtrm", "lwfr")


def _row_values(rows: list[dict], report_year: int) -> dict[int, dict[str, float]]:
    """배당 공시 한 건 → {해: {"eps", "ni", "ni_sep"}}. 순이익은 억 원이에요. (연결) 줄을 먼저 써요."""
    out: dict[int, dict[str, float]] = {report_year - back: {} for back in range(3)}
    for consolidated in (True, False):
        for r in rows:
            se = (r.get("se") or "").replace(" ", "")
            if consolidated != se.startswith("(연결)"):
                continue
            for back, column in enumerate(_COLUMNS):
                v = parse_amount(str(r.get(column) or ""))
                if v is None:
                    continue
                got = out[report_year - back]
                if "주당순이익" in se:
                    got.setdefault("eps", v)
                elif se.startswith("(별도)") and "당기순이익" in se:
                    got.setdefault("ni_sep", v / 100)        # 백만 원 → 억 원
                elif "당기순이익" in se:
                    got.setdefault("ni", v / 100)
    return out


def _by_year(div_reports: dict[int, list[dict]]) -> dict[int, dict[str, float]]:
    """보고서 여러 건을 해마다 하나로. 겹치는 해는 더 최근 보고서 값이 먼저예요."""
    merged: dict[int, dict[str, float]] = {}
    for report_year in sorted(div_reports, reverse=True):
        for y, values in _row_values(div_reports[report_year] or [], report_year).items():
            for k, v in values.items():
                merged.setdefault(y, {}).setdefault(k, v)
    return merged


def _roe(info: CompanyInfo, fisis, names: tuple[str, ...], latest: int,
         values: dict[int, dict[str, float]]) -> dict[int, float | None]:
    years = range(latest - 4, latest + 1)
    if fisis is None:
        return dict.fromkeys(years)
    if info.financial_kind in ROE_TABLES:
        part, list_no, account = ROE_TABLES[info.financial_kind]
        got = fisis.annual_values(part, names, list_no, account, latest - 4, latest)
        return {y: got.get(y) for y in years}
    tables = EQUITY_TABLES.get(info.financial_kind or "")
    if tables:                                   # 보험·증권: (별도)당기순이익 ÷ 개별 자본총계(연말 평균)
        equity: dict[int, float] = {}
        for part, list_no, account in tables:
            equity = {y: v / 1e8 for y, v in fisis.annual_values(part, names, list_no, account, latest - 5, latest).items()}
            if equity:
                break
        roe: dict[int, float | None] = {}
        for y in years:
            income = values.get(y, {}).get("ni_sep")
            if income is None or y not in equity or (y - 1) not in equity:
                roe[y] = None
            else:
                roe[y] = excel_round(income / ((equity[y] + equity[y - 1]) / 2) * 100, 2)
        return roe
    return dict.fromkeys(years)


def substitute_inputs(info: CompanyInfo, latest: int, div_reports: dict[int, list[dict]],
                      year_end: dict[int, PriceRow], price: PriceRow, price_date: date, fisis,
                      names: tuple[str, ...], capital: CapitalRatio | None,
                      preferred: PreferredShare | None = None) -> Assembled:
    """사업연도 latest의 금융회사 계산기 입력을 배당 공시와 FISIS로 채워요.

    PER은 연말 종가 ÷ EPS(EPS > 0)이에요. 우선주면 주가·연말 종가·배당이 우선주 것이에요.
    """
    kind = preferred_kind(preferred.name) if preferred else "보통"
    dps, flags, notes = dividend_history(div_reports, latest, kind, info.est_dt)
    values = _by_year(div_reports)
    roe = _roe(info, fisis, names, latest, values)
    closes = preferred.year_end if preferred else year_end
    shown = preferred.price if preferred else price
    years = []
    for y in range(latest - 4, latest + 1):
        eps = values.get(y, {}).get("eps")
        row = closes.get(y)
        per = (excel_round(row.close / eps, 2)
               if row is not None and row.close is not None and eps is not None and eps > 0 else None)
        income = values.get(y, {}).get("ni")
        years.append(YearRow(year=y, eps=eps, per=per, dps=dps.get(y), roe=roe.get(y),
                             net_income=None if income is None else excel_round(income, 2)))
    prior = range(latest - 9, latest - 4)
    memo = (f"자동 수집 {price_date}: DART 배당 공시 {'·'.join(map(str, sorted(div_reports))) or '자료 없음'}, "
            f"금감원 FISIS, 주가 KRX {price_date} 종가. {SUBSTITUTE_NOTE}")
    inputs = StockInputs(name=info.name, code=info.code, price=shown.close, price_date=price_date, memo=memo,
                         years=tuple(years), prior_years=tuple(prior), prior_dps=tuple(dps.get(y) for y in prior))
    return Assembled(inputs, flags, notes + (SUBSTITUTE_NOTE,), {}, False, latest, capital)
