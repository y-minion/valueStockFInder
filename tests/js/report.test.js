const test = require('node:test');
const assert = require('node:assert');
const r = require('../../src/vsf/report/assets/report.js');
const data = require('./sample_data.js');

test('index shows banners, tiles, changes', () => {
  const h = r.renderIndex(data);
  for (const s of ['지난 실행과 기준이 달라졌어요', '매수선 이하', '새로 매수선 이하', '주가', '지난주']) assert.ok(h.includes(s), s);
});
test('index header and partial banner use fixed wording', () => {
  const h = r.renderIndex(data);
  assert.ok(h.includes('2026년 11월 14일 실행 · 2026년 11월 13일 종가 기준 · 분석 6개 / 상장 2700개 · 제외 1개') ||
            h.includes('분석 6개 / 상장 2,700개 · 제외 1개'));
  assert.ok(h.includes('전체 2,700개 중 6개만 분석했어요. 내일 다시 실행하면 이어서 받아요.') ||
            h.includes('전체 2700개 중 6개만 분석했어요. 내일 다시 실행하면 이어서 받아요.'));
  assert.ok(h.includes('요구수익률 10% → 12%'));
  assert.ok(h.includes('관심 목록 (20% 이내)') && h.includes('매수선까지 10% 이내'));
});
test('year-end price banner shows only when some years are missing', () => {
  const text = '연말 주가를 가져오지 못한 해가 있어요: 2019·2020. 이 해들의 PER이 비어 적정가 B·C 계산이 빠질 수 있어요.';
  const d = { ...data, run: { ...data.run, year_end_missing: [2019, 2020] } };
  assert.ok(r.renderIndex(d).includes('<div class="banner warn">' + text + '</div>'));
  assert.deepEqual(data.run.year_end_missing, []);
  assert.ok(!r.renderIndex(data).includes('연말 주가를 가져오지 못한'));
  const old = { ...data, run: { ...data.run } };
  delete old.run.year_end_missing;                       // 예전 data.js에는 키가 없어요
  assert.ok(!r.renderIndex(old).includes('연말 주가를 가져오지 못한'));
});
test('first run banner', () => {
  const d = { ...data, run: { ...data.run, first_run: true, partial: false, criteria_changes: [] } };
  assert.ok(r.renderIndex(d).includes('첫 실행이라 비교할 지난 결과가 없어요'));
});
test('watchlist order follows payload', () => {
  const h = r.renderIndex(data);
  assert.ok(h.indexOf(data.stocks.A.name) < h.indexOf(data.stocks.B.name));
});
test('flagged stock always shows warning chip', () => {
  assert.ok(r.renderIndex(data).includes('숫자 확인 필요'));
  assert.ok(r.renderStock(data, 'F').includes('숫자 확인 필요'));
  assert.ok(!r.renderStock(data, 'A').includes('숫자 확인 필요'));
});
test('names are escaped', () => {
  const h = r.renderIndex(data);
  assert.ok(!h.includes('<script>alert'));
  assert.ok(h.includes('&lt;script&gt;alert'));
  assert.ok(!r.renderStock(data, 'X').includes('<script>alert'));
  assert.equal(r.esc(`&<>"'`), '&amp;&lt;&gt;&quot;&#39;');
});
test('stock card core sections', () => {
  const h = r.renderStock(data, 'A');
  for (const s of [data.stocks.A.cells.B15, '직접 판단 필요', '<svg', 'uv run run.py --excel A', data.stocks.A.sources.F27])
    assert.ok(h.includes(s), s);
  assert.equal((h.match(/<svg/g) || []).length, 3);
  assert.ok((h.match(/<svg[^>]*>\s*<title>/g) || []).length === 3);
});
test('gate 4 badge is 직접 판단 필요 only when 입력 필요', () => {
  const d = JSON.parse(JSON.stringify(data));
  d.stocks.A.cells.D135 = '통과';
  const h = r.renderStock(d, 'A');
  assert.ok(!h.includes('직접 판단 필요'));
  assert.ok(h.includes('④ 통과'));
});
test('card header chips and extra gate1 row', () => {
  const h = r.renderStock(data, 'B');
  assert.ok(h.includes('업종 기준 적용'));
  assert.ok(h.includes('업종 안 ROE 순위') && h.includes('상위 18.5%') && h.includes('상위 50% 이내'));
  assert.ok(h.includes('최근 연도 2025'));
});
test('null renders as dash and numbers are formatted', () => {
  const d = JSON.parse(JSON.stringify(data));
  d.stocks.A.cells.B107 = null; d.stocks.A.summary.buy_line = null;
  assert.ok(r.renderStock(data, 'A').includes('22,500'));
  d.stocks.A.cells.B105 = 1234567;
  const h = r.renderStock(d, 'A');
  assert.ok(!h.includes('22,500'));
  assert.ok(h.includes('—'));
  assert.ok(h.includes('1,234,567'));
  assert.equal(r.fmt(null, 'won'), '—');
  assert.equal(r.fmt('', 'won'), '—');
  assert.equal(r.fmt(0.7, 'd2'), '0.70');
  assert.equal(r.fmt(0.0711, 'pct'), '7.1%');
  assert.equal(r.fmt(0.06, 'pct0'), '6%');
  assert.equal(r.fmt(12.3456, 'raw'), '12.35');
  assert.equal(r.fmt(21000.4, 'won'), '21,000');
});
test('index row shows drop percent and ratio', () => {
  const h = r.renderIndex(data);
  assert.ok(h.includes('0.70') && h.includes('13%') && h.includes('상위 18.5%'));
  assert.ok(h.includes('href="stock.html#A"'));
});
test('quick fail card', () => {
  const h = r.renderStock(data, 'Q');
  assert.ok(h.includes('나머지 숫자는 받지 않았어요'));
  assert.ok(h.indexOf('배당 보고서만 받았어요') < h.indexOf('관문'));
  assert.ok(!h.includes('<svg'));
});
test('missing stock and back link', () => {
  const h = r.renderStock(data, 'NOPE');
  assert.ok(h.includes('이 종목은 이번 실행에서 분석되지 않았어요'));
  assert.ok(h.includes('href="index.html"') && h.includes('← 첫 페이지'));
  assert.ok(r.renderStock(data, 'A').includes('← 첫 페이지'));
});
test('search by name and code', () => {
  assert.deepEqual(r.searchStocks(data, '기아').map(x => x.code), ['000270']);
  assert.equal(r.searchStocks(data, '000270').length, 1);
  assert.equal(r.searchStocks(data, '').length, 0);
});
test('search is case-insensitive and limited to 20, sorted by code', () => {
  assert.deepEqual(r.searchStocks(data, 'q').map(x => x.code), ['Q']);
  const big = { stocks: {} };
  for (let i = 99; i >= 0; i--) big.stocks['C' + String(i).padStart(3, '0')] = { name: 'Foo' + i, code: 'C' + String(i).padStart(3, '0') };
  const res = r.searchStocks(big, 'FOO');
  assert.equal(res.length, 20);
  assert.deepEqual(res.map(x => x.code), res.map(x => x.code).slice().sort());
  assert.equal(r.searchStocks(big, 'c01').length, 10);
});
test('hostile urls are not linked', () => {
  const d = JSON.parse(JSON.stringify(data));
  d.stocks.A.extras.news[0].url = 'javascript:alert(1)';
  assert.ok(!r.renderStock(d, 'A').includes('javascript:'));
});
test('lists of excluded, failed, pending', () => {
  const h = r.renderIndex(data);
  for (const s of ['삼성전자우', '실패회사', '사유', '대기회사', '<details']) assert.ok(h.includes(s), s);
});
test('gate tables show static criteria and a gate 3 verdict row', () => {
  const h = r.renderStock(data, 'A');
  for (const s of ['0번 (아니면 이유 확인)', '>0번<', '관문 ③ 결과', '주가 ≤ 매수선', 'pill ok">통과']) assert.ok(h.includes(s), s);
  assert.ok(h.includes('통과 기준: 0.75배 이하'));
});

