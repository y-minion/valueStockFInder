// 손으로 쓴 작은 payload. 실제 payload와 같은 키, 같은 칸 주소를 써요.
const YEARS = [2021, 2022, 2023, 2024, 2025];
const COLS = "BCDEF";

function year(i, eps, dps) {
  return { year: YEARS[i], eps, per: 8 + i * 0.5, dps, roe: 12.34 + i, debt_ratio: 80, interest_coverage: 12.5,
    net_income: 1000 + i * 10, ocf: 1500, capex: 300, dividends_paid: 200, exclude_avg: i === 0, exclude_div: false };
}

function cells(over) {
  const c = {
    B15: "①②③을 통과했어요. 이제 6번에서 ④를 직접 판단해요.",
    C11: "기준일 2026-11-13", C12: "정한 방법: C 과거 배당수익률",
    D82: "통과", D90: "통과", D110: "통과", D135: "입력 필요",
    B78: 15.6, C78: "8 이상", D78: "통과", B79: 80, C79: "200 이하", D79: "통과",
    B80: 12.5, C80: "3 이상", D80: "통과", B81: 1.52, C81: "1.0 이상", D81: "통과",
    B86: 0, D86: "통과", B87: 1, D87: "통과", B88: 0.334, C88: "20%~60%", D88: "통과",
    B89: 2.1, C89: "1.0 이상", D89: "통과",
    B94: 4000, B96: 4000, B97: 7.5, B98: 0.05, B99: 0.3, B100: 1500,
    B102: 40000, B103: 30000, B104: 30000, B105: 30000, B106: "C 과거 배당수익률", B107: 22500,
    B108: 0.7, C108: "통과 기준: 0.75배 이하", B109: 0, B112: 6000, B113: 1.5, B114: 6.4, B115: 0.071,
    B116: 0.12, B117: 0.156, B118: 7.5,
    B120: 3000, C120: 22400, D120: 16875, E120: 0.93, F120: "제값",
    B126: 5000, C126: 37500, D126: 28125, E126: 0.56, F126: "싸요",
    C131: "참고: 최근 부채비율 80%", C132: "참고: 배당성향 평균 33%",
  };
  YEARS.forEach((y, i) => {
    const col = COLS[i];
    c[col + "46"] = String(y); c[col + "47"] = 50000; c[col + "48"] = 0.05; c[col + "49"] = 0.3;
    c[col + "53"] = "정상"; c[col + "54"] = "넣음"; c[col + "55"] = 4000 + i * 100;
  });
  return Object.assign(c, over || {});
}

function stock(code, name, o) {
  o = o || {};
  const eps = [3000, 3500, 4000, 4500, 5000];
  return {
    name, code, market: "KOSPI", latest_year: 2025,
    industry: o.industry === undefined ? { group_code: "30", group_name: "자동차", size: 12, roe_median: 9.1,
      roe_rank_pct: 18.5, debt_median: 90, debt_rank_pct: 40 } : o.industry,
    inputs: { name, code, price: 21000, price_date: "2026-11-13", pbr: 0.8, memo: "",
      years: YEARS.map((_, i) => year(i, eps[i], 1000 + i * 100)),
      prior_years: [2020, 2019, 2018, 2017, 2016], prior_dps: [900, 800, null, 600, 500],
      normal_eps_override: null, my_eps: null,
      gate4: { reason: "", q1: "", q2: "", q3: "", judgment: "", why: "" } },
    cells: o.cells || cells(),
    summary: { gate1: "통과", gate2: "통과", gate3: o.gate3 || "통과", gate4: o.gate4 || "입력 필요", price: 21000,
      fair_value: 30000, method: "C 과거 배당수익률", buy_line: 22500, ratio: o.ratio === undefined ? 0.7 : o.ratio,
      drop: o.drop === undefined ? 0 : o.drop, next_step: "다음", roe_avg: 15.6, payout_avg: 0.3, yield_now: 0.071 },
    state: o.state || "buy", near: !!o.near, flags: o.flags || [], notes: o.notes || [],
    sources: { F27: "DART 사업보고서 2025", ...(o.sources || {}) }, quick_fail: !!o.quick_fail,
    criteria: { required_return: 0.1, safety_margin: 0.25, roe_min: 8, debt_ratio_max: 200 },
    criteria_overridden: !!o.overridden, extra_gate1: o.extra_gate1 || null, extras: o.extras === undefined ? null : o.extras,
  };
}

