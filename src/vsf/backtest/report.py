"""백테스트 결과 페이지 (2026-11-24 백테스트 설계 6장). 외부 스크립트 없는 정적 HTML 한 장이에요.

그래프는 dataviz 스킬의 기본 팔레트 1~6번 칸을 순서대로 써요 (밝은·어두운 화면 모두 색약 검사 통과,
밝은 화면의 노랑·청록·분홍은 3:1 대비 아래라 표로도 같은 숫자를 보여줘요).
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from vsf.backtest.metrics import cash_share, max_drawdown, unit_values, xirr, yearly_returns
from vsf.backtest.simulate import FLAG_GATES, HOLDING, SimResult, Trade

MINUS = "−"
NOTES = (
    "비교 지수·ETF는 분배금(배당)이 빠진 가격이에요. 그래서 실제보다 낮게 나와요 (고배당 ETF는 연 4~5% 정도).",
    "계산기 쪽은 받은 배당을 넣어 계산했어요. 결산일에 들고 있던 주식 수 × 그해 DPS를 사업보고서 공시일에 받는다고 봤어요.",
    "관문 ④(사람의 판단)는 과거로 재현할 수 없어서 빠졌어요. 매수선 이하면 산다고 봤어요.",
    "정정된 사업보고서는 정정본 숫자를 써요. 공시일은 원본 공시일이에요.",
    "소수점 주식을 허용했어요. 실제로는 1주 단위라 비싼 종목은 조금 다를 수 있어요.",
    "살 때와 팔 때 각각 0.25%를 비용으로 뺐어요. ISA라 세금은 빼지 않았어요.",
)


@dataclass(frozen=True)
class Row:
    label: str
    kind: str                  # "규칙" | "비교"
    result: SimResult
    invested: float
    final: float
    xirr: float | None
    mdd: tuple[float, date | None]
    yearly: dict[int, float]
    cash_share: float


def money(x: float | None) -> str:
    """135,200,000 → "1억 3,520만 원", 52,000,000 → "5,200만 원", 9,500 → "9,500원"."""
    if x is None:
        return "—"
    sign = MINUS if x < 0 else ""
    x = abs(x)
    if x >= 1e8:
        eok, man = divmod(round(x / 1e4), 10_000)
        return f"{sign}{eok:,}억 {man:,}만 원" if man else f"{sign}{eok:,}억 원"
    if x >= 1e4:
        return f"{sign}{round(x / 1e4):,}만 원"
    return f"{sign}{x:,.0f}원"


def annual(r: float | None) -> str:
    return "—" if r is None else f"연 {r * 100:.1f}%".replace("-", MINUS)


def signed(r: float | None) -> str:
    if r is None:
        return "—"
    return f"{'+' if r >= 0 else MINUS}{abs(r) * 100:.1f}%"


def _deposits_by_day(result: SimResult) -> list[float]:
    by_day: dict[date, float] = {}
    for d, amount in result.deposits:
        by_day[d] = by_day.get(d, 0.0) + amount
    return [by_day.get(d, 0.0) for d in result.days]


def units_of(result: SimResult) -> list[float]:
    return unit_values(result.value, _deposits_by_day(result))


def summarize_row(label: str, kind: str, result: SimResult) -> Row:
    invested = sum(a for _, a in result.deposits)
    final = result.value[-1] if result.value else 0.0
    flows = [(d, -a) for d, a in result.deposits] + ([(result.days[-1], final)] if result.days else [])
    units = units_of(result)
    return Row(label=label, kind=kind, result=result, invested=invested, final=final, xirr=xirr(flows),
               mdd=max_drawdown(result.days, units), yearly=yearly_returns(result.days, units),
               cash_share=cash_share(result.value, result.cash))


# ---- 조각 ----

def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _summary_table(rows: list[Row]) -> str:
    head = "<tr><th>이름</th><th>넣은 돈</th><th>마지막 평가액</th><th>연평균 수익률</th><th>가장 크게 빠졌던 때</th><th>CMA 평균 비중</th></tr>"
    body = []
    for r in rows:
        worst, day = r.mdd
        mdd = f"{signed(worst)} ({day.isoformat()})" if day else "없음"
        tag = "" if r.kind == "규칙" else ' class="bench"'
        body.append(f"<tr{tag}><td>{_e(r.label)}</td><td class=n>{money(r.invested)}</td><td class=n>{money(r.final)}</td>"
                    f"<td class=n>{annual(r.xirr)}</td><td class=n>{mdd}</td><td class=n>{r.cash_share * 100:.0f}%</td></tr>")
    return f'<table class="summary">{head}{"".join(body)}</table>'


def _yearly_table(rows: list[Row]) -> str:
    years = sorted({y for r in rows for y in r.yearly})
    head = "<tr><th>해</th>" + "".join(f"<th>{_e(r.label)}</th>" for r in rows) + "</tr>"
    body = "".join("<tr><td>" + str(y) + "</td>" + "".join(f"<td class=n>{signed(r.yearly.get(y))}</td>" for r in rows)
                   + "</tr>" for y in years)
    return f'<div class="wide"><table>{head}{body}</table></div>'


def _months(a: date, b: date) -> str:
    return f"{max((b - a).days, 0) / 30.44:.0f}개월"


def _trade_rows(trades: list[Trade], end: date) -> str:
    out = []
    for t in sorted(trades, key=lambda t: (t.first_buy, t.code)):
        sold = t.reason != HOLDING
        ret = signed((t.proceeds + t.dividends) / t.invested - 1) if sold and t.proceeds is not None and t.invested else "—"
        sell = f"{t.sell_date.isoformat()} · {t.sell_price:,.0f}원" if sold and t.sell_date and t.sell_price else "—"
        flags = "<br>".join(_e(f) for f in t.flags) or ""
        out.append(f"<tr><td>{_e(t.name)} <span class=muted>{_e(t.code)}</span></td><td>{t.first_buy.isoformat()}</td>"
                   f"<td>{_e(t.basis)}</td><td class=n>{money(t.invested)}</td><td>{sell}</td><td>{_e(t.reason)}</td>"
                   f"<td class=n>{ret}</td><td class=n>{_months(t.first_buy, t.sell_date or end)}</td>"
                   f"<td class=n>{money(t.dividends)}</td><td class=flag>{flags}</td></tr>")
    head = ("<tr><th>종목</th><th>처음 산 날</th><th>산 날의 판정 근거</th><th>넣은 돈</th><th>판 날 · 값</th><th>판 이유</th>"
            "<th>수익률(배당 포함)</th><th>보유 기간</th><th>받은 배당</th><th>표시</th></tr>")
    return f'<div class="wide"><table class="trades">{head}{"".join(out)}</table></div>'


def _holdings(trades: list[Trade]) -> str:
    held = [t for t in trades if t.reason == HOLDING]
    if not held:
        return "<p>끝날 보유 종목이 없어요 (모두 CMA예요).</p>"
    items = "".join(f"<li>{_e(t.name)} ({_e(t.code)}) · {t.first_buy.isoformat()}부터 · 넣은 돈 {money(t.invested)}"
                    f"{' · <strong>' + _e(FLAG_GATES) + '</strong>' if FLAG_GATES in t.flags else ''}</li>" for t in held)
    return f"<ul>{items}</ul>"


SERIES = 6


def _chart(rows: list[Row]) -> str:
    """돈 넣은 시점을 뺀 수익 지수(시작 = 1). 선 2px, 범례 + 십자선 툴팁, 표로도 같은 숫자를 보여줘요."""
    rows = rows[:SERIES]
    if not rows or not rows[0].result.days:
        return ""
    days = rows[0].result.days
    picks = sorted(set(range(0, len(days), 5)) | {len(days) - 1})
    series = []
    for i, r in enumerate(rows, 1):
        u = units_of(r.result)
        series.append({"name": r.label, "slot": i, "v": [round(u[k], 4) for k in picks if k < len(u)]})
    data = {"d": [days[k].isoformat() for k in picks], "s": series}
    lo = min(min(s["v"]) for s in series)
    hi = max(max(s["v"]) for s in series)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    legend = "".join(f'<li><span class="key s{s["slot"]}"></span>{_e(s["name"])}</li>' for s in series)
    return f'''<figure class="chart">
<figcaption>수익 지수 — 돈을 넣은 시점을 빼고 본 오르내림 (시작 = 1, {days[0].isoformat()} ~ {days[-1].isoformat()})</figcaption>
<ul class="legend">{legend}</ul>
<div class="plot"><svg id="bt-chart" viewBox="0 0 760 300" role="img" aria-label="수익 지수 그래프 (아래 연도별 표에 같은 숫자가 있어요)"></svg>
<div class="tip" id="bt-tip" hidden></div></div>
<script type="application/json" id="bt-data">{blob}</script>
<script>
(function () {{
  var data = JSON.parse(document.getElementById("bt-data").textContent);
  var svg = document.getElementById("bt-chart"), tip = document.getElementById("bt-tip");
  var NS = "http://www.w3.org/2000/svg", L = 56, R = 744, T = 14, B = 272, n = data.d.length;
  var lo = {lo!r}, hi = {hi!r}, pad = (hi - lo) * 0.06 || 0.1; lo -= pad; hi += pad;
  function x(i) {{ return L + (R - L) * (n > 1 ? i / (n - 1) : 0); }}
  function y(v) {{ return B - (B - T) * (v - lo) / (hi - lo); }}
  function el(tag, at) {{ var e = document.createElementNS(NS, tag); for (var k in at) e.setAttribute(k, at[k]); svg.appendChild(e); return e; }}
  var step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 4))); if ((hi - lo) / step > 8) step *= 2; if ((hi - lo) / step > 8) step *= 2.5;
  for (var g = Math.ceil(lo / step) * step; g <= hi; g += step) {{
    el("line", {{x1: L, x2: R, y1: y(g), y2: y(g), "class": "grid"}});
    var t = el("text", {{x: L - 8, y: y(g) + 4, "text-anchor": "end", "class": "axis"}}); t.textContent = g.toFixed(step < 1 ? 1 : 0);
  }}
  var seen = {{}};
  data.d.forEach(function (d, i) {{ var yr = d.slice(0, 4); if (!seen[yr] && d.slice(5, 7) <= "01") {{ seen[yr] = 1;
    var t = el("text", {{x: x(i), y: B + 18, "text-anchor": "middle", "class": "axis"}}); t.textContent = yr; }} }});
  data.s.forEach(function (s) {{
    el("polyline", {{points: s.v.map(function (v, i) {{ return x(i).toFixed(1) + "," + y(v).toFixed(1); }}).join(" "), "class": "line s" + s.slot}});
  }});
  var cross = el("line", {{y1: T, y2: B, "class": "cross", visibility: "hidden"}});
  var hit = el("rect", {{x: L, y: T, width: R - L, height: B - T, fill: "transparent"}});
  function show(ev) {{
    var box = svg.getBoundingClientRect(), px = (ev.clientX - box.left) * 760 / box.width;
    var i = Math.max(0, Math.min(n - 1, Math.round((px - L) / (R - L) * (n - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    tip.textContent = ""; var h = document.createElement("strong"); h.textContent = data.d[i]; tip.appendChild(h);
    data.s.forEach(function (s) {{ var line = document.createElement("div"); var k = document.createElement("span");
      k.className = "key s" + s.slot; line.appendChild(k); line.appendChild(document.createTextNode(s.name + " " + s.v[i].toFixed(2)));
      tip.appendChild(line); }});
    tip.hidden = false; var left = (ev.clientX - box.left) + 14; if (left > box.width - 240) left -= 268; tip.style.left = left + "px";
  }}
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerleave", function () {{ tip.hidden = true; cross.setAttribute("visibility", "hidden"); }});
}})();
</script>
</figure>'''


CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7974;--line:#e4e3df;--grid:#ecebe7;--bench:#f4f3ef;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#9a998f;--line:#3a3935;--grid:#2c2b28;--bench:#232320;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;
--series-5:#d55181;--series-6:#0ca30c}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#3a3935;--grid:#2c2b28;
--bench:#232320;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#0ca30c}
body{margin:0;background:var(--surface);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 10px}p.sub{color:var(--ink2);margin:0 0 8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.bench td{background:var(--bench)}.muted{color:var(--muted)}td.flag{color:var(--ink2);font-size:13px}
.wide{overflow-x:auto}.trades td{font-size:13px}
.chart{margin:8px 0 0}.chart figcaption{color:var(--ink2);margin-bottom:6px}
.legend{list-style:none;padding:0;margin:0 0 8px;display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink2)}
.key{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
.plot{position:relative}svg{width:100%;height:auto;display:block}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.grid{stroke:var(--grid);stroke-width:1}.cross{stroke:var(--muted);stroke-width:1}.axis{fill:var(--muted);font-size:11px}
.tip{position:absolute;top:8px;min-width:200px;max-width:260px;background:var(--surface);border:1px solid var(--line);border-radius:6px;
padding:8px 10px;font-size:12px;color:var(--ink);pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,.12)}
""" + "".join(f".s{i}{{stroke:var(--series-{i})}}span.key.s{i}{{background:var(--series-{i})}}" for i in range(1, SERIES + 1))


