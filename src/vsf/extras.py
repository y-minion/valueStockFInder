"""관문 ④ 판단 자료: 관심 목록 종목의 최근 공시·뉴스·올해 분기 실적·주가 흐름."""
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

from vsf.data.accounts import extract
from vsf.data.dart import DartError, DartQuotaExceeded, FinRows
from vsf.data.http import NetworkError
from vsf.data.krx import KrxError
from vsf.data.naver import NaverAuthError, NaverNews
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


@dataclass(frozen=True)
class Extras:
    disclosures: list[dict]
    news: list[dict]
    news_link: str
    quarterly: dict | None
    weekly_closes: list[tuple[str, float]]
    notes: tuple[str, ...]


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
            "op_income_prev": pick(before, "operating_income")}


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

        quarterly = None
        try:
            quarterly = _quarterly(dart, company.corp_code, today.year)
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

        out[code] = Extras(disclosures=disclosures, news=news,
                           news_link=_NEWS_LINK.format(quote(company.name)),
                           quarterly=quarterly, weekly_closes=closes, notes=tuple(notes))
    return out
