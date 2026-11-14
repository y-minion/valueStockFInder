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
  assert.ok(h.includes('요구수익률 0.1 → 0.12'));
  assert.ok(h.includes('관심 목록 (20% 이내)') && h.includes('매수선까지 10% 이내'));
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
