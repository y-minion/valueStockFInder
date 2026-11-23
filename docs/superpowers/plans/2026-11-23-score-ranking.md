# 점수 순위 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최근 해에 배당을 준 모든 종목(금융 포함)에 100점 점수를 매기고, 리포트 첫 화면을 점수 순위로 바꾼다.

**Architecture:** 관문 계산(`evaluate`)은 그대로 두고, 그 뒤에 점수 자료 받기(`data/score_facts.py`) → 점수 계산(`score.py`, 순수 함수) → payload·스냅샷·리포트로 이어 붙인다. 배점과 구간은 `settings.toml [score]`에서 읽는다.

**Tech Stack:** Python 3.13 / uv, httpx, pytest; 리포트는 바닐라 JS + `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-23-score-ranking-design.md`

## Global Constraints

- 공식 API만 쓴다(OpenDART, KRX). 실행 중 AI 없음. 새 의존성 없음.
- 키는 화면·파일·예외 글에 쓰지 않는다.
- 관문 ①②③ 계산, 엑셀 내보내기, 엑셀 판정 일치는 바꾸지 않는다. 점수는 엑셀에 쓰지 않는다.
- 사용자에게 보이는 글은 한국어 해요체. 등급에 "매수/적극 매수/장기투자 적합" 같은 권유 글을 쓰지 않는다.
- 자료 없는 항목은 `status: "no_data"`, 합계에는 0으로 더하고, 그 배점을 `missing`에 모은다.
- 원본 계산기 엑셀과 go_ava 평가표 파일은 건드리거나 커밋하지 않는다. 사용자가 고친 `README.md` 내용은 지우지 않는다.
- 테스트: `uv run pytest -q`, `node --test tests/js/` 둘 다 초록이어야 커밋한다.

## Review Focus

1. 자사주 표에서 소계·세부 줄을 총계와 겹쳐 더함 → 보통주 '총계' 줄만 쓴다 (Task 4 `test_treasury_uses_common_total_row_only`).
2. 최근 사업연도 EPS가 0 이하 → PER·최근 4분기 항목은 0점이지 0으로 나누다 죽지 않는다 (Task 5 `test_loss_year_gives_zero_not_error`).
3. 점수 자료 받는 중 DART 한도 → 받은 데까지 쓰고 나머지는 `no_data`, 리포트에 partial 배너 (Task 4 `test_gather_stops_on_quota_and_marks_partial`, Task 7 JS).
4. 배점 설정이 바뀐 주 → 지난주 대비 변화 대신 "배점이 바뀌었어요" (Task 6 `test_score_change_hidden_when_score_settings_changed`).
5. 예전 스냅샷(점수 없음)과 예전 data.js → 오류 없이 변화 '—' (Task 6 `test_old_snapshot_without_score_reads_none`, Task 7 JS).

---

### Task 1: `[score]` 설정

**Files:**
- Modify: `src/vsf/config.py`, `settings.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ItemRule(points: float, steps: tuple[tuple[float, float], ...] = (), none_points: float | None = None)` (frozen)
  - `ScoreSettings(top_n: int = 50, grade_a: float = 80, grade_b: float = 70, grade_c: float = 50, subsidiary_stake_min: float = 30.0, items: dict[str, ItemRule] = DEFAULT_ITEMS)` (frozen)
  - `ITEM_OPS: dict[str, str]` — 항목 키 → 비교 방향 `"lt"|"le"|"ge"|"gt"|"flag"|"freq"`
  - `Settings.score: ScoreSettings = ScoreSettings()`; `settings_fingerprint(s)["score"]`

기본값 (스펙 5장 그대로, 키 이름 고정):

| 키 | op | points | steps | none_points |
|---|---|---|---|---|
| per | lt | 15 | (5,15),(8,11),(10,7),(15,3) | |
| pbr | lt | 5 | (0.3,5),(0.6,4),(1.0,2) | |
| ratio | le | 15 | (0.75,15),(0.9,10),(1.0,6),(1.2,3) | |
| roe | ge | 10 | (15,10),(10,7),(8,5),(5,2) | |
| no_loss | flag | 5 | | |
| ttm | ge | 5 | (0.9,5),(0.7,3) | |
| yield | gt | 10 | (7,10),(5,7),(3,5),(0,2) | |
| streak | ge | 5 | (7,5),(5,4),(3,3) | |
| freq | freq | 5 | (4,5),(2,3) — 한 해 지급 횟수 이상 | |
| buyback | flag | 7 | | |
| cancel | gt | 8 | (2,8),(1.5,5),(0.5,3) | |
| treasury | lt | 5 | (2,4),(5,2) | 5 (0주일 때) |
| subsidiary | flag | 5 | | |