test('criteria change banner shows booleans and objects and escapes once', () => {
  const d = { ...data, run: { ...data.run, criteria_changes: [
    { key: 'use_in_verdict', label: '업종 비교를 판정에 넣기', old: false, new: true },
    { key: 'overrides', label: '업종별 기준 덮어쓰기', old: {}, new: { '35': { roe_min: 6 } } },
    { key: 'overrides', label: '업종별 기준 덮어쓰기', old: { '35': { roe_min: 6, debt_ratio_max: 150 }, '20': { roe_min: 9 } }, new: {} },
    { key: 'required_return', label: '요구수익률', old: 0.1, new: 0.09 },
    { key: 'roe_min', label: 'ROE 최소', old: 8, new: 7.5 },
    { key: 'interest_coverage_min', label: '이자보상배율 최소', old: 3, new: 2.5 },
    { key: 'min_group_size', label: '업종 최소 묶음 크기', old: 5, new: 3 },
    { key: 'note', label: 'A&B', old: 'x<y', new: null },
  ] } };
  const banners = [...r.renderIndex(d).matchAll(/<div class="banner warn">([^<]*)<\/div>/g)].map(m => m[1]);
  const prefix = '지난 실행과 기준이 달라졌어요: ';
  // 머리의 '적용한 기준' 줄과 같은 단위로 보여줘요 (0.1 → 10%, 8 → 8%, 3 → 3배)
  for (const want of ['업종 비교를 판정에 넣기 꺼짐 → 켜짐', '업종별 기준 덮어쓰기 없음 → 35: roe_min 6%',
                      '업종별 기준 덮어쓰기 20: roe_min 9% / 35: roe_min 6%, debt_ratio_max 150% → 없음',
                      '요구수익률 10% → 9%', 'ROE 최소 8% → 7.5%', '이자보상배율 최소 3배 → 2.5배',
                      '업종 최소 묶음 크기 5개 → 3개', 'A&amp;B x&lt;y → —'])
    assert.ok(banners.includes(prefix + want), want);
  assert.ok(!banners.join('').includes('&amp;lt;') && !banners.join('').includes('&amp;amp;'));
});
test('header shows the applied criteria in one line', () => {
  const line = '적용한 기준: 요구수익률 10% · 안전마진 25% · ROE ≥ 8% · 부채비율 &lt; 200% · 이자보상배율 ≥ 3배 · ' +
    '배당성향 20%~60% · 관심 목록 20% 이내';
  const h = r.renderIndex(data);
  assert.ok(h.includes('<p class="muted">' + line + ' · <a href="criteria.html">기준 점검</a></p>'));
  assert.ok(h.indexOf('적용한 기준') < h.indexOf('banner'));            // 머리 안, 알림보다 위
  const d = JSON.parse(JSON.stringify(data));
  Object.assign(d.run.criteria.criteria, { required_return: 0.095, roe_min: 7.5, payout_max: 0.65 });
  d.run.criteria.report.watch_range = 0.15;
  const h2 = r.renderIndex(d);
  assert.ok(h2.includes('요구수익률 9.5% · ') && h2.includes('ROE ≥ 7.5% · ') && h2.includes('배당성향 20%~65% · 관심 목록 15% 이내'));
  delete d.run.criteria;                                                 // 예전 data.js
  assert.ok(!r.renderIndex(d).includes('적용한 기준'));
});
test('watchlist industry column shows rank and median', () => {
  const h = r.renderIndex(data);
  assert.ok(h.includes('상위 18.5% (중간값 9.1%)'));
  const d = JSON.parse(JSON.stringify(data));
  d.stocks.A.industry.roe_rank_pct = null;
  assert.ok(r.renderIndex(d).includes('<td class="num">—</td>'));
});

