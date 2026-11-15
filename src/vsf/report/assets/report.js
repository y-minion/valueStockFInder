/* 주간 배당주 리포트 화면. 일반 <script>로 불러요 (file://에서 ES 모듈은 막혀요). */

// ---- 엑셀 계산기 '분석_빈칸' 시트의 A열 행 이름 ----
var LABELS = {
  26: "연도", 27: "EPS (원)", 28: "연말 PER (배)", 29: "주당배당금 DPS (원)", 30: "ROE (%)", 31: "부채비율 (%)",
  32: "이자보상배율 (배)", 33: "지배주주 순이익 (억 원)", 34: "영업활동현금흐름 (억 원)",
  35: "설비투자: 유형자산의 취득 (억 원)", 36: "배당금 지급 총액 (억 원, 선택)", 37: "평균에서 뺄 해 (선택, X)",
  38: "배당 계산에서만 뺄 해 (선택, X)", 41: "연도", 42: "주당배당금 DPS (원)", 43: "배당 증감률 (자동)",
  46: "연도", 47: "연말 주가 추정 (원)", 48: "배당수익률", 49: "배당성향", 50: "배당 증감률 (전년 대비)",
  51: "잉여현금흐름 (억 원)", 52: "배당 총액 (억 원)", 53: "이 해는 정상인가", 54: "배당 평균에 넣나",
  55: "정상 EPS (그래프용)",
  78: "ROE 5년 평균", 79: "부채비율 (최근 해)", 80: "이자보상배율 (최근 해)", 81: "영업현금흐름 ÷ 순이익 (5년 합계)",
  82: "관문 ① 결과", 86: "배당을 거른 해 (입력한 기간)", 87: "배당을 줄인 해 (입력한 기간)", 88: "배당성향 평균",
  89: "잉여현금흐름 ÷ 배당 총액 (5년 합계)", 90: "관문 ② 결과",
  94: "정상 EPS (5년 평균, 원)", 95: "정상 EPS 직접 입력 (선택, 원)", 96: "계산에 쓰는 정상 EPS (원)",
  97: "평균 PER (정상인 해)", 98: "평균 배당수익률 (배당 평균에 넣은 해)", 99: "평균 배당성향 (배당 평균에 넣은 해)",
  100: "정상 DPS (원)",
  102: "A 이론 (정상 EPS ÷ 요구수익률)", 103: "B 과거 PER (정상 EPS × 평균 PER)",
  104: "C 과거 배당수익률 (정상 DPS ÷ 평균 배당수익률)", 105: "보수적 적정가 (A·B·C 중 가장 낮은 값)",
  106: "적정가를 정한 방법", 107: "매수선 (보수적 적정가 × (1 − 안전마진))", 108: "주가 ÷ 보수적 적정가",
  109: "매수선까지 필요한 하락률", 110: "관문 ③ 결과",
  112: "시장이 예상하는 정상 EPS (원)", 113: "내 정상 EPS 대비", 114: "지금 PER (최근 해 EPS 기준)",
  115: "지금 배당수익률 (최근 해 DPS 기준)", 116: "시장이 예상하는 ROE (PBR × 요구수익률)",
  117: "ROE 5년 평균 (비교용)", 118: "보수적 배수 (보수적 적정가 ÷ 정상 EPS)",
  120: "최근 5년 중 가장 나쁜 해", 121: "정상 EPS의 80%", 122: "계산에 쓴 정상 EPS", 123: "최근 해(F열)",
  124: "최근 5년 중 가장 좋은 해", 125: "내가 생각하는 정상 EPS (직접 입력)",
  126: "지금 주가가 매수선이 되려면 필요한 정상 EPS",
  130: "질문 1. 1~3년 안에 풀릴 문제인가", 131: "질문 2. 풀릴 때까지 버틸 체력(빚, 현금)이 있나",
  132: "질문 3. 그동안 배당이 유지될까", 135: "관문 ④ 결과"
};
var KIND_LABEL = { new_buy: "새로 매수선 이하", new_watch: "새로 관심 목록", above_buy: "매수선 위로", left: "관심 목록에서 빠짐" };
// 엑셀 C열에 수식이 아니라 글자로 적혀 있어서 payload의 cells에 없는 기준 글
var STATIC_CRIT = { C86: "0번", C87: "0번 (아니면 이유 확인)", C110: "주가 ≤ 매수선" };
var COLS = ["B", "C", "D", "E", "F"];
var NO_FIGURES = "이 종목은 이번 실행에서 분석되지 않았어요";