- [ ] **Step 1: 실패하는 테스트**

```python
def test_shipped_score_defaults():
    s = load_settings(ROOT / "settings.toml").score
    assert s == ScoreSettings()
    assert sum(r.points for r in s.items.values()) == 100
    assert s.items["per"].steps == ((5, 15), (8, 11), (10, 7), (15, 3))
    assert s.items["treasury"].none_points == 5

def test_score_steps_override(tmp_path):
    p = write_settings(tmp_path, score={"per": "{ points = 20, steps = [[5, 20], [8, 12]] }"})
    s = load_settings(p).score
    assert s.items["per"] == ItemRule(20, ((5, 20), (8, 12)))
    assert s.items["pbr"] == ScoreSettings().items["pbr"]

@pytest.mark.parametrize("body,word", [
    ('{ points = 5, steps = [[5, 9]] }', "배점"),                 # 구간 점수 > 배점
    ('{ points = 15, steps = [[8, 11], [5, 15]] }', "순서"),      # lt인데 경계가 내려감
    ('{ points = -1 }', "0 이상"),
])
def test_bad_score_item(tmp_path, body, word):
    with pytest.raises(ConfigError) as e:
        load_settings(write_settings(tmp_path, score={"per": body}))
    assert word in str(e.value)

def test_unknown_score_item(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_settings(write_settings(tmp_path, score={"growth": "{ points = 10 }"}))
    assert "알 수 없는" in str(e.value)

def test_fingerprint_has_score():
    fp = settings_fingerprint(load_settings(ROOT / "settings.toml"))
    assert fp["score"]["items"]["per"]["points"] == 15 and fp["score"]["top_n"] == 50
```

`write_settings`(tests/helpers.py)가 `score=` 섹션을 쓸 수 있게 넓힌다(값은 TOML 글자 그대로).

- [ ] **Step 2:** `uv run pytest tests/test_config.py -q` → 새 테스트 FAIL.
- [ ] **Step 3: 구현.** `_SECTIONS`에 `"score"`. `[score]`의 스칼라 키(`top_n` 정수 ≥1, `grade_a/b/c` 숫자 ≥0이고 a ≥ b ≥ c, `subsidiary_stake_min` 0~100)와 항목 하위표(`[score.per]` 또는 인라인 표)를 읽는다. 항목 검사: points ≥ 0, 각 단계 점수 0 ≤ x ≤ points, 경계 순서는 lt/le면 오름차순, ge/gt/freq면 내림차순(엄격), 알 수 없는 키는 한국어 오류. 지정 안 한 항목은 기본값. `CRITERIA_LABELS`에 `"top_n"` 등 라벨 추가. `settings_fingerprint`에 `"score": asdict(s.score)` (튜플은 리스트로 직렬화돼도 됨). `settings.toml`에 기본값과 같은 `[score]` 블록을 주석과 함께 적는다(사용자가 숫자만 바꾸면 되게, 항목마다 한 줄 설명).
- [ ] **Step 4:** `uv run pytest -q` → PASS (기존 `test_shipped_settings_are_excel_defaults` 포함).
- [ ] **Step 5: 커밋** `feat: [score] settings for the score ranking`

---

### Task 2: 금융회사(그 밖) 포함과 빠른 탈락 좁히기

**Files:**
- Modify: `src/vsf/data/universe.py`, `src/vsf/financial.py`, `src/vsf/data/assemble.py:211-215`, `src/vsf/collect.py` (빠른 탈락 메모 글)
- Test: `tests/test_universe.py`, `tests/test_collect.py`, `tests/test_assemble.py`

**Interfaces:**
- Produces: `company_exclusion(company, include_financial=True)`는 `"그 밖"`을 더는 빼지 않는다(include_financial=False 동작은 그대로). `CAPITAL_LABELS["그 밖"] = "자본비율"`. `quick_fail_check(rows, latest_year)`는 **최근 해 DPS가 0일 때만** True.

- [ ] **Step 1: 테스트 고치기/더하기**

