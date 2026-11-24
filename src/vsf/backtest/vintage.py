"""회사×사업연도 판정 묶음 만들기 (2026-11-24 백테스트 설계 4장).

계산은 주간 실행과 같은 조립(assemble_for_year)과 판정(evaluate_one)을 써요. 사업연도 L의 묶음은
그 사업보고서가 처음 공시된 날 다음 첫 거래일의 주가로 조립하고, 그날부터 다음 해 묶음 전까지 써요.
공시일 당일은 빼요. 장 마감 뒤에 올라온 보고서는 그날 종가로 사고팔 수 없었어요.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

from vsf.backtest.model import Verdict, Vintage
from vsf.backtest.past_financial import substitute_inputs
from vsf.collect import (FIRST_DIV_YEAR, NO_CORP, NO_FIN, PREFERRED, _capital, _Excluded, _Failed, _prepare,
                         _year_ends, assemble_for_year, context_for, preferred_base)
from vsf.config import Settings
from vsf.data.assemble import Assembled, CompanyInfo, PreferredShare, dividend_history, preferred_kind
from vsf.data.dart import DartQuotaExceeded
from vsf.data.krx import Listed
from vsf.data.universe import is_financial_holding, is_holding_like, listing_exclusion
from vsf.evaluate import evaluate_one
from vsf.excelfn import is_num

NON_DECEMBER = "결산월이 12월이 아니에요"
NO_PAST_ROE = "과거 ROE 자료가 없는 금융회사예요 (대체 자료)"
PROGRESS_EVERY = 200


def _verdict(info: CompanyInfo, asm: Assembled, settings: Settings,
             overrides: tuple[tuple[str, float], ...]) -> Verdict:
    s = replace(settings, criteria=replace(settings.criteria, **dict(overrides)))
    res = evaluate_one(info, asm, s, None)
    b105, b107 = res.cells.get("B105"), res.cells.get("B107")
    return Verdict(gate1=res.summary.gate1, gate2=res.summary.gate2,
                   fair=float(b105) if is_num(b105) else None, buy_line=float(b107) if is_num(b107) else None,
                   method=res.summary.method, uncomputable=b105 == "계산 불가")


def _payer(dart, corp: str, years: range, kind: str, est_dt: str) -> bool:
    """기간 안에 한 번이라도 배당을 준 회사. 이런 회사는 배당을 거른 해에도 끝까지 조립해서 적정가를 남겨요."""
    last = years.stop - 1
    reports = {y: rows for y in range(last, last - 11, -2)
               if y >= FIRST_DIV_YEAR and (rows := dart.dividends(corp, y)) is not None}
    if not reports:
        return False
    values, _, _ = dividend_history(reports, last, kind, est_dt)
    return any(v is not None and v > 0 for y, v in values.items() if y >= years.start - 4)


def _substitute(ctx, dart, item: Listed, common: str | None, year: int,
                last_year: int) -> tuple[CompanyInfo, Assembled]:
    """재무제표가 없는 해의 금융회사. 금융회사가 아니면 원래 실패(_Failed)를 그대로 올려요."""
    prep = _prepare(ctx, item, common)
    kind = prep.info.financial_kind
    if kind is None and is_holding_like(prep.raw):
        # 금융지주인지는 재무상태표로 가려요. 그해 표가 없으면 나중 해 표로 회사 종류만 봐요 (숫자는 안 써요).
        later = next((f for y in range(last_year, year, -1) if (f := dart.financials(prep.corp, y)) is not None), None)
        if is_financial_holding(later):
            kind = "금융지주"
    if kind is None:
        raise _Failed(NO_FIN.format(year=year))
    info = replace(prep.info, financial_kind=kind)
    div_reports = {y: rows for y in range(year, year - 9, -2)
                   if y >= FIRST_DIV_YEAR and (rows := dart.dividends(prep.corp, y)) is not None}
    year_end = {y: rows[prep.base] for y, rows in ctx.year_ends.items() if prep.base in rows}
    pref = None if common is None else PreferredShare(
        item.code, item.name, prep.price, {y: rows[item.code] for y, rows in ctx.year_ends.items() if item.code in rows})
    capital, notes = _capital(ctx, info, prep.raw, item)
    names = (str(prep.raw.get("corp_name") or ""), str(prep.raw.get("corp_name_eng") or ""), item.name)
    asm = substitute_inputs(info, year, div_reports, year_end, prep.base_price, ctx.price_date, ctx.fisis, names,
                            capital, preferred=pref)
    if all(y.roe is None for y in asm.inputs.years):
        # ROE 칸이 다 비면 관문 ①이 '확인 필요'로 공짜 통과해요. 자료가 없어서 생긴 통과라 묶음을 만들지 않아요.
        raise _Failed(NO_PAST_ROE)
    return info, replace(asm, notes=asm.notes + notes) if notes else asm


def build_vintages(universe: dict[str, Listed], filings: dict[tuple[str, int], date], years: range,
                   market, dart, settings: Settings, fisis_for: Callable[[date], object | None],
                   progress: Callable[[str], None] = print) -> tuple[dict[str, list[Vintage]], list[tuple[str, int, str]]]:
    """코드 → valid_from 순 묶음 목록, 그리고 못 만든 묶음 [(코드, 사업연도, 사유)].

    DartQuotaExceeded는 그대로 올려요 (받은 자료는 저장소에 남아 다음 실행이 이어서 써요).
    """
    corp_map = dart.corp_codes()
    vintages: dict[str, list[Vintage]] = {}
    failures: list[tuple[str, int, str]] = []
    work: list[tuple[date, str, int, Listed, str | None, str, bool, date]] = []
    for code in sorted(universe):
        item = universe[code]
        reason = listing_exclusion(item)
        common = None
        if reason == PREFERRED:
            common = preferred_base(code)
            if common not in universe:
                continue
        elif reason:
            continue
        corp = corp_map.get(common or code)
        if not corp:
            failures.append((code, years.start, NO_CORP))
            continue
        try:
            raw = dart.company(corp)
            if raw is None:
                failures.append((code, years.start, NO_CORP))
                continue
            if str(raw.get("acc_mt") or "12").zfill(2) != "12":
                failures.append((code, years.start, NON_DECEMBER))
                continue
            payer = _payer(dart, corp, years, preferred_kind(item.name) if common else "보통",
                           str(raw.get("est_dt") or ""))
        except DartQuotaExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - 회사 하나의 오류로 전체를 멈추지 않아요
            failures.append((code, years.start, f"{type(e).__name__}: {e}"))
            continue
        for year in years:
            filed = filings.get((corp, year))
            if filed is None:
                continue
            valid_from = market.first_trading_day_on_or_after(filed + timedelta(days=1))
            if valid_from is None or valid_from > market.end:
                continue
            work.append((valid_from, code, year, item, common, corp, payer, filed))

    work.sort(key=lambda w: (w[0], w[1], w[2]))
    ends: dict[int, dict] = {}
    ctx = None
    for i, (valid_from, code, year, item, common, corp, payer, filed) in enumerate(work, 1):
        if ctx is None or ctx.price_date != valid_from:
            if valid_from.year not in ends:
                ends[valid_from.year] = _year_ends(market.krx, valid_from)[0]
            ctx = context_for(dart, market.krx, valid_from, corp_map, include_financial=settings.financial.include,
                              fisis=fisis_for(valid_from), year_ends=ends[valid_from.year])
        try:
            substitute = False
            try:
                info, asm = assemble_for_year(ctx, item, year, common, quick_fail=not payer)
            except _Failed as e:
                if str(e) != NO_FIN.format(year=year):
                    raise
                info, asm = _substitute(ctx, dart, item, common, year, max(market.today.year, year + 1) - 1)
                substitute = True
            verdicts = {name: _verdict(info, asm, settings, overrides)
                        for name, overrides in settings.backtest.variants}
        except DartQuotaExceeded:
            raise
        except (_Excluded, _Failed) as e:
            failures.append((code, year, str(e)))
            continue
        except Exception as e:  # noqa: BLE001
            failures.append((code, year, f"{type(e).__name__}: {e}"))
            continue
        row = ctx.prices.get(code)
        vintages.setdefault(code, []).append(Vintage(
            code=code, corp_code=corp, name=item.name, common_code=common, year=year, filed=filed,
            valid_from=valid_from, shares=row.shares if row is not None else None,
            dps=asm.inputs.years[-1].dps, substitute=substitute, verdicts=verdicts))
        if i % PROGRESS_EVERY == 0 or i == len(work):
            progress(f"판정 묶음 {i}/{len(work)}")
    return vintages, failures