test('financial card shows sector rows and not-applicable rows', () => {
  const h = r.renderStock(data, '105560');
  for (const s of ['금융지주 · 금융업 기준으로 판정했어요', '최근 5년 적자 없음', '보통주자본비율', '해당 없음',
                   '자본비율은 금감원 금융통계정보시스템']) assert.ok(h.includes(s), s);
});
test('financial chip in the watchlist and the start banner', () => {
  const d = { ...data, run: { ...data.run, financial_started: true }, watchlist: [...data.watchlist, '105560'] };
  const h = r.renderIndex(d);
  assert.ok(h.includes('금융회사를 금융업 기준으로 분석하기 시작했어요') && h.includes('chip info">금융<'));
});
test('old data without financial fields still renders', () => {
  const d = JSON.parse(JSON.stringify(data));
  delete d.stocks['105560'].financial; delete d.run.financial_started;
  assert.doesNotThrow(() => r.renderStock(d, '105560'));
  assert.ok(!r.renderStock(d, '105560').includes('금융업 기준으로 판정'));
});
test('boundary chips on the gate tables', () => {
  const q = r.renderStock(data, 'F');
  assert.ok(q.includes('경계 · 기준까지 0.4%p'));
  assert.ok(q.includes('chip warn'));
  const a = r.renderStock(data, 'A');
  assert.ok(a.includes('경계 · 기준보다 2%p 여유') && a.includes('chip info">경계'));
});
test('near-miss section on the first page', () => {
  const h = r.renderIndex(data);
  assert.ok(h.includes('<h2>아깝게 탈락 (기준 한 칸 안쪽)</h2>'));
  assert.ok(h.includes('ROE 5년 평균 7.6% · 기준까지 0.4%p'));
  assert.ok(h.indexOf('관심 목록') < h.indexOf('아깝게 탈락'));
  const d = { ...data, near_miss: [] };
  assert.ok(!r.renderIndex(d).includes('아깝게 탈락'));
  const old = { ...data }; delete old.near_miss;
  assert.ok(!r.renderIndex(old).includes('아깝게 탈락'));
});
test('old data without boundaries renders', () => {
  const d = JSON.parse(JSON.stringify(data));
  Object.values(d.stocks).forEach((s) => { delete s.boundaries; });
  assert.doesNotThrow(() => r.renderStock(d, 'Q'));
});