```python
# test_universe.py — 기존 ("642","어떤신탁","금융회사(그 밖)") 등 3줄의 기대값을 None으로
def test_other_financial_is_analyzed():
    assert company_exclusion({"acc_mt": "12", "induty_code": "64201"}) is None
    assert company_exclusion({"acc_mt": "12", "induty_code": "64201"}, include_financial=False) == "금융회사"

# test_assemble.py
def test_quick_fail_only_when_latest_year_has_no_dividend():
    assert quick_fail_check(div_rows("-", "1,000", "900"), 2025) is True      # 최근 해 0
    assert quick_fail_check(div_rows("1,000", "-", "900"), 2025) is False     # 전 해만 0

# test_collect.py — test_quick_fail_skips_statements의 배당을 div_rows("-", "1,000", "900")로,
# test_exclusions_bucketed의 기대 집합에서 "금융회사(그 밖)"을 빼고 그 종목이 records에 들어간다고.
def test_skipped_dividend_year_now_gets_full_calculation():
    dart = FakeDart.with_company("000270", dividends={2025: div_rows("1,000", "-", "900")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    info, a = c.records["000270"]
    assert not a.quick_fail and dart.calls_of("financials") >= 1
    assert evaluate_one(info, a, load_settings(ROOT / "settings.toml"), None).summary.gate2 == "탈락"
```

(`div_rows(당기, 전기, 전전기)` 인자 순서는 tests/helpers.py의 정의를 따른다. 위 예는 당기=최근 해 가정이니 실제 순서에 맞춰 쓴다.)

- [ ] **Step 2:** 해당 테스트 FAIL 확인.
- [ ] **Step 3: 구현.** `company_exclusion`에서 `"그 밖"` 제외 줄 삭제(`include_financial=False` 분기는 유지). `CAPITAL_LABELS`에 `"그 밖": "자본비율"`. `quick_fail_check` → `dps_from_report(rows, latest_year).get(latest_year) == 0`. docstring과 빠른 탈락 메모 글("최근 해에 배당을 주지 않아 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요.")을 새 규칙에 맞게 고친다. report.js `quickFailCard`의 안내 글도 Task 7에서 맞춘다.
- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: analyze other financial companies; quick-fail only on a no-dividend latest year`

---

### Task 3: DART 클라이언트 — 정기보고서 항목 캐시, 분기 재무제표 캐시, 상장 회사명

**Files:**
- Modify: `src/vsf/data/dart.py`, `tests/fakes.py`
- Test: `tests/test_dart.py`

**Interfaces:**
- Produces:
  - `DartClient.periodic(api: str, corp_code: str, year: int, report: str = "11011") -> list[dict] | None` — `{api}`는 `"stockTotqySttus"` 같은 이름(`.json` 없이). 결과가 있으면 캐시(`dart:{corp}:{api}:{year}:{report}`), 013이면 None(캐시 안 함).
  - `DartClient.financials(...)`: 분기 보고서도 **결과가 있을 때** 캐시한다(없으면 매번 다시 물음).
  - `DartClient.corp_names() -> dict[str, str]` — 종목코드 → DART 회사명 (CORPCODE.xml에서, `corp_codes()`와 같은 캐시 사용).
  - `tests/fakes.FakeDart`: 생성자 엔트리에 `"periodic": {(api, year, report): rows}`, `"quarterly_fin": {(year, report): FinRows}`를 받고 `periodic()`·`corp_names()`를 흉내 낸다. 기존 테스트가 쓰는 모양은 그대로.

- [ ] **Step 1: 테스트**

```python
def test_periodic_cached_and_013_not_cached(dart, transport): ...
    # 첫 호출 1회 네트워크, 같은 인자 두 번째는 0회. 013 응답은 None이고 다음에 다시 부른다.
def test_quarterly_cached_when_found(dart, transport): ...
    # 기존 test_quarterly_not_cached를 이 이름으로 바꾸고 기대를 '찾으면 캐시'로.
def test_quarterly_missing_is_asked_again(store): ...
def test_corp_names_maps_stock_code_to_name(dart): ...
    # synthetic CORPCODE.xml의 종목 하나: corp_names()["000270"] == 그 파일의 corp_name
```

- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현. `corp_codes()`의 XML 파싱을 내부 함수로 빼서 `corp_names()`와 같이 쓴다. 키는 지금처럼 요청 파라미터에만.
- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: cached periodic-report items and quarterly statements in the DART client`

---

