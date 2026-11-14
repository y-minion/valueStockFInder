"""수집한 자료를 종목마다 계산해서 판정 결과로 만들어요."""
from dataclasses import dataclass

from vsf.collect import Collected
from vsf.config import ReportSettings, Settings, settings_fingerprint
from vsf.data.assemble import Assembled, CompanyInfo
from vsf.engine import Summary, compute, is_near, summarize, watch_state
from vsf.industry import (IndustryInfo, build_industry, effective_criteria, extra_gate1,
                          industry_inputs)
from vsf.model import Criteria, SheetValues, StockInputs


@dataclass(frozen=True)
class StockResult:
    company: CompanyInfo
    assembled: Assembled
    criteria: Criteria
    extra_gate1: str | None
    cells: SheetValues
    summary: Summary
    industry: IndustryInfo | None
    state: str
    near: bool


@dataclass
class RunResult:
    collected: Collected
    settings_fp: dict
    results: dict[str, StockResult]


def state_of(inputs: StockInputs, criteria: Criteria, extra: str | None, report: ReportSettings) -> str:
    return watch_state(summarize(compute(inputs, criteria, extra)), report)


def evaluate_one(company: CompanyInfo, assembled: Assembled, settings: Settings,
                 industry: IndustryInfo | None) -> StockResult:
    criteria = effective_criteria(settings.criteria, company.induty_code, settings.industry.overrides)
    extra = extra_gate1(industry, settings.industry)
    cells = compute(assembled.inputs, criteria, extra)
    summary = summarize(cells)
    state = watch_state(summary, settings.report)
    return StockResult(company=company, assembled=assembled, criteria=criteria, extra_gate1=extra,
                       cells=cells, summary=summary, industry=industry, state=state,
                       near=state != "out" and is_near(summary, settings.report))


def evaluate(collected: Collected, settings: Settings) -> RunResult:
    stocks = {code: (company.induty_code, *industry_inputs(assembled.inputs))
              for code, (company, assembled) in collected.records.items()}
    table = build_industry(stocks, settings.industry.min_group_size)
    results = {code: evaluate_one(company, assembled, settings, table.get(code))
               for code, (company, assembled) in collected.records.items()}
    return RunResult(collected=collected, settings_fp=settings_fingerprint(settings), results=results)
