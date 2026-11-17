"""관문 ④ 판단 자료: 관심 목록 종목의 최근 공시·뉴스·올해 분기 실적·주가 흐름."""
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

from vsf.data.accounts import extract
from vsf.data.dart import DartError, DartQuotaExceeded, FinRows
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError
from vsf.data.naver import NaverAuthError, NaverNews
from vsf.engine import eps_scenario
from vsf.evaluate import RunResult
from vsf.excelfn import excel_round

_CAUGHT = (NetworkError, DartError, KrxError, ValueError)
_DISCLOSURE_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
_NEWS_LINK = "https://search.naver.com/search.naver?where=news&query={}"
_QUOTA_NOTE = "오늘 DART 호출 한도에 닿아 일부 자료를 받지 못했어요"
_NAVER_KEY_NOTE = "네이버 검색 키가 맞지 않아 뉴스를 가져오지 못했어요. keys.toml의 [naver] 값을 확인해 주세요."
_NO_QUARTER = "올해 분기 실적이 아직 없어요"
_REPORTS = ("11014", "11012", "11013")  # 3분기 누적, 반기 누적, 1분기
_LABELS = {"11014": "3분기 누적", "11012": "반기 누적", "11013": "1분기"}
_QUARTER = {"11014": 3, "11012": 2, "11013": 1}
_RECENT_TAIL = "계산기는 연간 실적만 봐서 아직 반영하지 못했어요."


@dataclass(frozen=True)
class Extras:
    disclosures: list[dict]
    news: list[dict]
    news_link: str
    quarterly: dict | None
    weekly_closes: list[tuple[str, float]]
    notes: tuple[str, ...]
    recent: dict | None = None    # 최근 4분기 EPS로 본 5-4 표 한 줄 (참고, 판정은 안 바꿔요)


def _eok(v: float | None) -> float | None:
    return None if v is None else excel_round(v / 1e8, 2)


def quarterly_summary(fin: FinRows, year: int, report: str) -> dict:
    cur, prev = ("thstrm", "frmtrm_q") if report == "11013" else ("thstrm_add", "frmtrm_add")
    now, before = extract(fin, cur), extract(fin, prev)

    def pick(a: dict, field: str) -> float | None:
        v = a[field].value
        if field == "net_income_parent" and v is None:
            v = a["profit_loss"].value
        return _eok(v)

    return {"label": f"{year}년 {_LABELS[report]}",
            "net_income": pick(now, "net_income_parent"),
            "net_income_prev": pick(before, "net_income_parent"),
            "op_income": pick(now, "operating_income"),
            "op_income_prev": pick(before, "operating_income"),
            "eps": now["eps"].value, "eps_prev": before["eps"].value,   # 누적 EPS (원)
            "year": year, "quarter": _QUARTER[report]}


def recent_row(q: dict | None, *, latest_year: int | None, latest_eps, b118, price,
               safety_margin: float, gate3: str | None) -> dict | None:
    """최근 4분기 EPS = 최근 해 EPS + 올해 누적 EPS − 작년 같은 때 누적 EPS. 5-4 표와 같은 식으로 매수선을 구해요.

    연간 보고서 바로 다음 해의 분기 보고서일 때만 이어 붙여요. 관문 ③을 통과했는데
    이 기준으로는 '싸요'가 아니면 경고 문장을 붙여요."""
    if q is None or latest_year is None or q.get("year") != latest_year + 1:
        return None
    parts = (latest_eps, q.get("eps"), q.get("eps_prev"), b118, price)
    if not all(isinstance(x, (int, float)) for x in parts):
        return None
    eps = latest_eps + q["eps"] - q["eps_prev"]
    fair, buy, ratio, verdict = eps_scenario(eps, b118, price, safety_margin)
    n = q["quarter"]
    label = f"최근 4분기 ({latest_year}년 {n + 1}분기~{q['year']}년 {n}분기)"
    warning = None
    if gate3 == "통과" and verdict != "싸요":
        warning = (f"최근 4분기 EPS가 −{-eps:,.0f}원(적자)이라 이 기준으로는 매수선이 없어요. {_RECENT_TAIL}"
                   if eps <= 0 else
                   f"최근 4분기 EPS {eps:,.0f}원으로 보면 매수선이 {buy:,.0f}원이라 "
                   f"지금 주가 {price:,.0f}원보다 낮아요. {_RECENT_TAIL}")
    return {"label": label, "eps": eps, "fair": fair, "buy_line": buy, "ratio": ratio,
            "verdict": verdict, "warning": warning}