### Task 4: 점수 자료 받기 (`data/score_facts.py`)

**Files:**
- Create: `src/vsf/data/score_facts.py`, `tests/fixtures/dart/score/*.json` (2026-11-23에 받은 실제 응답: 기아 `tesstkAcqsDspsSttus`·`stockTotqySttus` 2025, 우리금융지주 `tesstkAcqsDspsSttus` 2025, KB금융 `alotMatter` 2026 11013, 롯데정밀화학 `alotMatter` 2026 11013·11012, 우리금융지주 `otrCprInvstmntSttus` 2025 — 키 없음, 공개 자료)
- Modify: `src/vsf/extras.py` (`_quarterly`를 공용으로: 이름 `quarterly(dart, corp, year) -> dict | None`, 기존 호출부 수정)
- Test: `tests/test_score_facts.py`

**Interfaces:**
- Consumes: Task 3 `DartClient.periodic`, `financials`, `corp_names`; `extras.quarterly_summary`.
- Produces:

```python
@dataclass(frozen=True)
class ScoreFacts:
    ttm_eps: float | None = None            # 최근 4분기 EPS (원)
    ttm_label: str | None = None            # "2025년 4분기~2026년 3분기"
    ttm_is_annual: bool = False             # 사업보고서 뒤 분기 보고서가 아직 없음
    payout_per_year: int | None = None      # 4 분기 · 2 반기 · 1 연 1회 · None 자료 없음
    issued: float | None = None             # 보통주 발행주식 총수
    treasury: float | None = None           # 보통주 자기주식 수
    buyback_years: tuple[bool | None, ...] = (None, None, None)   # 최근 사업연도부터 3년
    cancelled: float | None = None          # 최근 사업연도 소각 주식 수
    subsidiaries: tuple[tuple[str, float], ...] | None = None     # 상장 자회사 (이름, 지분율%)
    sources: dict[str, str] = field(default_factory=dict)         # 항목 키 → "2025 사업보고서 (접수 2026-03-xx)" 등

def parse_stock_total(rows: list[dict]) -> tuple[float | None, float | None]      # (issued, treasury)
def parse_treasury_changes(rows: list[dict]) -> tuple[float | None, float | None] # (매입, 소각) — 보통주 '총계' 줄 기준, 매입 = 총계 취득 − 기타취득 취득
def interim_payouts(q1_rows: list[dict] | None, half_rows: list[dict] | None) -> int | None
def listed_subsidiaries(rows: list[dict], listed_names: set[str], stake_min: float) -> tuple[tuple[str, float], ...]
def normalize_name(s: str) -> str          # ㈜·(주)·주식회사·공백·줄바꿈 제거
def fetch_score_facts(dart, corp: str, latest_year: int, latest_eps: float | None,
                      listed_names: set[str], stake_min: float) -> ScoreFacts
def gather_score_facts(run: RunResult, dart, listed_names: set[str], stake_min: float,
                       eligible: Iterable[str]) -> tuple[dict[str, ScoreFacts], bool]   # (facts, partial)
def score_facts_to_dict(f: ScoreFacts) -> dict ; def score_facts_from_dict(d: dict | None) -> ScoreFacts | None
```

- 숫자 글("8,515,181", "-")은 "-"→0, 빈칸·이상한 글→None.
- `interim_payouts`: 1분기 보고서 '주당 현금배당금(원)' 보통주 `thstrm` > 0 → 4; 아니면 반기 보고서 > 0 → 2; 둘 중 하나라도 받았고 둘 다 0 → 1; 둘 다 None → None. 연도는 `latest_year + 1`, 그해 반기 보고서가 None이면 `latest_year`로 다시.
- TTM: `quarterly(dart, corp, latest_year + 1)`; 없으면 `ttm_is_annual=True`. 있으면 `latest_eps + q["eps"] − q["eps_prev"]`, 라벨은 `recent_row`와 같은 모양.
- 자사주 매입 3년: `periodic("tesstkAcqsDspsSttus", corp, y)` for y in latest, latest−1, latest−2 → (매입>0 or 소각>0); 자료 None이면 그 해 None.
- `gather_score_facts`: `DartQuotaExceeded`를 만나면 멈추고 남은 종목은 넣지 않고 `partial=True`. 그 밖 `DartError/NetworkError/ValueError`는 그 종목만 기본 `ScoreFacts()`(전부 None)와 `sources["error"]`.
- `listed_names`는 cli에서 `{normalize_name(n) for n in KRX 상장 이름} ∪ {normalize_name(dart.corp_names()[c]) for c in KRX 상장 코드}`로 만든다(Task 6).