// ---- 작은 도구들 ----
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function isNum(v) { return typeof v === "number" && isFinite(v); }
function group(s) { return s.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
function decimals(v, d) {
  var t = v.toFixed(d), neg = t[0] === "-", p = (neg ? t.slice(1) : t).split(".");
  return (neg ? "-" : "") + group(p[0]) + (p[1] ? "." + p[1] : "");
}
// kind: won 원, d2 소수 둘째, pct 1자리 %, pct0 정수 %, raw 최대 소수 둘째, text 그대로
function fmt(v, kind) {
  if (v == null || v === "") return "—";
  if (typeof v === "string") return esc(v);
  if (!isNum(v)) return "—";
  switch (kind) {
    case "won": return decimals(Math.round(v), 0);
    case "d2": return decimals(v, 2);
    case "pct": return decimals(v * 100, 1) + "%";
    case "pct0": return Math.round(v * 100) + "%";
    default: return decimals(Math.round(v * 100) / 100, 2).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  }
}
function dateKo(iso) {
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? m[1] + "년 " + Number(m[2]) + "월 " + Number(m[3]) + "일" : esc(iso);
}
function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? esc(u) : ""; }
function link(url, text) {
  var u = safeUrl(url);
  return u ? '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + esc(text) + "</a>" : esc(text);
}
function wrap(table) { return '<div class="scroll">' + table + "</div>"; }
function chip(text, cls) { return '<span class="chip ' + (cls || "") + '">' + esc(text) + "</span>"; }
function badgeClass(v) {
  if (v === "통과") return "ok";
  if (v === "탈락") return "no";
  return "warn";
}
function badge(text, verdict, title) {
  return '<span class="pill ' + badgeClass(verdict) + '"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + esc(text) + "</span>";
}
function gateBadge(n, verdict) {
  var mark = ["①", "②", "③", "④"][n - 1];
  if (n === 4 && verdict === "입력 필요") return badge(mark + " 직접 판단 필요", verdict);
  return badge(mark + " " + (verdict == null || verdict === "" ? "—" : verdict), verdict);
}
function flagChip(s) { return s.flags && s.flags.length ? " " + chip("숫자 확인 필요", "flag") : ""; }
function stockLink(code, name) { return '<a href="stock.html#' + encodeURIComponent(code) + '">' + esc(name) + "</a>"; }

function searchStocks(data, query) {
  var q = String(query || "").trim().toLowerCase();
  if (!q) return [];
  var out = [];
  Object.keys(data.stocks || {}).forEach(function (code) {
    var s = data.stocks[code];
    if (String(s.name).toLowerCase().indexOf(q) >= 0 || String(code).toLowerCase().indexOf(q) === 0)
      out.push({ code: code, name: s.name });
  });
  out.sort(function (a, b) { return a.code < b.code ? -1 : a.code > b.code ? 1 : 0; });
  return out.slice(0, 20);
}