test('criteria page renders both groups and per-variant lists', () => {
  const h = r.renderCriteria(data);
  for (const t of ['일반 회사', '금융회사', '한 칸 엄하게', '한 칸 느슨하게', '분포 (25%·중간·75%)', '+1/−0', '+0/−1', '차카타화학', '자동차']) assert.ok(h.includes(t), t);
  assert.ok(r.renderIndex(data).includes('<a href="criteria.html">기준 점검</a>'));
});
test('criteria page partial banner and missing variant', () => {
  assert.ok(r.renderCriteria(data).includes('일부만 분석해서 참고만 하세요'));
  assert.ok(r.renderCriteria(data).includes('계산 안 함'));
  const d = { ...data, criteria_check: { ...data.criteria_check, partial: false } };
  assert.ok(!r.renderCriteria(d).includes('일부만 분석해서'));
});
test('criteria page without data shows fallback', () => {
  const d = { ...data }; delete d.criteria_check;
  assert.ok(r.renderCriteria(d).includes('이 리포트에는 기준 점검 자료가 없어요'));
});

test('capital row shows value, base month and source when a ratio is present', () => {
  const d = JSON.parse(JSON.stringify(data));
  const s = d.stocks['105560'];
  const src = '금감원 금융통계정보시스템 SL008·보통주자본비율 (2026-06 기준)';
  Object.assign(s.cells, { F_CAP_B: 13.2, F_CAP_D: '통과', F_CAP_SRC: src });
  s.financial.capital = { value: 13.2, base_month: '2026-06', source: '금감원 금융통계정보시스템 SL008·보통주자본비율' };
  const h = r.renderStock(d, '105560');
  for (const t of ['13.2%', '2026-06', '금감원 금융통계정보시스템 SL008']) assert.ok(h.includes(t), t);
});
test('recent four quarters row sits in the 5-4 table and warns when it is not cheap', () => {
  const d = JSON.parse(JSON.stringify(data));
  const warning = '최근 4분기 EPS 452원으로 보면 매수선이 3,390원이라 지금 주가 3,790원보다 낮아요. 계산기는 연간 실적만 봐서 아직 반영하지 못했어요.';
  d.stocks.A.extras.recent = { label: '최근 4분기 (2025년 4분기~2026년 3분기)', eps: 452, fair: 4520, buy_line: 3390,
                               ratio: 0.8385, verdict: '제값', warning };
  const h = r.renderStock(d, 'A');
  const at = h.indexOf('최근 4분기 (2025년 4분기~2026년 3분기)');
  assert.ok(h.indexOf('최근 해(F열)') < at && at < h.indexOf('최근 5년 중 가장 좋은 해'));
  for (const s of ['3,390', '4,520', '0.84', warning, '최근 실적 미달']) assert.ok(h.includes(s), s);
  assert.ok(r.renderIndex(d).includes('최근 실적 미달'));
  d.stocks.A.extras.recent.warning = null;
  assert.ok(r.renderStock(d, 'A').includes('최근 4분기 (2025년'));
  assert.ok(!r.renderStock(d, 'A').includes('최근 실적 미달') && !r.renderIndex(d).includes('최근 실적 미달'));
});
test('old data without the recent row renders', () => {
  assert.ok(!('recent' in data.stocks.A.extras));
  assert.ok(!r.renderStock(data, 'A').includes('최근 4분기'));
  assert.ok(!r.renderStock(data, 'B').includes('최근 4분기'));
});