- [ ] **Step 1: 테스트** (fixture 기반)

```python
def test_treasury_uses_common_total_row_only():
    assert parse_treasury_changes(rows("000270_tesstkAcqsDspsSttus_2025")) == (7_259_634, 7_259_634)
    assert parse_treasury_changes(rows("316140_tesstkAcqsDspsSttus_2025")) == (8_515_181, 8_515_181)
def test_other_acquisition_is_not_a_buyback(): ...   # 총계 취득 = 기타취득 취득이면 매입 0
def test_stock_total_reads_common_row():
    assert parse_stock_total(rows("000270_stockTotqySttus_2025")) == (390_412_998, 1_810_273)
def test_interim_payouts():
    assert interim_payouts(rows("105560_alotMatter_2026_11013"), None) == 4
    assert interim_payouts(rows("004000_alotMatter_2026_11013"), rows("004000_alotMatter_2026_11012")) == 1
    assert interim_payouts(None, None) is None
def test_listed_subsidiaries_match_by_normalized_name():
    got = listed_subsidiaries(rows("316140_otrCprInvstmntSttus_2025"), {"우리은행"}, 30.0)
    assert got == (("우리은행", 100.0),)      # "㈜우리은행 " → "우리은행"
    assert listed_subsidiaries(rows("316140_otrCprInvstmntSttus_2025"), set(), 30.0) == ()
def test_fetch_score_facts_ttm_and_annual_fallback(): ...   # FakeDart quarterly_fin 있음/없음
def test_gather_stops_on_quota_and_marks_partial(): ...     # 두 번째 종목에서 한도 → 첫 종목만, partial True
def test_facts_round_trip_dict(): ...
```

- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: fetch score facts (TTM, payouts, treasury stock, listed subsidiaries) from DART`

---

### Task 5: 점수 계산 (`score.py`)

**Files:**
- Create: `src/vsf/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: Task 1 `ScoreSettings`, `ITEM_OPS`; Task 4 `ScoreFacts`; `evaluate.StockResult`.
- Produces:

```python
GROUPS = (("cheap", "싼가", ("per", "pbr", "ratio")),
          ("steady", "꾸준히 버나", ("roe", "no_loss", "ttm")),
          ("return", "주주환원", ("yield", "streak", "freq", "buyback", "cancel", "treasury")),
          ("other", "기타", ("subsidiary",)))
JUDGMENT = (  # 점수에 넣지 않는 판단 항목 (key, 질문, 선택지, 평가표 배점) — 카드와 /자문이 그대로 씀
    ("sustain", "이익이 앞으로도 지속 가능한가", ("대체로 지속 가능", "불안정"), (5, 0)),
    ("growth", "미래 성장 잠재력", ("매우 높다", "높다", "보통", "낮다"), (10, 7, 5, 3)),
    ("management", "기업 경영", ("우수한 경영자", "전문 경영자", "실적이 저조한 오너 경영"), (10, 5, 0)),
    ("brand", "세계적 브랜드·경쟁력", ("있다", "없다"), (5, 0)),
)
def eligible(r: StockResult) -> bool          # not quick_fail and 최근 해 DPS > 0
def dividend_streak(prior_dps, years_dps) -> int | None
def step_points(value: float, rule: ItemRule, op: str) -> float
def score_stock(r: StockResult, facts: ScoreFacts | None, cfg: ScoreSettings) -> dict | None
def grade(total: float, cfg: ScoreSettings) -> str           # "A"|"B"|"C"|"D"
def rank(scores: dict[str, dict], ratios: dict[str, float | None]) -> list[str]
```

`score_stock` 결과 dict (payload·스냅샷·card.py가 같은 모양을 씀):

```python
{"total": 62.0, "max": 100.0, "grade": "C", "missing": 8.0,
 "groups": {"cheap": 26.0, "steady": 15.0, "return": 16.0, "other": 5.0},
 "items": [{"key": "per", "label": "PER", "group": "cheap", "value": "6.2배",
            "rule": "5 미만 15 · 8 미만 11 · 10 미만 7 · 15 미만 3", "points": 11.0, "max": 15.0,
            "status": "ok", "source": "현재가 ÷ 2025년 EPS"}]}
```