def _disclosures(dart, corp: str, today: date) -> list[dict]:
    rows = dart.filings(today - timedelta(days=90), today, detail_type=None, corp_code=corp)
    rows = sorted(rows, key=lambda r: (r.get("rcept_dt", ""), r.get("rcept_no", "")), reverse=True)[:10]
    out = []
    for r in rows:
        d = r.get("rcept_dt", "")
        out.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d,
                    "title": r.get("report_nm", ""), "url": _DISCLOSURE_URL.format(r.get("rcept_no", ""))})
    return out


def _quarterly(dart, corp: str, year: int) -> dict | None:
    for report in _REPORTS:
        fin = dart.financials(corp, year, report)
        if fin:
            q = quarterly_summary(fin, year, report)
            return None if q["net_income"] is None and q["op_income"] is None else q
    return None


def gather_extras(codes, run: RunResult, dart, krx, naver: NaverNews | None,
                  today: date) -> dict[str, Extras]:
    price_date = run.collected.price_date
    closes_by_day: dict[date, dict] | None = None
    closes_error = False
    naver_key_bad = False
    out: dict[str, Extras] = {}
    for code in codes:
        result = run.results.get(code)
        if result is None:
            continue
        company = result.company
        notes: list[str] = []

        def note(text: str) -> None:
            if text not in notes:
                notes.append(text)

        def failed(e: Exception, text: str) -> None:
            note(_QUOTA_NOTE if isinstance(e, DartQuotaExceeded) else text)

        disclosures: list[dict] = []
        try:
            disclosures = _disclosures(dart, company.corp_code, today)
        except _CAUGHT as e:
            failed(e, "최근 공시를 가져오지 못했어요")

        latest_year = result.assembled.latest_year
        quarterly = None
        try:
            # 사업보고서 바로 다음 해의 분기 보고서. 1~3월엔 아직 지난해 3분기 누적이 가장 최근이에요.
            quarterly = _quarterly(dart, company.corp_code, latest_year + 1 if latest_year else today.year)
            if quarterly is None:
                note(_NO_QUARTER)
        except _CAUGHT as e:
            failed(e, "분기 실적을 가져오지 못했어요")

        if closes_by_day is None and not closes_error:
            try:
                closes_by_day = {d: krx.daily(d) for d in krx.week_ends(price_date, 52)}
            except _CAUGHT:
                closes_error = True
        closes: list[tuple[str, float]] = []
        if closes_error:
            note("주가 흐름을 가져오지 못했어요")
        else:
            for d in sorted(closes_by_day or {}):
                row = closes_by_day[d].get(code)
                if row is not None and row.close is not None:
                    closes.append((d.isoformat(), row.close))

        news: list[dict] = []
        if naver is not None and naver_key_bad:
            note(_NAVER_KEY_NOTE)
        elif naver is not None:
            try:
                news = naver.search(company.name)
            except NaverAuthError:                # ValueError의 하위라서 _CAUGHT보다 먼저 잡아요
                naver_key_bad = True              # 남은 종목은 네이버를 부르지 않아요
                note(_NAVER_KEY_NOTE)
            except _CAUGHT:
                note("뉴스를 가져오지 못했어요")

        cells = result.cells
        recent = recent_row(quarterly, latest_year=latest_year, latest_eps=cells.get("B123"),
                            b118=cells.get("B118"), price=result.assembled.inputs.price,
                            safety_margin=result.criteria.safety_margin, gate3=cells.get("D110"))
        out[code] = Extras(disclosures=disclosures, news=news,
                           news_link=_NEWS_LINK.format(quote(company.name)),
                           quarterly=quarterly, weekly_closes=closes, notes=tuple(notes), recent=recent)
    return out