function finStock() {
  const c = cells({
    B79: null, C79: "해당 없음", D79: "해당 없음", B80: null, C80: "해당 없음", D80: "해당 없음",
    B81: null, C81: "해당 없음", D81: "해당 없음", B89: null, C89: "해당 없음", D89: "해당 없음",
    F_LOSS_B: 0, F_LOSS_C: "0년", F_LOSS_D: "통과", F_CAP_B: null, F_CAP_C: "9 이상", F_CAP_D: "직접 확인",
    F_CAP_SRC: "자본비율은 금감원 금융통계정보시스템(fisis.fss.or.kr)이나 사업보고서 '자본적정성'에서 확인해 주세요.",
  });
  const s = stock("105560", "KB금융", { cells: c, state: "watch", ratio: 0.9, drop: 0.1 });
  s.financial = { kind: "금융지주", capital_label: "보통주자본비율", capital_min: 9, capital: null };
  s.inputs.years.forEach((y) => { y.debt_ratio = null; y.interest_coverage = null; y.ocf = null; y.capex = null; });
  return s;
}

const extras = {
  disclosures: [{ date: "2026-11-10", title: "분기보고서", url: "https://dart.fss.or.kr/x" }],
  news: [{ title: "뉴스 제목 & 요약", url: "https://example.com/n", date: "2026-11-12" }],
  news_link: "https://search.naver.com/search.naver?where=news&query=x",
  quarterly: { label: "2026년 3분기", net_income: 100, net_income_prev: 90, op_income: 120, op_income_prev: null },
  weekly_closes: [["2026-10-30", 20000], ["2026-11-06", 20500], ["2026-11-13", 21000]], notes: ["공시 일부를 못 받았어요"],
};

const failCells = { D82: "통과", D90: "확인 필요", B86: 0, D86: "통과", B87: 0, D87: "통과", B15: "빠른 탈락 문장" };

const stocks = {
  A: stock("A", "가나다산업", { extras, ratio: 0.7 }),
  B: stock("B", "라마바식품", { state: "watch", gate3: "탈락", ratio: 0.8, drop: 0.06, near: true, overridden: true,
    extra_gate1: "통과" }),
  "000270": stock("000270", "기아", { state: "out", gate3: "탈락", ratio: 1.3, drop: 0.5 }),
  F: stock("F", "차카타화학", { state: "watch", ratio: 0.85, drop: 0.13, flags: ["2024년 DPS가 보고서마다 달라요."] }),
  X: stock("X", "<script>alert(1)</script>", { state: "watch", ratio: 0.9, drop: 0.2, industry: null }),
  "105560": finStock(),
  Q: stock("Q", "빠른탈락", { state: "out", quick_fail: true, cells: failCells, notes: ["배당 보고서만 받았어요"] }),
};
function score(total, grade, missing, max) {
  return { total, max: max || 100, grade, missing: missing || 0,
    groups: { cheap: 30, steady: 17, return: total - 52, other: 5 },
    items: [
      { key: "per", label: "PER", group: "cheap", value: "7.5배", rule: "5배 미만 15 · 8배 미만 11", points: 11, max: 15,
        status: "ok", source: "현재가 ÷ 2025년 EPS" },
      { key: "freq", label: "분기·반기 배당", group: "return", value: "자료 없음", rule: "4회 이상 5 · 2회 이상 3", points: 0,
        max: 5, status: "no_data", source: "" },
    ] };
}
Object.values(stocks).forEach((s) => { s.score = null; s.score_prev = null; });
stocks.P = stock("P", "가나다산업우", { ratio: 0.6 });
stocks.P.share_class = "우선"; stocks.P.common_code = "A"; stocks.P.common_price = 30000; stocks.P.common_dps = 1350;
stocks.P.liquidity = { avg: 50000000, days: 13, thin: true };
stocks.P.score = score(80, "B");
stocks.A.score = score(85, "A"); stocks.A.score_prev = 80;
stocks.B.score = score(72, "B", 5);
stocks["105560"].score = score(64, "C"); stocks["105560"].score_prev = 66;
stocks.Q.boundaries = stocks.F.boundaries = [{ cell: "D78", label: "ROE 5년 평균", value: 7.6, threshold: 8, gap: -0.4, unit: "%p", passed: false }];
stocks.A.boundaries = [{ cell: "D88", label: "배당성향", value: 58, threshold: 60, gap: -2, unit: "%p", passed: true }];