- 값 고르기(스펙 5장): per = `inputs.price / years[-1].eps`(EPS ≤ 0 → 0점, value "적자"); pbr = `inputs.pbr`; ratio = `cells["B108"]`; roe = `cells["B78"]`; no_loss = 5년 EPS 모두 > 0(하나라도 None이면 no_data); ttm = `facts.ttm_is_annual`이면 만점(value "최근 연간이 가장 최신"), 아니면 `ttm_eps / years[-1].eps`(최근 EPS ≤ 0 → 0); yield = `cells["B115"] * 100`; streak = `dividend_streak(inputs.prior_dps, [y.dps for y in years])`; freq = `facts.payout_per_year`; buyback = 3년 모두 True → 만점, 하나라도 None → no_data, 아니면 0; cancel = `cancelled / (issued + cancelled) * 100`; treasury = `treasury / issued * 100`, 0주면 `none_points`; subsidiary = `()` → 만점, 있음 → 0(value에 이름·지분율, "이름으로 맞춘 거라 틀릴 수 있어요"), None → no_data.
- `facts is None`이면 facts 항목(ttm, freq, buyback, cancel, treasury, subsidiary)은 모두 no_data.
- `step_points`: 단계를 위에서부터 보고 처음 맞는 단계 점수, 없으면 0. op: lt `v < b`, le `v <= b`, ge `v >= b`, gt `v > b`, freq는 ge.
- `dividend_streak`: 최근 해부터 거꾸로 비교 — 늘면 +1, 같으면 계속, 줄거나 None이면 멈춤. 최근 해 DPS가 None이면 None.
- `grade`: total > grade_a → A, > grade_b → B, > grade_c → C, 아니면 D.
- `rank`: 점수 내림차순 → 주가÷적정가 오름차순(None 뒤) → 코드.

- [ ] **Step 1: 테스트**

```python
def test_step_points_each_op():
    per = ItemRule(15, ((5, 15), (8, 11), (10, 7), (15, 3)))
    assert [step_points(v, per, "lt") for v in (4.9, 5, 7.9, 14.9, 15, 40)] == [15, 11, 11, 3, 0, 0]
    ratio = ItemRule(15, ((0.75, 15), (0.9, 10), (1.0, 6), (1.2, 3)))
    assert step_points(0.75, ratio, "le") == 15 and step_points(0.76, ratio, "le") == 10
def test_dividend_streak_counts_raises_and_skips_freezes():
    assert dividend_streak((100, 100, 120, 120, 130), (130, 150, 150, 160, 170)) == 5
    assert dividend_streak((None,) * 5, (100, 90, 100, 110, 120)) == 3
    assert dividend_streak((None,) * 5, (100, 100, 100, 100, None)) is None
def test_score_full_example():
    # 합성 StockResult(가격 30,000, EPS 5년 [3000,3200,3500,3600,4000], pbr 0.5, B108 0.7, B78 12, B115 0.055,
    # DPS 10년 꾸준히 인상 6회) + ScoreFacts(ttm_eps 4200, payout 4, buyback 3년 True, cancelled 1.6%, treasury 0, subsidiaries ())
    s = score_stock(r, facts, ScoreSettings())
    assert s["groups"] == {"cheap": 11 + 4 + 15, "steady": 7 + 5 + 5, "return": 7 + 4 + 5 + 7 + 5 + 5, "other": 5}
    assert s["total"] == 85 and s["grade"] == "A" and s["missing"] == 0
def test_loss_year_gives_zero_not_error(): ...    # 최근 EPS −100 → per 0 "적자", ttm 0
def test_missing_facts_are_no_data_and_counted(): ...   # facts None → missing == 5+5+7+8+5+5
def test_not_eligible_when_quick_fail_or_no_latest_dividend(): ...
def test_grade_boundaries_are_strict(): assert grade(80, ScoreSettings()) == "B" and grade(80.5, ScoreSettings()) == "A"
def test_rank_order(): ...
def test_judgment_items_are_four_with_go_ava_points(): assert [j[0] for j in JUDGMENT] == ["sustain", "growth", "management", "brand"]
```

- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현. `rule` 글은 설정에서 만든다(예: `"5 미만 15 · 8 미만 11"`).
- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: score stocks from calculator cells and DART facts`

---

### Task 6: 연결 — cli, payload, 스냅샷

**Files:**
- Modify: `src/vsf/cli.py` (`_weekly_run`), `src/vsf/report/payload.py`, `src/vsf/snapshot.py`
- Test: `tests/test_payload.py`, `tests/test_snapshot.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 `gather_score_facts`, `normalize_name`; Task 5 `score_stock`, `rank`, `eligible`, `JUDGMENT`, `GROUPS`.
- Produces:
  - `build_payload(run, changes, crit_changes, prev, extras, settings, scores: dict[str, dict] | None = None, score_partial: bool = False)`
  - payload 새 키: `"score_rank": [code…]`(전체, 순위 순), `"score_summary": {"eligible": n, "A": n, "B": n, "C": n, "D": n, "partial": bool, "top_n": int, "settings_changed": bool, "groups": [[key, label], …], "judgment": [[key, 질문, [선택지…], [점수…]], …]}`, `stocks[code]["score"]`(dict 또는 None), `stocks[code]["score_prev"]`(지난주 total 또는 None)
  - `save_snapshot(run, runs_dir, carry_from=None, scores: dict[str, dict] | None = None)` — 종목 문서에 `"score": total 또는 None`. 옮겨 온 종목은 지난 값 유지.
  - `SnapStock.score: float | None = None` (예전 파일은 None)
- 흐름(`_weekly_run`): `evaluate` → `eligible` 코드 목록 → `listed_names` 만들기(KRX `listed(price_date)` 이름 + `dart.corp_names()`) → `gather_score_facts` → `scores = {code: score_stock(...)}` (자격 없는 종목은 None) → payload·스냅샷. 끝 출력에 "점수 대상 N개, A n·B n" 한 줄 추가.
- `settings_changed` = 지난 스냅샷이 있고 `prev.settings_fp.get("score") != run.settings_fp["score"]`. 이때 `score_prev`는 모두 None.

- [ ] **Step 1: 테스트**

```python
def test_payload_score_rank_and_summary(): ...          # 점수 2개·None 1개 → rank 2개, A/B/C/D 수, judgment 4개
def test_score_change_hidden_when_score_settings_changed(): ...
def test_snapshot_stores_score_and_carries_it(tmp_path): ...
def test_old_snapshot_without_score_reads_none(tmp_path): ...
def test_weekly_run_report_has_scores(tmp_path): ...    # FakeDart에 점수 자료 넣고 data.js에 score_rank 존재
def test_weekly_run_score_quota_is_partial(tmp_path): ...
```

- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현. `SCHEMA`는 그대로 1(새 키만 추가, JS가 없으면 감춤).
- [ ] **Step 4:** `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: score ranking in the weekly payload and snapshot`

---

### Task 7: 리포트 화면

**Files:**
- Modify: `src/vsf/report/assets/report.js`, `src/vsf/report/assets/report.css`
- Test: `tests/js/report.test.js`, `tests/js/sample_data.js`

**Interfaces:**
- Consumes: Task 6 payload 키.
- Produces: `scoreTable(data)`, `scoreBox(s, data)`, `judgmentBox(data)`; `renderIndex` 순서 = 머리 → 배너 → 타일 → **점수 순위** → 이번 주 변화 → '계산기 관문 기준' 제목 아래 관심 목록·아깝게 탈락 → 검색 → 제외 목록.

- 점수 순위 표: 열 = 순위, 종목(+ 숫자 확인 필요·최근 실적 미달·금융 칩), 점수(등급), 싼가·꾸준·환원·기타, 자료 없는 배점, 지난주 대비(▲n/▼n/—, settings_changed면 "배점 바뀜"), PER, 배당수익률, 주가÷적정가, 관문 ①②③ 배지. 처음 `top_n`개, 나머지는 `<details><summary>전체 N개 보기</summary>`.
- 배너: `score_summary.partial`이면 "점수 자료를 다 받지 못했어요. 내일 다시 실행하면 이어서 받아요. '자료 없음' 항목은 0점으로 더했어요." (warn)
- 타일: "점수 대상", "A등급", "B등급" 추가.
- 카드: 관문 배지 줄에 `점수 62 · C` 칩. 가격 상자·최근 실적 배너 다음에 `<h3>점수</h3>` + 점수표(항목·값·구간·점수/배점·출처, no_data는 '자료 없음' 칩) + 묶음 합계 + "자료 없는 배점 N점". 그 다음 `<h3>점수에 없는 판단</h3>` 상자: JUDGMENT 네 질문과 선택지, 문구 "이 네 가지는 점수에 넣지 않았어요. `/자문`에서 꼭 같이 봐요."
- 점수 없는 카드(quick_fail 포함): "최근 해 배당 없음 — 점수 대상 아님". `quickFailCard` 안내 글을 "최근 해에 배당을 주지 않아 먼저 걸렸어요. 나머지 숫자는 받지 않았어요."로.
- 예전 data.js(키 없음): 점수 표·칩·상자를 그리지 않는다(오류 없음).