// ---- 그래프 (SVG) ----
function svgOpen(title, w, h) {
  return '<svg class="chart" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="' + esc(title) + '"><title>' + esc(title) + "</title>";
}
function barChart(title, items, line) {
  // items: [{label, value}], line: 같은 길이의 값 배열 (점선)
  var W = 320, H = 170, L = 8, T = 18, B = 26, n = items.length;
  var vals = items.map(function (i) { return i.value; }).concat(line || []).filter(isNum);
  if (!n || !vals.length) return "";
  var hi = Math.max.apply(null, vals.concat([0])), lo = Math.min.apply(null, vals.concat([0]));
  if (hi === lo) hi = lo + 1;
  var y = function (v) { return T + (hi - v) / (hi - lo) * (H - T - B); };
  var step = (W - 2 * L) / n, bw = step * 0.6, s = svgOpen(title, W, H);
  s += '<line class="axis" x1="' + L + '" x2="' + (W - L) + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
  items.forEach(function (it, i) {
    var x = L + i * step + (step - bw) / 2, cx = x + bw / 2;
    if (isNum(it.value)) {
      var y0 = y(0), y1 = y(it.value);
      s += '<rect class="bar" x="' + x.toFixed(1) + '" y="' + Math.min(y0, y1).toFixed(1) + '" width="' + bw.toFixed(1) +
        '" height="' + Math.max(Math.abs(y0 - y1), 1).toFixed(1) + '"/>';
      s += '<text class="val" x="' + cx.toFixed(1) + '" y="' + (Math.min(y0, y1) - 3).toFixed(1) + '">' + fmt(it.value, "won") + "</text>";
    }
    s += '<text class="lab" x="' + cx.toFixed(1) + '" y="' + (H - 8) + '">' + esc(it.label) + "</text>";
  });
  var pts = [];
  (line || []).forEach(function (v, i) { if (isNum(v)) pts.push((L + i * step + step / 2).toFixed(1) + "," + y(v).toFixed(1)); });
  if (pts.length > 1) s += '<polyline class="dash" points="' + pts.join(" ") + '"/>';
  else if (pts.length === 1) s += '<circle class="dot" cx="' + pts[0].split(",")[0] + '" cy="' + pts[0].split(",")[1] + '" r="3"/>';
  return s + "</svg>";
}
function epsChart(s) {
  var c = s.cells || {}, yrs = s.inputs.years || [];
  var items = COLS.map(function (col, i) {
    return { label: c[col + "46"] || (yrs[i] && yrs[i].year != null ? String(yrs[i].year) : ""), value: yrs[i] ? yrs[i].eps : null };
  });
  var normal = COLS.map(function (col) { return c[col + "55"]; });
  return barChart("EPS 막대와 정상 EPS 점선", items, normal);
}
function dpsChart(s) {
  var pairs = [], inp = s.inputs;
  (inp.prior_years || []).forEach(function (y, i) { if (y != null) pairs.push({ label: String(y), value: inp.prior_dps[i] }); });
  (inp.years || []).forEach(function (y) { if (y.year != null) pairs.push({ label: String(y.year), value: y.dps }); });
  pairs.sort(function (a, b) { return a.label < b.label ? -1 : 1; });
  return barChart("10년 주당배당금(DPS) 막대", pairs.slice(-10), null);
}
function lineChart(title, pts) {
  var W = 320, H = 150, L = 8, T = 14, B = 22, vals = pts.map(function (p) { return p[1]; }).filter(isNum);
  if (vals.length < 2) return "";
  var hi = Math.max.apply(null, vals), lo = Math.min.apply(null, vals);
  if (hi === lo) hi = lo + 1;
  var xs = (W - 2 * L) / (pts.length - 1), path = [];
  pts.forEach(function (p, i) {
    if (isNum(p[1])) path.push((L + i * xs).toFixed(1) + "," + (T + (hi - p[1]) / (hi - lo) * (H - T - B)).toFixed(1));
  });
  return svgOpen(title, W, H) + '<polyline class="line" points="' + path.join(" ") + '"/>' +
    '<text class="lab" x="' + L + '" y="' + (H - 6) + '" style="text-anchor:start">' + esc(pts[0][0]) + " " + fmt(pts[0][1], "won") + "</text>" +
    '<text class="lab" x="' + (W - L) + '" y="' + (H - 6) + '" style="text-anchor:end">' + esc(pts[pts.length - 1][0]) + " " + fmt(pts[pts.length - 1][1], "won") + "</text>" +
    '<text class="val" x="' + L + '" y="10" style="text-anchor:start">' + fmt(hi, "won") + " ~ " + fmt(lo, "won") + "</text></svg>";
}