module.exports = {
  schema: 1,
  run: {
    date: "2026-11-14", price_date: "2026-11-13", analyzed: 6, total_listed: 2700,
    excluded: { "우선주": [["005935", "삼성전자우"]] }, failed: [["111111", "실패회사", "사유"]], pending: [["222222", "대기회사"]],
    partial: true, first_run: false, year_end_missing: [],
    criteria: {
      criteria: { required_return: 0.1, safety_margin: 0.25, roe_min: 8, debt_ratio_max: 200, interest_coverage_min: 3,
        ocf_to_ni_min: 1, payout_min: 0.2, payout_max: 0.6, fcf_to_div_min: 1, abnormal_ratio: 0.5, isa_weight_max: 0.1 },
      report: { watch_range: 0.2, near_range: 0.1 }, industry: { use_in_verdict: false, roe_top_percent: 50, min_group_size: 5, overrides: {} } },
    criteria_changes: [{ key: "required_return", label: "요구수익률", old: 0.1, new: 0.12 }],
  },
  summary: { buy: 1, near: 2, watch: 4, gate12_ok: 5, prev: { buy: 0, near: 1, watch: 3, gate12_ok: 4 } },
  changes: [
    { code: "A", name: "가나다산업", kind: "new_buy", causes: ["주가"] },
    { code: "B", name: "라마바식품", kind: "above_buy", causes: ["기준 변경", "재무 갱신"] },
  ],
  watchlist: ["A", "B", "F", "X"],
  score_rank: ["A", "P", "B", "105560"],
  score_summary: { eligible: 4, A: 1, B: 2, C: 1, D: 0, partial: false, top_n: 3, settings_changed: false,
    groups: [["cheap", "싼가"], ["steady", "꾸준히 버나"], ["return", "주주환원"], ["other", "기타"]],
    judgment: [["sustain", "이익이 앞으로도 지속 가능한가", ["대체로 지속 가능", "불안정"], [5, 0]],
      ["growth", "미래 성장 잠재력", ["매우 높다", "높다", "보통", "낮다"], [10, 7, 5, 3]],
      ["management", "기업 경영", ["우수한 경영자", "전문 경영자", "실적이 저조한 오너 경영"], [10, 5, 0]],
      ["brand", "세계적 브랜드·경쟁력", ["있다", "없다"], [5, 0]]] },
  near_miss: ["Q"],
  stocks,
  criteria_check: {
    partial: true,
    groups: [
      { group: "일반 회사", n: 5, rows: [
        { key: "roe_min", label: "ROE 최소", threshold: 8, unit: "%", dist: { n: 5, p25: 6, median: 8.5, p75: 12 }, pass_now: 3,
          stricter: { threshold: 9, pass: 2, watch_in: [], watch_out: [["A", "가나다산업"]] },
          looser: { threshold: 7, pass: 4, watch_in: [["F", "차카타화학"]], watch_out: [] } },
        { key: "payout_min", label: "배당성향 하한", threshold: 55, unit: "%", dist: null, pass_now: 0, stricter: null,
          looser: { threshold: 50, pass: 0, watch_in: [], watch_out: [] } },
        { key: "required_return", label: "요구수익률", threshold: 10, unit: "%", dist: null, pass_now: null,
          stricter: { threshold: 11, pass: null, watch_in: [], watch_out: [] }, looser: null },
      ] },
      { group: "금융회사", n: 1, rows: [
        { key: "bank_cet1_min", label: "은행·금융지주 보통주자본비율 최소", threshold: 9, unit: "%",
          dist: { n: 1, p25: 13.2, median: 13.2, p75: 13.2 }, pass_now: 1,
          stricter: { threshold: 10, pass: 1, watch_in: [], watch_out: [] }, looser: { threshold: 8, pass: 1, watch_in: [], watch_out: [] } },
      ] },
    ],
    industry: [{ group_name: "자동차", size: 5, roe_median: 9.1 }],
  },
};