def write_backtest_report(main: list[Row], second: list[Row], meta: dict, out_dir: Path, today: date) -> Path:
    """reports/backtest/<오늘>/index.html을 써요."""
    start, end = meta.get("start"), meta.get("end")
    rules = [r for r in main if r.kind == "규칙"]
    parts = [f"<h1>계산기 백테스트</h1><p class=sub>{_e(start)} ~ {_e(end)} · 매달 첫 거래일에 130만 원 · 매수선 이하인 종목을 "
             "싼 순서로 최대 5개 · 보수적 적정가에 닿으면 팔고 다른 싼 종목으로 갈아타요 · 살 게 없으면 CMA</p>"
             f"<p class=sub>만든 날 {today.isoformat()}</p>",
             "<h2>한눈에</h2>", _summary_table(main)]
    if second:
        parts += [f"<h2>{_e(meta.get('second_start'))}부터 같은 기간 (환노출 S&amp;P500 비교)</h2>", _summary_table(second)]
    parts += ["<h2>오르내림</h2>", _chart(main), "<h2>해마다 수익률 (돈 넣은 시점을 뺀 수익률)</h2>", _yearly_table(main)]
    for r in rules:
        parts += [f"<h2>{_e(r.label)} · 거래 목록</h2>", _trade_rows(r.result.trades, end or today),
                  f"<h2>{_e(r.label)} · 끝날 보유 종목</h2>", _holdings(r.result.trades)]
    failures = meta.get("failures") or {}
    fail_text = " · ".join(f"{_e(k)} {v:,}개" for k, v in sorted(failures.items(), key=lambda kv: -kv[1])) or "없음"
    parts += ["<h2>자료 안내</h2><ul>",
              f"<li>판정 묶음 {meta.get('vintages', 0):,}개 (그중 금융회사 대체 자료 {meta.get('substitutes', 0):,}개)</li>",
              f"<li>못 만든 묶음: {fail_text}</li>"]
    parts += [f"<li>{_e(n)}</li>" for n in NOTES] + ["</ul>"]
    page = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>계산기 백테스트</title><style>{CSS}</style></head><body><main>{"".join(parts)}</main>'
            "</body></html>")
    path = out_dir / "backtest" / today.isoformat() / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