// ---- 첫 페이지 ----
function banner(text, cls) { return '<div class="banner ' + (cls || "") + '">' + esc(text) + "</div>"; }
function tile(label, n, prev) {
  return '<div class="tile"><div class="muted">' + esc(label) + '</div><div class="big">' + fmt(n, "won") + "</div>" +
    (prev != null ? '<div class="muted">지난주 ' + fmt(prev, "won") + "</div>" : "") + "</div>";
}
function indexHead(data) {
  var r = data.run, n = 0;
  Object.keys(r.excluded || {}).forEach(function (k) { n += r.excluded[k].length; });
  return "<h1>주간 배당주 리포트</h1><p class=\"muted\">" + dateKo(r.date) + " 실행 · " + dateKo(r.price_date) + " 종가 기준 · 분석 " +
    fmt(r.analyzed, "won") + "개 / 상장 " + fmt(r.total_listed, "won") + "개 · 제외 " + fmt(n, "won") + "개</p>";
}
function banners(data) {
  var r = data.run, out = "";
  if (r.partial) out += banner("전체 " + fmt(r.total_listed, "won") + "개 중 " + fmt(r.analyzed, "won") + "개만 분석했어요. 내일 다시 실행하면 이어서 받아요.", "warn");
  var missing = r.year_end_missing || [];
  if (missing.length) out += banner("연말 주가를 가져오지 못한 해가 있어요: " + missing.join("·") + ". 이 해들의 PER이 비어 적정가 B·C 계산이 빠질 수 있어요.", "warn");
  (r.criteria_changes || []).forEach(function (c) {
    out += banner("지난 실행과 기준이 달라졌어요: " + c.label + " " + fmt(c.old, "raw") + " → " + fmt(c.new, "raw"), "warn");
  });
  if (r.first_run) out += banner("첫 실행이라 비교할 지난 결과가 없어요", "info");
  return out;
}
function tiles(data) {
  var s = data.summary, p = s.prev || {}, rep = (data.run.criteria || {}).report || {};
  var near = Math.round((rep.near_range == null ? 0.1 : rep.near_range) * 100);
  var watch = Math.round((rep.watch_range == null ? 0.2 : rep.watch_range) * 100);
  return '<div class="tiles">' + tile("매수선 이하", s.buy, p.buy) + tile("매수선까지 " + near + "% 이내", s.near, p.near) +
    tile("관심 목록 (" + watch + "% 이내)", s.watch, p.watch) + tile("①② 탈락 아님", s.gate12_ok, p.gate12_ok) + "</div>";
}
function changesTable(data) {
  var list = data.changes || [];
  var h = "<h2>이번 주 변화</h2>";
  if (!list.length) return h + '<p class="muted">' + (data.run.first_run ? "첫 실행이라 비교할 변화가 없어요." : "지난주와 달라진 종목이 없어요.") + "</p>";
  var rows = list.map(function (c) {
    var s = data.stocks[c.code];
    return "<tr><td>" + (s ? stockLink(c.code, c.name) : esc(c.name)) + (s ? flagChip(s) : "") + "</td><td>" + esc(KIND_LABEL[c.kind] || c.kind) +
      "</td><td>" + (c.causes || []).map(function (x) { return chip(x); }).join(" ") + "</td></tr>";
  }).join("");
  return h + wrap("<table><tr><th>종목</th><th>변화</th><th>원인</th></tr>" + rows + "</table>");
}
function watchTable(data) {
  var h = "<h2>관심 목록 (매수선에 가까운 순)</h2>", list = data.watchlist || [];
  if (!list.length) return h + '<p class="muted">지금 관심 목록에 든 종목이 없어요.</p>';
  var rows = list.map(function (code) {
    var s = data.stocks[code], m = s.summary, ind = s.industry;
    return "<tr><td>" + stockLink(code, s.name) + flagChip(s) + '<div class="muted">' + esc(ind ? ind.group_name : "업종 정보 없음") + "</div></td><td>" +
      gateBadge(1, m.gate1) + " " + gateBadge(2, m.gate2) + " " + gateBadge(3, m.gate3) + '</td><td class="num">' + fmt(m.ratio, "d2") +
      '</td><td class="num">' + fmt(m.drop == null ? null : Math.round(m.drop * 100) / 100, "pct0") + '</td><td class="num">' + fmt(m.yield_now, "pct") +
      "</td><td>" + fmt(m.method) + '</td><td class="num">' + (ind && isNum(ind.roe_rank_pct) ? "상위 " + fmt(ind.roe_rank_pct, "raw") + "%" : "—") +
      "</td><td>" + (s.flags.length ? esc(s.flags.join(" / ")) : "") + "</td></tr>";
  }).join("");
  return h + wrap("<table><tr><th>종목(업종)</th><th>관문</th><th>주가÷적정가</th><th>매수선까지</th><th>지금 배당수익률</th><th>적정가 방법</th><th>업종 ROE 순위</th><th>경고</th></tr>" + rows + "</table>");
}
function searchBox() {
  return '<h2>종목 찾기</h2><input id="q" type="search" placeholder="종목명이나 코드" autocomplete="off" aria-label="종목 검색"><ul id="results" class="results"></ul>';
}
function renderResults(data, q) {
  var res = searchStocks(data, q);
  if (!String(q || "").trim()) return "";
  if (!res.length) return '<li class="muted">찾는 종목이 없어요</li>';
  return res.map(function (x) { return "<li>" + stockLink(x.code, x.name) + ' <span class="muted">' + esc(x.code) + "</span></li>"; }).join("");
}
function skipLists(data) {
  var r = data.run, h = "<h2>제외·실패·대기</h2>";
  var ex = Object.keys(r.excluded || {}).map(function (why) {
    return "<h4>" + esc(why) + " (" + r.excluded[why].length + ")</h4><p>" + r.excluded[why].map(function (x) { return esc(x[1]) + " " + esc(x[0]); }).join(", ") + "</p>";
  }).join("");
  var fl = (r.failed || []).map(function (x) { return "<li>" + esc(x[1]) + " " + esc(x[0]) + " — " + esc(x[2]) + "</li>"; }).join("");
  var pe = (r.pending || []).map(function (x) { return esc(x[1]) + " " + esc(x[0]); }).join(", ");
  return h + "<details><summary>제외한 종목</summary>" + (ex || "<p>없어요</p>") + "</details>" +
    "<details><summary>받지 못한 종목 (" + (r.failed || []).length + ")</summary>" + (fl ? "<ul>" + fl + "</ul>" : "<p>없어요</p>") + "</details>" +
    "<details><summary>다음에 이어서 받을 종목 (" + (r.pending || []).length + ")</summary><p>" + (pe || "없어요") + "</p></details>";
}
function renderIndex(data) {
  return indexHead(data) + banners(data) + tiles(data) + changesTable(data) + watchTable(data) + searchBox() + skipLists(data);
}

