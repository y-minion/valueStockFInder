"""수집한 자료를 종목마다 계산해서 판정 결과로 만들어요."""
from dataclasses import dataclass

from vsf.collect import Collected
from vsf.config import ReportSettings, Settings, settings_fingerprint
from vsf.data.assemble import Assembled, CompanyInfo
from vsf.engine import Summary, compute, is_near, summarize, watch_state
from vsf.excelfn import is_num
from vsf.financial import FinancialGate, financial_gate
from vsf.industry import (IndustryInfo, build_industry, effective_criteria, extra_gate1,
                          industry_inputs)
from vsf.model import Criteria, SheetValues, StockInputs

FAIR_VALUE_FLAG = ("적정가 세 방법 중 {missing}를 계산하지 못했어요(연말 PER·배당 자료 부족). "
                   "숫자를 확인해 주세요.")


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
    eval_flags: tuple[str, ...]   # 계산 뒤에 단 '숫자 확인 필요' 사유
    financial: FinancialGate | None = None

    @property
    def flags(self) -> tuple[str, ...]:
        """'숫자 확인 필요' 사유 전부: 조립 단계 표시(assembled.flags) 다음에 계산 뒤 표시."""
        return self.assembled.flags + self.eval_flags


@dataclass
class RunResult:
    collected: Collected
    settings_fp: dict
    results: dict[str, StockResult]


def state_of(inputs: StockInputs, criteria: Criteria, extra: str | None, report: ReportSettings,
             financial: FinancialGate | None = None) -> str:
    return watch_state(summarize(compute(inputs, criteria, extra, financial=financial)), report)


def evaluation_flags(cells: SheetValues, state: str) -> tuple[str, ...]:
    """계산 결과를 보고 다는 '숫자 확인 필요' 사유.

    적정가 B(과거 PER)·C(과거 배당수익률)가 빠지면 MIN()에 A(이론)만 남아 매수선이 올라가요.
    그러면 연말 주가 같은 자료 하나가 없어서 조용히 '매수선 이하'가 나올 수 있어요.
    정상 EPS가 양수이고 'out'이 아닌 종목만 봐요 (어차피 빠지는 종목에는 표시하지 않아요).
    """
    b96 = cells.get("B96")
    if state == "out" or not is_num(b96) or b96 <= 0:
        return ()
    missing = [name for name, addr in (("B", "B103"), ("C", "B104")) if not is_num(cells.get(addr))]
    return (FAIR_VALUE_FLAG.format(missing="·".join(missing)),) if missing else ()


def evaluate_one(company: CompanyInfo, assembled: Assembled, settings: Settings,
                 industry: IndustryInfo | None) -> StockResult:
    criteria = effective_criteria(settings.criteria, company.induty_code, settings.industry.overrides)
    extra = extra_gate1(industry, settings.industry)
    fin = financial_gate(company.financial_kind, assembled.capital, settings.financial)
    cells = compute(assembled.inputs, criteria, extra, financial=fin)
    summary = summarize(cells)
    state = watch_state(summary, settings.report)
    return StockResult(company=company, assembled=assembled, criteria=criteria, extra_gate1=extra,
                       cells=cells, summary=summary, industry=industry, state=state,
                       near=state != "out" and is_near(summary, settings.report),
                       eval_flags=evaluation_flags(cells, state), financial=fin)


def evaluate(collected: Collected, settings: Settings) -> RunResult:
    # 업종 묶음은 보통주만으로 만들어요. 우선주는 같은 회사 보통주의 업종 정보를 그대로 써요 (두 번 세지 않게).
    stocks = {code: (company.induty_code, *industry_inputs(assembled.inputs))
              for code, (company, assembled) in collected.records.items() if company.common_code is None}
    table = build_industry(stocks, settings.industry.min_group_size)
    results = {code: evaluate_one(company, assembled, settings, table.get(company.common_code or code))
               for code, (company, assembled) in collected.records.items()}
    return RunResult(collected=collected, settings_fp=settings_fingerprint(settings), results=results)
