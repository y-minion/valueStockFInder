"""가장 최근 리포트(reports/<날짜>/data.js)에서 종목 카드 하나를 읽어, 자문에 필요한 숫자를 기준일과 함께 보여줘요.

사용 (프로젝트 폴더에서):
    uv run python .claude/skills/자문/scripts/card.py 004000
    uv run python .claude/skills/자문/scripts/card.py 004000 --eps 8293,4165,7696   # 정상 EPS 후보별 매수선
    uv run python .claude/skills/자문/scripts/card.py 004000 --report reports/2026-11-17

숫자는 프로그램이 만든 그대로예요. 여기서 다시 계산하는 건 --eps 시나리오뿐이고, 계산기 5-4 표와 같은 식을 써요.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from vsf.engine import eps_scenario

ROOT = Path.cwd()
CHECK = ("확인 필요", "입력 필요", "직접 확인", "탈락")


def latest_report() -> Path:
    dirs = sorted(p for p in (ROOT / "reports").glob("*") if (p / "data.js").is_file())
    if not dirs:
        sys.exit("리포트가 없어요. 먼저 `uv run run.py`로 주간 실행을 해요.")
    return dirs[-1]


def load(path: Path) -> dict:
    t = path.read_text(encoding="utf-8")
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def labels() -> dict[int, str]:
    js = (ROOT / "src/vsf/report/assets/report.js").read_text(encoding="utf-8")
    start = js.index("LABELS = {")
    body = js[start: js.index("};", start)]
    return {int(k): v for k, v in re.findall(r'(\d+): "([^"]+)"', body)}


def n(v, d: int = 0) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{d}f}"
    return str(v)


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def print_score(s: dict, data: dict) -> None:
    """점수(총점·등급·항목)와 점수에 없는 판단 네 가지. 예전 리포트(점수 없음)면 그렇게 말해요."""
    summ = data.get("score_summary")
    if summ is None or "score" not in s:
        print("\n## 점수\n이 리포트에는 점수가 없어요 (점수 순위 전 리포트). 새로 `uv run run.py`를 해요.")
        return
    sc = s["score"]
    print("\n## 점수")
    if sc is None:
        print("최근 해 배당 없음 — 점수 대상 아님")
    else:
        rank = data.get("score_rank") or []
        pos = f"{rank.index(s['code']) + 1}위 / {len(rank)}개" if s["code"] in rank else "순위 없음"
        prev = s.get("score_prev")
        change = "배점 바뀜" if summ.get("settings_changed") else ("—" if prev is None else f"{sc['total'] - prev:+g}")
        print(f"총점 {sc['total']:g} / 만점 {sc['max']:g} · 등급 {sc['grade']} · {pos} · 지난주 대비 {change}"
              f" · 자료 없는 배점 {sc['missing']:g}점")
        names = dict(summ.get("groups") or [])
        print("묶음: " + " · ".join(f"{names.get(k, k)} {v:g}" for k, v in sc["groups"].items()))
        print("항목 | 이 회사 | 구간 | 점수/배점 | 출처")
        for it in sc["items"]:
            got = "자료 없음" if it["status"] == "no_data" else f"{it['points']:g}/{it['max']:g}"
            print(f"- {it['label']} | {it['value']} | {it['rule']} | {got} | {it.get('source') or '—'}")
        missed = sorted((it for it in sc["items"] if it["max"] - it["points"] > 0), key=lambda it: it["points"] - it["max"])
        if missed:
            print("놓친 배점 큰 순: " + ", ".join(f"{it['label']} −{it['max'] - it['points']:g}" for it in missed))
    print("\n## 점수에 없는 판단 (자문에서 빠뜨리지 않아요; 평가표 배점은 참고)")
    for _key, q, choices, points in summ.get("judgment") or []:
        print(f"- {q}: " + " / ".join(f"{c}({p})" for c, p in zip(choices, points)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--eps", default="", help="쉼표로 구분한 정상 EPS 후보 (원)")
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args()

    rdir = a.report or latest_report()
    data = load(rdir / "data.js")
    s = data["stocks"].get(a.code)
    if s is None:
        sys.exit(f"{rdir.name} 리포트에 {a.code}가 없어요 (분석 제외·실패이거나 코드가 틀렸어요).")
    L, c, m, inp = labels(), s["cells"], s["summary"], s["inputs"]
    sm = (s.get("criteria") or {}).get("safety_margin", 0.25)

    print(f"## 리포트 {rdir.name} · 주가 기준일 {inp.get('price_date')} · 사업보고서 최근 연도 {s['latest_year']}")
    ind = (s.get("industry") or {}).get("group_name", "업종 정보 없음")
    print(f"{s['name']} ({s['code']}) · {s['market']} · {ind} · 상태 {s['state']}"
          f"{' (매수선 근처)' if s.get('near') else ''}")
    if s.get("share_class") == "우선":
        common = data["stocks"].get(s.get("common_code") or "", {})
        cp, liq = s.get("common_price"), s.get("liquidity")
        disc = f"{(1 - inp['price'] / cp) * 100:.0f}%" if cp else "—"
        print(f"우선주예요 · 보통주 {common.get('name', '')}({s.get('common_code')}) {n(cp)}원 · 보통주 대비 할인 {disc}"
              f" · 최근 해 DPS 우선주 {n(inp['years'][-1]['dps'])}원 / 보통주 {n(s.get('common_dps'))}원")
        if liq:
            print(f"거래대금 평균 {liq['avg'] / 1e8:.1f}억 원 (최근 {liq['days']}일){' · 거래 적음' if liq['thin'] else ''}")
        print("재무는 보통주와 같은 회사 숫자이고 주가·배당만 우선주 것이에요. "
              "배당은 그 우선주 종류의 줄(예: 2우선주)을 쓰고, 회사가 우선주 배당을 한 줄로만 적었으면 모든 우선주가 그 줄을 같이 써요.")
    if s.get("quick_fail"):
        print("빠른 탈락 종목이에요:", s["quick_fail"])
    print(f"관문 ① {c.get('D82')} · ② {c.get('D90')} · ③ {c.get('D110')} · ④ {c.get('D135')}")
    print(f"다음에 할 일: {m.get('next_step')}")
    print(f"주가 {n(m['price'])}원 · 보수적 적정가 {n(m['fair_value'])}원 ({m.get('method')}) · 매수선 {n(m['buy_line'])}원"
          f" · 주가÷적정가 {n(m['ratio'], 2)} · PBR {inp.get('pbr')} · 지금 배당수익률 {pct(m.get('yield_now'))}")
    if s["flags"]:
        print("숫자 확인 필요:", " / ".join(s["flags"]))
    if s["notes"]:
        print("메모:", " / ".join(s["notes"]))

    print_score(s, data)

    print("\n## 통과 못 한 칸 (관문 ①②)")
    rows = [r for r in range(70, 91) if c.get(f"D{r}") in CHECK]
    for r in rows:
        print(f"- {r}행 {L.get(r, '')}: 값 {n(c.get(f'B{r}'), 2)} · 기준 {c.get(f'C{r}') or '—'} · {c.get(f'D{r}')}")
    if not rows:
        print("- 없어요")

    print("\n## 계산에 쓴 값")
    for r, d in ((94, 0), (95, 0), (96, 0), (97, 2), (100, 0), (112, 0), (118, 2), (126, 0)):
        print(f"- {r}행 {L.get(r, '')}: {n(c.get(f'B{r}'), d)}")
    for r in (98, 99):
        print(f"- {r}행 {L.get(r, '')}: {pct(c.get(f'B{r}'))}")
    print(f"- 적정가 A {n(c.get('B102'))} · B {n(c.get('B103'))} · C {n(c.get('B104'))}")

    print("\n## 5-4 정상 EPS 가정 표 (정상 EPS → 적정가 → 매수선 → 주가÷적정가 → 판단)")
    for r in range(120, 127):
        print(f"- {L.get(r, r)}: {n(c.get(f'B{r}'))} → {n(c.get(f'C{r}'))} → {n(c.get(f'D{r}'))}"
              f" → {n(c.get(f'E{r}'), 2)} → {c.get(f'F{r}') or '—'}")
    e = s.get("extras") or {}
    rec = e.get("recent")
    if rec:
        print(f"- {rec['label']}: {n(rec['eps'])} → {n(rec['fair'])} → {n(rec['buy_line'])}"
              f" → {n(rec['ratio'], 2)} → {rec['verdict'] or '—'}")
        if rec.get("warning"):
            print(f"  경고: {rec['warning']}")
    elif e:
        print("- 최근 4분기 줄 없음 (분기 EPS를 못 받았거나 연도가 이어지지 않아요) → dart_pull.py로 직접 계산해요")

    if a.eps:
        print(f"\n## 정상 EPS 후보별 (보수적 배수 {n(c.get('B118'), 2)}, 안전마진 {sm:.0%}, 주가 {n(m['price'])}원)")
        for x in (float(v) for v in a.eps.split(",") if v.strip()):
            fair, buy, ratio, verdict = eps_scenario(x, c.get("B118"), m["price"], sm)
            print(f"- 정상 EPS {n(x)} → 적정가 {n(fair)} → 매수선 {n(buy)} → 주가÷적정가 {n(ratio, 2)} → {verdict or '—'}")

    print("\n## 5년 입력 (억 원·원·%)")
    print("연도 | EPS | PER | DPS | ROE | 부채비율 | 이자보상 | 순이익 | 영업CF | 설비투자 | 배당지급")
    for y in inp["years"]:
        print(" | ".join([str(y["year"]), n(y["eps"]), n(y["per"], 2), n(y["dps"]), n(y["roe"], 1), n(y["debt_ratio"], 1),
                          n(y["interest_coverage"], 1), n(y["net_income"]), n(y["ocf"]), n(y["capex"]),
                          n(y["dividends_paid"])]))
    print("그 전 5년 DPS:", ", ".join(f"{yr} {n(v)}" for yr, v in zip(inp.get("prior_years") or [], inp.get("prior_dps") or [])))

    if not e:
        print("\n관심 목록 밖이라 공시·뉴스·분기 실적·주가 흐름을 받지 않았어요 → dart_pull.py로 받아요.")
    else:
        q = e.get("quarterly")
        print("\n## 분기 실적 (억 원, EPS는 원)")
        if q:
            print(f"{q['label']}: 순이익 {q['net_income']} (작년 같은 때 {q['net_income_prev']}) · "
                  f"영업이익 {q['op_income']} ({q['op_income_prev']}) · 누적 EPS {n(q.get('eps'))} ({n(q.get('eps_prev'))})")
        else:
            print("없어요")
        w = e.get("weekly_closes") or []
        if w:
            hi, lo = max(w, key=lambda z: z[1]), min(w, key=lambda z: z[1])
            print(f"\n## 주가 흐름 (주간 종가 {len(w)}개)")
            print(f"처음 {w[0][0]} {n(w[0][1])} · 고점 {hi[0]} {n(hi[1])} · 저점 {lo[0]} {n(lo[1])} · 끝 {w[-1][0]} {n(w[-1][1])}"
                  f" · 고점 대비 {(w[-1][1] / hi[1] - 1) * 100:+.0f}%")
            print("최근 8주:", ", ".join(f"{d[5:]} {n(v)}" for d, v in w[-8:]))
        print("\n## 최근 공시 (90일)")
        for d in e.get("disclosures") or []:
            print(f"- {d['date']} {d['title'].strip()} {d['url']}")
        print("\n## 뉴스")
        for d in e.get("news") or []:
            print(f"- {d['date']} {d['title']} {d['url']}")
        for t in e.get("notes") or []:
            print("자료 메모:", t)

    memos = sorted((ROOT / "data/memos").glob(f"*_{a.code}*.md"))
    print("\n## 이전 자문 메모")
    print("\n".join(f"- {p}" for p in memos) if memos else "- 없어요 (처음이에요)")


if __name__ == "__main__":
    main()