// ---- 종목 카드 ----
function rowsTable(head, rows) {
  return wrap("<table><tr>" + head.map(function (x) { return "<th>" + esc(x) + "</th>"; }).join("") + "</tr>" + rows.join("") + "</table>");
}
function tr(cells) {
  return "<tr>" + cells.map(function (c, i) { return "<td" + (i && /^[\d—-]/.test(c) ? ' class="num"' : "") + ">" + c + "</td>"; }).join("") + "</tr>";
}
function verdictCell(v) { return v ? badge(String(v), v) : "—"; }
function gateTable(c, rows, resultRow) {
  var body = rows.map(function (g) {
    return tr([esc(LABELS[g[0]]), fmt(c["B" + g[0]], g[1]), fmt(c["C" + g[0]], g[1] === "pct" ? "pct" : "raw"), verdictCell(c["D" + g[0]])]);
  });
  body.push(tr(["<b>" + esc(LABELS[resultRow]) + "</b>", "", "", verdictCell(c["D" + resultRow])]));
  return rowsTable(["항목", "이 회사", "기준", "판정"], body);
}
function colTable(s, rows, headRow) {
  var c = s.cells, head = [""].concat(COLS.map(function (col, i) { return c[col + headRow] || (s.inputs.years[i] && s.inputs.years[i].year) || ""; }));
  return rowsTable(head, rows.map(function (r) {
    return tr([esc(LABELS[r[0]])].concat(COLS.map(function (col) { return fmt(c[col + r[0]], r[1]); })));
  }));
}
function inputTable(s) {
  var y = s.inputs.years || [], src = s.sources || {};
  var defs = [[27, "eps", "won"], [28, "per", "d2"], [29, "dps", "won"], [30, "roe", "raw"], [31, "debt_ratio", "raw"],
    [32, "interest_coverage", "d2"], [33, "net_income", "raw"], [34, "ocf", "raw"], [35, "capex", "raw"], [36, "dividends_paid", "raw"]];
  var head = [LABELS[26]].concat(y.map(function (v) { return v.year == null ? "—" : String(v.year); }));
  var rows = defs.map(function (d) {
    return "<tr><td>" + esc(LABELS[d[0]]) + "</td>" + COLS.map(function (col, i) {
      var t = src[col + d[0]];
      return '<td class="num"' + (t ? ' title="' + esc(t) + '"' : "") + ">" + fmt(y[i] ? y[i][d[1]] : null, d[2]) + "</td>";
    }).join("") + "</tr>";
  });
  [[37, "exclude_avg"], [38, "exclude_div"]].forEach(function (d) {
    rows.push("<tr><td>" + esc(LABELS[d[0]]) + "</td>" + y.map(function (v) { return '<td class="num">' + (v[d[1]] ? "X" : "") + "</td>"; }).join("") + "</tr>");
  });
  var inp = s.inputs;
  var prior = rowsTable(["그 이전 5년 (" + LABELS[42] + ")"].concat(inp.prior_years.map(function (v) { return v == null ? "—" : String(v); })),
    [tr([esc(LABELS[42])].concat(inp.prior_dps.map(function (v) { return fmt(v, "won"); })))]);
  return rowsTable(head, rows) + "<h4>1-1. 그 이전 5년 배당</h4>" + prior;
}
function sourceTable(s) {
  var keys = Object.keys(s.sources || {}).sort(), y = s.inputs.years || [];
  if (!keys.length) return "";
  var rows = keys.map(function (k) {
    var m = /^([B-F])(\d+)$/.exec(k), label = k;
    if (m) {
      var yr = y[COLS.indexOf(m[1])];
      label = k + " · " + (LABELS[m[2]] || "") + (yr && yr.year != null ? " · " + yr.year : "");
    }
    return tr([esc(label), esc(s.sources[k])]);
  });
  return "<h4>칸별 출처</h4>" + rowsTable(["칸", "출처"], rows);
}
function cardHead(s) {
  var chips = flagChip(s) + (s.criteria_overridden ? " " + chip("업종 기준 적용", "info") : "");
  return '<p><a href="index.html">← 첫 페이지</a></p><h1>' + esc(s.name) + " (" + esc(s.code) + ")" + chips + '</h1><p class="muted">' +
    esc(s.industry ? s.industry.group_name : "업종 정보 없음") + " · " + esc(s.market) + " · 최근 연도 " + esc(s.latest_year) + "</p>";
}
function noteList(notes) {
  return notes && notes.length ? '<div class="banner warn"><ul>' + notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul></div>" : "";
}
function flagList(s) {
  return s.flags.length ? '<div class="banner warn"><b>숫자 확인 필요</b><ul>' + s.flags.map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + "</ul></div>" : "";
}
function gateBadges(s) {
  var c = s.cells, m = s.summary;
  return '<div class="badges">' + gateBadge(1, c.D82 != null ? c.D82 : m.gate1) + " " + gateBadge(2, c.D90 != null ? c.D90 : m.gate2) + " " +
    gateBadge(3, c.D110 != null ? c.D110 : m.gate3) + " " + gateBadge(4, c.D135 != null ? c.D135 : m.gate4) + "</div>";
}
function priceBox(s) {
  var m = s.summary, c = s.cells, ratio = m.ratio, max = 1.5, sm = s.criteria && isNum(s.criteria.safety_margin) ? s.criteria.safety_margin : 0.25;
  var bar = isNum(ratio) ? '<div class="meter"><span style="width:' + Math.min(ratio / max, 1) * 100 + '%"></span><i style="left:' + (1 - sm) / max * 100 + '%"></i></div>' +
    '<div class="muted">파란 막대 = 주가÷적정가 ' + fmt(ratio, "d2") + " · 빨간 선 = 매수선 " + fmt(1 - sm, "d2") + "</div>" : "";
  return '<div class="box">현재가 <b>' + fmt(m.price, "won") + "원</b> · 보수적 적정가 <b>" + fmt(m.fair_value, "won") + "원</b> (" + fmt(m.method) +
    ") · 매수선 <b>" + fmt(m.buy_line, "won") + "원</b>" + (isNum(m.drop) ? " · 매수선까지 " + Math.round(m.drop * 100) + "%" : "") + bar +
    '<p class="next">' + fmt(c.B15) + "</p></div>";
}
function crit(c, row) { var k = "C" + row; return fmt(c[k] != null && c[k] !== "" ? c[k] : STATIC_CRIT[k]); }
function gate1Table(s, data) {
  var c = s.cells, body = [[78, "raw"], [79, "raw"], [80, "d2"], [81, "d2"]].map(function (g) {
    return tr([esc(LABELS[g[0]]), fmt(c["B" + g[0]], g[1]), crit(c, g[0]), verdictCell(c["D" + g[0]])]);
  });
  if (s.extra_gate1) {
    var ind = s.industry, pct = ((data.run.criteria || {}).industry || {}).roe_top_percent;
    body.push(tr(["업종 안 ROE 순위", ind && isNum(ind.roe_rank_pct) ? "상위 " + fmt(ind.roe_rank_pct, "raw") + "%" : "—",
      "상위 " + fmt(pct, "raw") + "% 이내", verdictCell(s.extra_gate1)]));
  }
  body.push(tr(["<b>" + esc(LABELS[82]) + "</b>", "", "", verdictCell(c.D82)]));
  return rowsTable(["항목", "이 회사", "기준", "판정"], body);
}
function gate2Table(s) {
  var c = s.cells, body = [[86, "raw"], [87, "raw"], [88, "pct"], [89, "d2"]].map(function (g) {
    return tr([esc(LABELS[g[0]]), fmt(c["B" + g[0]], g[1]), crit(c, g[0]), verdictCell(c["D" + g[0]])]);
  });
  body.push(tr(["<b>" + esc(LABELS[90]) + "</b>", "", "", verdictCell(c.D90)]));
  return rowsTable(["항목", "이 회사", "기준", "판정"], body);
}
function gate3Table(c) {
  return rowsTable(["항목", "이 회사", "기준", "판정"], [
    tr([esc(LABELS[108]), fmt(c.B108, "d2"), crit(c, 108), verdictCell(c.D110)]),
    tr(["<b>" + esc(LABELS[110]) + "</b>", "", crit(c, 110), verdictCell(c.D110)])]);
}
function kvTable(c, rows) {
  return rowsTable(["항목", "값"], rows.map(function (r) { return tr([esc(LABELS[r[0]]), fmt(c["B" + r[0]], r[1])]); }));
}
function fairTable(c) {
  var kinds = { 102: "won", 103: "won", 104: "won", 105: "won", 106: "text", 107: "won", 108: "d2", 109: "pct0" };
  return rowsTable(["적정가 세 가지와 매수선", "값"], Object.keys(kinds).map(function (r) { return tr([esc(LABELS[r]), fmt(c["B" + r], kinds[r])]); }));
}
function table54(c) {
  return rowsTable(["5-4. 정상 EPS 가정을 바꾸면", "정상 EPS", "적정가", "매수선", "주가÷적정가", "판단"], [120, 121, 122, 123, 124, 125, 126].map(function (r) {
    return tr([esc(LABELS[r]), fmt(c["B" + r], "won"), fmt(c["C" + r], "won"), fmt(c["D" + r], "won"), fmt(c["E" + r], "d2"), verdictCell(c["F" + r])]);
  }));
}
function industryBox(s) {
  var i = s.industry;
  if (!i) return "<p class=\"muted\">업종 정보가 없어요.</p>";
  return rowsTable(["업종 비교 (참고)", "값"], [
    tr(["업종", esc(i.group_name) + " (" + i.size + "개)"]),
    tr(["업종 ROE 중앙값 / 이 회사 순위", fmt(i.roe_median, "raw") + " / " + (isNum(i.roe_rank_pct) ? "상위 " + fmt(i.roe_rank_pct, "raw") + "%" : "—")]),
    tr(["업종 부채비율 중앙값 / 이 회사 순위", fmt(i.debt_median, "raw") + " / " + (isNum(i.debt_rank_pct) ? "상위 " + fmt(i.debt_rank_pct, "raw") + "%" : "—")])]);
}
function gate4Box(s) {
  var c = s.cells, e = s.extras;
  var qs = [130, 131, 132].map(function (r) {
    var ref = c["C" + r];
    return "<li>□ " + esc(LABELS[r]) + (ref ? '<div class="muted">' + esc(ref) + "</div>" : "") + "</li>";
  }).join("");
  var h = "<h3>관문 ④ 자료 (직접 판단)</h3>";
  if (!e) return h + '<p class="muted">이 종목의 공시·뉴스 자료는 받지 않았어요.</p><ul class="q">' + qs + "</ul>";
  var disc = (e.disclosures || []).map(function (d) { return "<li>" + esc(d.date) + " " + link(d.url, d.title) + "</li>"; }).join("");
  var news = (e.news || []).map(function (n) { return "<li>" + esc(n.date) + " " + link(n.url, n.title) + "</li>"; }).join("");
  var q = e.quarterly;
  return h + "<h4>최근 공시</h4>" + (disc ? "<ul>" + disc + "</ul>" : '<p class="muted">없어요</p>') +
    "<h4>뉴스</h4>" + (news ? "<ul>" + news + "</ul>" : '<p class="muted">받은 뉴스가 없어요</p>') +
    (e.news_link ? "<p>" + link(e.news_link, "네이버 뉴스에서 더 보기") + "</p>" : "") +
    "<h4>분기 실적 (억 원)</h4>" + (q ? rowsTable([q.label, "이번", "작년 같은 때"], [
      tr(["순이익", fmt(q.net_income, "raw"), fmt(q.net_income_prev, "raw")]), tr(["영업이익", fmt(q.op_income, "raw"), fmt(q.op_income_prev, "raw")])])
      : '<p class="muted">받은 분기 실적이 없어요</p>') +
    "<h4>세 가지 질문</h4><ul class=\"q\">" + qs + "</ul>" + noteList(e.notes);
}
function charts(s) {
  var out = '<div class="charts">' + epsChart(s) + dpsChart(s);
  var w = s.extras && s.extras.weekly_closes;
  if (w && w.length > 1) out += lineChart("주간 종가", w);
  return out + "</div>";
}
function quickFailCard(s) {
  var c = s.cells, y = s.inputs.years || [];
  var dps = rowsTable(["배당"].concat(y.map(function (v) { return v.year == null ? "—" : String(v.year); })),
    [tr([esc(LABELS[29])].concat(y.map(function (v) { return fmt(v.dps, "won"); })))]);
  return cardHead(s) + noteList(s.notes) + flagList(s) + '<div class="banner info">배당 확인에서 먼저 걸렸어요. 나머지 숫자는 받지 않았어요.</div>' +
    '<div class="badges">' + gateBadge(1, c.D82) + " " + gateBadge(2, c.D90) + "</div>" +
    "<h3>배당</h3>" + dps + "<h3>관문 ② 배당이 오래 갈까</h3>" + gate2Table(s) + '<p class="muted">엑셀로 보려면 <code>uv run run.py --excel ' + esc(s.code) + "</code></p>";
}
function renderStock(data, code) {
  var s = (data.stocks || {})[code];
  if (!s) return '<p><a href="index.html">← 첫 페이지</a></p><div class="banner warn">' + esc(NO_FIGURES) + "</div>";
  if (s.quick_fail) return quickFailCard(s);
  var c = s.cells;
  return cardHead(s) + noteList(s.notes) + flagList(s) + gateBadges(s) + priceBox(s) +
    "<h3>적정가 A·B·C</h3>" + fairTable(c) +
    "<h3>관문 ① 좋은 회사인가</h3>" + gate1Table(s, data) +
    "<h3>관문 ② 배당이 오래 갈까</h3>" + gate2Table(s) +
    "<h3>관문 ③ 지금 싼가</h3>" + gate3Table(c) + "<h4>5-1. 계산에 쓰는 평균값</h4>" + kvTable(c, [[94, "won"], [96, "won"], [97, "d2"], [98, "pct"], [99, "pct"], [100, "won"]]) +
    "<h4>5-3. 지금 주가가 예상하는 것</h4>" + kvTable(c, [[112, "won"], [113, "d2"], [114, "d2"], [115, "pct"], [116, "pct"], [117, "pct"], [118, "d2"]]) +
    table54(c) +
    "<h3>5년 입력 숫자</h3>" + inputTable(s) +
    "<h4>해마다 계산한 값</h4>" + colTable(s, [[47, "won"], [48, "pct"], [49, "pct"], [50, "pct"], [51, "raw"], [52, "raw"], [53, "text"], [54, "text"], [55, "won"]], 46) +
    sourceTable(s) + "<h3>그래프</h3>" + charts(s) +
    "<h3>업종 비교 (참고)</h3>" + industryBox(s) + gate4Box(s) +
    '<p class="muted">엑셀로 보려면 <code>uv run run.py --excel ' + esc(s.code) + "</code></p>";
}

// ---- 브라우저 부트스트랩 ----
function bootIndex(data, doc) {
  var app = doc.getElementById("app");
  app.innerHTML = renderIndex(data);
  var q = doc.getElementById("q"), out = doc.getElementById("results");
  q.addEventListener("input", function () { out.innerHTML = renderResults(data, q.value); });
}
function bootStock(data, win) {
  var app = win.document.getElementById("app");
  function show() {
    var code = decodeURIComponent((win.location.hash || "").replace(/^#/, ""));
    app.innerHTML = renderStock(data, code);
    var s = data.stocks[code];
    win.document.title = s ? s.name + " · 종목 상세" : "종목 상세";
    win.scrollTo(0, 0);
  }
  win.addEventListener("hashchange", show);
  show();
}
if (typeof window !== "undefined" && window.VSF_DATA) {
  if (/stock\.html$/.test(window.location.pathname)) bootStock(window.VSF_DATA, window);
  else bootIndex(window.VSF_DATA, window.document);
}
if (typeof module !== "undefined") {
  module.exports = { esc: esc, fmt: fmt, renderIndex: renderIndex, renderStock: renderStock, searchStocks: searchStocks, renderResults: renderResults };
}
