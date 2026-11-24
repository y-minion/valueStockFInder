"""점수 자료 받기: 최근 4분기 EPS, 분기·반기 배당, 자사주, 상장 자회사 (점수 순위 설계 6장).

모두 OpenDART 정기보고서 주요정보예요. 지난 사업연도 자료는 DartClient가 캐시해요.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from vsf.data.assemble import current_dps
from vsf.data.dart import DartError, DartQuotaExceeded
from vsf.data.http import NetworkError

log = logging.getLogger("vsf.score_facts")

_COMMON = ("보통주", "의결권 있는 보통주")
_DPS_SE = "주당 현금배당금"
_FOOTNOTE = re.compile(r"\s*주\s*\d+\)")
_COMPANY_MARKS = re.compile(r"㈜|\(주\)|주식회사")


@dataclass(frozen=True)
class ScoreFacts:
    ttm_eps: float | None = None            # 최근 4분기 EPS (원)
    ttm_label: str | None = None            # "2025년 4분기~2026년 3분기"
    ttm_is_annual: bool = False             # 사업보고서 뒤 분기 보고서가 아직 없음
    payout_per_year: int | None = None      # 4 분기 · 2 반기 · 1 연 1회 · None 자료 없음
    issued: float | None = None             # 보통주 발행주식 총수
    treasury: float | None = None           # 보통주 자기주식 수
    buyback_years: tuple[bool | None, ...] = (None, None, None)   # 최근 사업연도부터 3년
    cancelled: float | None = None          # 최근 사업연도 소각 주식 수
    subsidiaries: tuple[tuple[str, float], ...] | None = None     # 상장 자회사 (이름, 지분율%)
    sources: dict[str, str] = field(default_factory=dict)         # 항목 키 → 출처 글


def _num(v) -> float | None:
    """DART 숫자 글: "8,515,181" → 8515181, "-" → 0, 빈칸·못 읽는 글 → None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("-", "－", "–", "—"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def parse_stock_total(rows: list[dict]) -> tuple[float | None, float | None]:
    """주식의 총수 현황 → (보통주 발행주식 총수, 보통주 자기주식 수). 보통주 줄이 없으면 합계 줄."""
    pick = next((r for r in rows if str(r.get("se", "")).strip() in _COMMON), None)
    pick = pick or next((r for r in rows if str(r.get("se", "")).strip() == "합계"), None)
    if pick is None:
        return None, None
    issued = _num(pick.get("istc_totqy"))
    return (issued if issued else None), _num(pick.get("tesstk_co"))


def parse_treasury_changes(rows: list[dict]) -> tuple[float | None, float | None]:
    """자기주식 취득·처분 현황 → (그해 매입, 그해 소각), 보통주 기준.

    줄이 취득 방법별 세부·소계·총계로 와서, 보통주 '총계' 줄만 써요(겹쳐 세지 않게).
    매입 = 총계 취득 − 기타취득 취득(단주 등은 매입이 아니에요).
    표가 '-'뿐이면 그해 활동이 없는 거라 (0, 0)이에요.
    """
    common = [r for r in rows if str(r.get("stock_knd", "")).strip() == "보통주"]
    total = next((r for r in common if str(r.get("acqs_mth1", "")).strip() == "총계"), None)
    if total is None:
        if rows and all(_num(r.get(k)) in (0.0, None) and str(r.get(k, "-")).strip() in ("-", "")
                        for r in rows for k in ("change_qy_acqs", "change_qy_incnr")):
            return 0.0, 0.0
        return None, None
    other = next((r for r in common if str(r.get("acqs_mth1", "")).strip() == "기타취득"), None)
    acq = _num(total.get("change_qy_acqs"))
    other_acq = _num(other.get("change_qy_acqs")) if other else 0.0
    bought = None if acq is None else max(0.0, acq - (other_acq or 0.0))
    return bought, _num(total.get("change_qy_incnr"))


def _common_dps(rows: list[dict] | None) -> float | None:
    """분기·반기 배당 표의 보통주 주당 현금배당금. '보통주식'·'보 통 주'·종류 칸 '-' 같은 모양도 사업보고서처럼 읽어요."""
    return current_dps(rows) if rows else None


def interim_payouts(q1_rows: list[dict] | None, half_rows: list[dict] | None) -> int | None:
    """1분기 보고서에 보통주 배당이 있으면 분기(4), 반기 보고서에 있으면 반기(2), 받았는데 둘 다 0이면 1."""
    q1, half = _common_dps(q1_rows), _common_dps(half_rows)
    if q1 is not None and q1 > 0:
        return 4
    if half is not None and half > 0:
        return 2
    if q1 is None and half is None:
        return None
    return 1


def normalize_name(s: str) -> str:
    """회사 이름 맞추기용: 주석 표시(주4)), ㈜·(주)·주식회사, 공백·줄바꿈을 빼요."""
    s = _FOOTNOTE.sub("", str(s or ""))
    s = _COMPANY_MARKS.sub("", s)
    return re.sub(r"\s+", "", s)


def listed_subsidiaries(rows: list[dict], listed_names: set[str],
                        stake_min: float) -> tuple[tuple[str, float], ...]:
    """타법인 출자 현황에서 기말 지분율이 stake_min% 이상이고 이름이 상장 회사와 맞는 회사."""
    out: list[tuple[str, float]] = []
    for r in rows:
        name = normalize_name(r.get("inv_prm", ""))
        stake = _num(r.get("trmend_blce_qota_rt"))
        if not name or name == "합계" or stake is None or stake < stake_min:
            continue
        if name in listed_names:
            out.append((name, stake))
    return tuple(out)


def _src(year: int, kind: str, rows: list[dict] | None) -> str:
    no = next((str(r.get("rcept_no")) for r in rows or [] if r.get("rcept_no")), "")
    return f"{year} {kind}" + (f" (접수번호 {no})" if no else "")


def fetch_score_facts(dart, corp: str, latest_year: int, latest_eps: float | None,
                      listed_names: set[str], stake_min: float) -> ScoreFacts:
    from vsf.extras import latest_quarter   # extras가 evaluate를 불러서, 순환을 피하려고 여기서 불러요

    src: dict[str, str] = {}
    ttm_eps = ttm_label = None
    q = latest_quarter(dart, corp, latest_year + 1)
    ttm_is_annual = q is None                 # 보고서 자체가 없을 때만 '연간이 가장 최신'이에요
    if q is not None and all(isinstance(x, (int, float)) for x in (latest_eps, q.get("eps"), q.get("eps_prev"))):
        ttm_eps = latest_eps + q["eps"] - q["eps_prev"]
        n = q["quarter"]
        ttm_label = f"{latest_year}년 {n + 1}분기~{q['year']}년 {n}분기"
        src["ttm"] = f"{latest_year} 사업보고서 EPS + {q['label']} 누적 EPS − 작년 같은 때 누적 EPS"
    elif ttm_is_annual:
        src["ttm"] = f"{latest_year + 1}년 분기 보고서가 아직 없어 {latest_year} 사업보고서가 가장 최신이에요"

    year = latest_year + 1
    half = dart.periodic("alotMatter", corp, year, "11012")
    if half is None:
        year = latest_year
        half = dart.periodic("alotMatter", corp, year, "11012")
    q1 = dart.periodic("alotMatter", corp, year, "11013")
    payout = interim_payouts(q1, half)
    if payout is not None:
        src["freq"] = f"{year} 1분기·반기 보고서 배당에 관한 사항"

    total = dart.periodic("stockTotqySttus", corp, latest_year)
    issued, treasury = parse_stock_total(total) if total else (None, None)
    if total:
        src["treasury"] = _src(latest_year, "사업보고서 주식의 총수 현황", total)

    years: list[bool | None] = []
    cancelled = None
    for i, yr in enumerate((latest_year, latest_year - 1, latest_year - 2)):
        changes = dart.periodic("tesstkAcqsDspsSttus", corp, yr)
        bought, inc = parse_treasury_changes(changes) if changes is not None else (None, None)
        years.append(None if bought is None and inc is None else (bought or 0) > 0 or (inc or 0) > 0)
        if i == 0:
            cancelled = inc
            if changes is not None:
                src["cancel"] = _src(yr, "사업보고서 자기주식 취득 및 처분 현황", changes)
    if any(y is not None for y in years):
        src["buyback"] = f"{latest_year - 2}~{latest_year} 사업보고서 자기주식 취득 및 처분 현황"

    inv = dart.periodic("otrCprInvstmntSttus", corp, latest_year)
    subs = None if inv is None else listed_subsidiaries(inv, listed_names, stake_min)
    if inv is not None:
        src["subsidiary"] = _src(latest_year, "사업보고서 타법인 출자 현황", inv)
    return ScoreFacts(ttm_eps=ttm_eps, ttm_label=ttm_label, ttm_is_annual=ttm_is_annual,
                      payout_per_year=payout, issued=issued, treasury=treasury,
                      buyback_years=tuple(years), cancelled=cancelled, subsidiaries=subs, sources=src)


def gather_score_facts(run, dart, listed_names: set[str], stake_min: float,
                       eligible: Iterable[str]) -> tuple[dict[str, ScoreFacts], bool]:
    """점수 대상 종목마다 자료를 받아요. 하루 한도에 닿으면 멈추고 (받은 것, True)를 돌려줘요.

    한 종목의 다른 오류는 그 종목만 빈 자료(전부 '자료 없음')로 두고 계속해요.
    """
    out: dict[str, ScoreFacts] = {}
    for code in eligible:
        r = run.results[code]
        a = r.assembled
        eps = a.inputs.years[-1].eps if a.inputs.years else None
        try:
            out[code] = fetch_score_facts(dart, r.company.corp_code, a.latest_year, eps, listed_names, stake_min)
        except DartQuotaExceeded:
            return out, True
        except (DartError, NetworkError, ValueError) as e:
            out[code] = ScoreFacts(sources={"error": f"점수 자료를 받지 못했어요: {e}"})
        except Exception as e:  # noqa: BLE001 - 한 종목 때문에 리포트가 멈추면 안 돼요
            log.exception("%s 점수 자료를 받다 예상하지 못한 오류가 났어요", code)
            out[code] = ScoreFacts(sources={"error": f"점수 자료를 받지 못했어요: {type(e).__name__}"})
    return out, False


def score_facts_to_dict(f: ScoreFacts) -> dict:
    d = asdict(f)
    d["buyback_years"] = list(f.buyback_years)
    d["subsidiaries"] = None if f.subsidiaries is None else [list(s) for s in f.subsidiaries]
    return d


def score_facts_from_dict(d: dict | None) -> ScoreFacts | None:
    if d is None:
        return None
    subs = d.get("subsidiaries")
    return ScoreFacts(ttm_eps=d.get("ttm_eps"), ttm_label=d.get("ttm_label"),
                      ttm_is_annual=bool(d.get("ttm_is_annual")), payout_per_year=d.get("payout_per_year"),
                      issued=d.get("issued"), treasury=d.get("treasury"),
                      buyback_years=tuple(d.get("buyback_years") or (None, None, None)),
                      cancelled=d.get("cancelled"),
                      subsidiaries=None if subs is None else tuple((str(n), float(s)) for n, s in subs),
                      sources=dict(d.get("sources") or {}))
