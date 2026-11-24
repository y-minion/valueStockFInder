"""사업보고서 원본 공시일 (2026-11-24 백테스트 설계 4장).

판정 묶음은 그 사업보고서가 처음 공시된 날부터 써요. 나중에 정정된 보고서는 DART 자료의 접수번호가
정정일로 바뀌어 있어서, 공시 목록에서 원본·정정 가운데 가장 이른 접수일을 찾아요.
"""
import re
from datetime import date

from vsf.data.store import Store

_ANNUAL = re.compile(r"사업보고서\s*\((\d{4})\.(\d{2})\)")


def _cache_key(year: int) -> str:
    return f"bt:filings:A001:{year}"


def _rows_of_year(dart, store: Store, year: int, today: date) -> list[dict]:
    """그해(공시한 해) 사업보고서 공시 목록. 끝난 해는 저장해 두고 다시 써요."""
    done = year < today.year
    if done:
        cached = store.get_json(_cache_key(year))
        if cached is not None:
            return list(cached)  # type: ignore[arg-type]
    end = date(year, 12, 31) if done else today
    rows = [{"corp_code": r.get("corp_code"), "report_nm": r.get("report_nm"), "rcept_dt": r.get("rcept_dt")}
            for r in dart.filings(date(year, 1, 1), end, "A001")]
    if done:
        store.put_json(_cache_key(year), rows)
    return rows


def annual_filing_dates(dart, store: Store, filing_years: range, today: date) -> dict[tuple[str, int], date]:
    """(corp_code, 사업연도) → 그 사업보고서의 가장 이른 접수일(원본·정정 중 가장 이른 날).

    결산월이 12월인 보고서('사업보고서 (YYYY.12)')만 써요. 다른 결산월은 DART 사업연도 표기와 맞춰 볼
    방법이 확실하지 않아서 v1에서는 묶음을 만들지 않아요 (플랜 Task 3 결정).
    """
    out: dict[tuple[str, int], date] = {}
    for year in filing_years:
        for r in _rows_of_year(dart, store, year, today):
            m = _ANNUAL.search(str(r.get("report_nm") or ""))
            ymd = str(r.get("rcept_dt") or "")
            corp = str(r.get("corp_code") or "")
            if not m or m.group(2) != "12" or not corp or len(ymd) != 8 or not ymd.isdigit():
                continue
            filed = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
            key = (corp, int(m.group(1)))
            if key not in out or filed < out[key]:
                out[key] = filed
    return out