- [ ] **Step 1: 테스트** — sample_data.js에 `score_rank`, `score_summary`, 종목 A·B의 `score`를 더하고:

```js
test('score ranking is the first table', () => { const h = r.renderIndex(data); assert.ok(h.indexOf('점수 순위') < h.indexOf('관심 목록')); });
test('score table shows grade, missing points, change', ...);
test('partial score banner', ...);
test('card shows score table and judgment box', () => { const h = r.renderStock(data, 'A'); for (const s of ['점수', '자료 없는 배점', '점수에 없는 판단', '미래 성장 잠재력', '/자문']) assert.ok(h.includes(s), s); });
test('no score card says not eligible', ...);
test('old data without score keys renders', () => { const d = { ...data }; delete d.score_rank; delete d.score_summary; assert.ok(!r.renderIndex(d).includes('점수 순위')); });
```

- [ ] **Step 2:** `node --test tests/js/` → FAIL.
- [ ] **Step 3:** 구현. 기존 `chip`·`gateBadge`·`fmt`·`wrap`을 쓴다. 등급 칩 색은 report.css에 A~D 4개 클래스.
- [ ] **Step 4:** `node --test tests/js/` 와 `uv run pytest -q` → PASS.
- [ ] **Step 5: 커밋** `feat: score ranking and score card in the report`

---

### Task 8: `/자문`, README, 설계 메모

**Files:**
- Modify: `.claude/skills/자문/scripts/card.py`, `.claude/skills/자문/SKILL.md`, `README.md`, `docs/superpowers/specs/2026-11-14-weekly-dividend-screener-design.md`

- [ ] **Step 1:** `card.py`가 카드의 `score`(총점·등급·묶음·항목 표·자료 없는 배점)와 data.js의 `score_summary.judgment` 네 항목(질문·선택지·평가표 배점)을 출력. 점수 없는 종목은 "점수 대상 아님". 실행 확인: `uv run python .claude/skills/자문/scripts/card.py 316140` (리포트를 새로 만든 뒤).
- [ ] **Step 2:** SKILL.md 답 형식 표에 두 줄 추가(스펙 9장): 2 다음 "점수"(총점·등급·놓친 배점 큰 순서와 이유), 6 다음 "점수에 없는 판단 (빠뜨리지 않아요)"(네 항목 각각 사실 → 해석 → 평가표 선택지 중 답 후보 → 근거 강도, 근거 없으면 "모르겠음"), 맨 끝 참고 "평가표 기준이라면: 자동 점수 + 판단 후보 점수 = N점"(리포트 점수와 섞지 않음). 번호를 다시 매긴다. '자주 하는 실수'에 "점수가 높으니 싸다 → 놓친 배점과 판단 항목을 같이 봐요".
- [ ] **Step 3:** README: '리포트 보는 법'에 점수 순위·점수표·점수에 없는 판단 설명, '기준 바꾸기'에 `[score]`, '/자문' 진행 순서에 판단 항목. 사용자가 써 둔 문장(8·10행 등)은 그대로 둔다.
- [ ] **Step 4:** 원래 설계 문서 끝에 `2026-11-23: 점수 순위 추가 — docs/superpowers/specs/2026-11-23-score-ranking-design.md` 한 줄.
- [ ] **Step 5:** `uv run pytest -q`, `node --test tests/js/` → PASS. 커밋 `docs: score ranking in /자문 and the README` (README는 사용자 변경과 함께 들어가니, 커밋 전 diff를 보고 사용자 문장이 남아 있는지 확인).

---

### 끝난 뒤 (스펙 12장)

- 실제 주간 실행(`uv run run.py --no-open`)으로 점수 자료를 받는다. 한도에 걸리면 다음 날 이어서.
- 상위 30개와 등급별 수를 사용자와 같이 보고 `[score]`를 조정, 스펙 끝에 날짜와 함께 기록.
