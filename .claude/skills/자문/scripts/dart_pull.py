"""DART 공식 API로 자문 자료를 한 번에 받아 JSON 파일로 저장하고 요약을 보여줘요.
키는 keys.toml에서 읽고 화면이나 파일에 쓰지 않아요.

사용 (프로젝트 폴더에서):
    uv run python .claude/skills/자문/scripts/dart_pull.py 004000 <스크래치 폴더>/dart_004000.json
    uv run python .claude/skills/자문/scripts/dart_pull.py 004000 out.json --year 2026   # 분기 보고서 연도 지정

받는 것: 회사 개요, 올해(사업보고서 다음 해) 분기 보고서 셋과 작년 같은 분기 보고서, 최근 1년 공시 목록,
임원·주요주주 지분 보고, 최대주주 현황, 자기주식, 배당, 타법인 출자.
"""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from vsf.config import load_keys
from vsf.data.accounts import extract
from vsf.data.dart import DartClient
from vsf.data.store import Store

ROOT = Path.cwd()
QUARTERS = (("11014", "3분기 누적"), ("11012", "반기 누적"), ("11013", "1분기"))


def latest_annual_year(code: str) -> int | None:
    dirs = sorted(p for p in (ROOT / "reports").glob("*") if (p / "data.js").is_file())
    if not dirs:
        return None
    t = (dirs[-1] / "data.js").read_text(encoding="utf-8")
    s = json.loads(t[t.index("{"): t.rindex("}") + 1])["stocks"].get(code)
    return s["latest_year"] if s else None


def revenue(fin, period: str) -> float | None:
    for r in fin.rows:
        if r.get("sj_div") in ("IS", "CIS") and (r.get("account_id") == "ifrs-full_Revenue"
                                                 or r.get("account_nm", "").replace(" ", "") in ("매출액", "수익(매출액)", "영업수익")):
            v = (r.get(f"{period}_amount") or "").replace(",", "")
            try:
                return float(v)
            except ValueError:
                continue
    return None


def eok(v) -> str:
    return "—" if v is None else f"{v / 1e8:,.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("out", type=Path)
    ap.add_argument("--year", type=int, default=None)
    a = ap.parse_args()

    keys = load_keys(ROOT / "keys.toml")
    dart = DartClient(keys.dart, Store(ROOT / "data/vsf.sqlite3"))
    corp = dart.corp_codes().get(a.code)
    if corp is None:
        raise SystemExit(f"DART 회사 목록에 {a.code}가 없어요.")
    annual = latest_annual_year(a.code)
    year = a.year or (annual + 1 if annual else date.today().year)
    today = date.today()

    out: dict = {"code": a.code, "corp_code": corp, "quarter_year": year, "company": dart.company(corp)}
    latest_q = None
    for rep, label in QUARTERS:
        now = dart.financials(corp, year, rep)
        before = dart.financials(corp, year - 1, rep)
        out[f"fin_{year}_{rep}"] = {"fs": now.fs, "rcept_no": now.rcept_no, "rows": now.rows} if now else None
        out[f"fin_{year - 1}_{rep}"] = {"fs": before.fs, "rcept_no": before.rcept_no, "rows": before.rows} if before else None
        if now and latest_q is None:
            latest_q = (rep, label, now)
    out["filings"] = dart.filings(today - timedelta(days=365), today, detail_type=None, corp_code=corp)
    q_rep = latest_q[0] if latest_q else "11014"
    q_year = str(year if latest_q else year - 1)
    for api, params in (("elestock.json", {}),
                        ("hyslrSttus.json", {"bsns_year": str(annual or year - 1), "reprt_code": "11011"}),
                        ("tesstkAcqsDspsSttus.json", {"bsns_year": q_year, "reprt_code": q_rep}),
                        ("alotMatter.json", {"bsns_year": q_year, "reprt_code": q_rep}),
                        ("otrCprInvstmntSttus.json", {"bsns_year": q_year, "reprt_code": q_rep})):
        out[api] = dart._json(api, corp_code=corp, **params)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(f"저장: {a.out}")
    print(f"{(out['company'] or {}).get('corp_name')} · 회사번호 {corp} · 분기 보고서 연도 {year} (사업보고서 최근 연도 {annual})")
    if latest_q:
        rep, label, fin = latest_q
        cur, prev = ("thstrm", "frmtrm_q") if rep == "11013" else ("thstrm_add", "frmtrm_add")
        x, y = extract(fin, cur), extract(fin, prev)
        print(f"\n## {year}년 {label} (억 원, EPS 원) — 접수번호 {fin.rcept_no} ({fin.fs})")
        print(f"매출 {eok(revenue(fin, cur))} (작년 같은 때 {eok(revenue(fin, prev))})")
        for k, nm in (("operating_income", "영업이익"), ("net_income_parent", "지배주주 순이익")):
            print(f"{nm} {eok(x[k].value)} ({eok(y[k].value)})")
        print(f"누적 EPS {x['eps'].value} ({y['eps'].value})")
        if rep != "11013":
            q, qp = extract(fin, "thstrm"), extract(fin, "frmtrm_q")
            print(f"이번 분기만: 영업이익 {eok(q['operating_income'].value)} ({eok(qp['operating_income'].value)})"
                  f" · 지배주주 순이익 {eok(q['net_income_parent'].value)} ({eok(qp['net_income_parent'].value)})"
                  f" · EPS {q['eps'].value} ({qp['eps'].value})")
    else:
        print(f"{year}년 분기 보고서가 아직 없어요.")
    print("\n## 분기 보고서 접수번호 (원문은 doc_text.py로)")
    for rep, label in QUARTERS:
        for yr in (year, year - 1):
            f = out.get(f"fin_{yr}_{rep}")
            if f:
                print(f"- {yr}년 {label}: {f['rcept_no']}")
    print(f"\n## 최근 1년 공시 {len(out['filings'])}건 (최근 순 20건)")
    for r in sorted(out["filings"], key=lambda r: r.get("rcept_dt", ""), reverse=True)[:20]:
        print(f"- {r.get('rcept_dt')} {r.get('report_nm', '').strip()} ({r.get('flr_nm')}) {r.get('rcept_no')}")
    ele = (out.get("elestock.json") or {}).get("list") or []
    print(f"\n## 임원·주요주주 지분 보고 (최근 10건 / 전체 {len(ele)}건)")
    for r in sorted(ele, key=lambda r: r.get("rcept_dt", ""), reverse=True)[:10]:
        print(f"- {r.get('rcept_dt')} {r.get('repror')} ({r.get('isu_exctv_ofcps') or r.get('isu_main_shrholdr')}) "
              f"증감 {r.get('sp_stock_lmp_irds_cnt')}주 → 비율 {r.get('sp_stock_lmp_rate')}%")
    for api in ("hyslrSttus.json", "tesstkAcqsDspsSttus.json", "alotMatter.json", "otrCprInvstmntSttus.json"):
        d = out.get(api) or {}
        print(f"{api}: {len(d.get('list') or [])}줄 (상태 {d.get('status', '—')})")


if __name__ == "__main__":
    main()
