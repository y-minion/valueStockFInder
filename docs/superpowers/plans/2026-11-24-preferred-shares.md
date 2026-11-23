# 우선주 배당 종목 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KRX 우선주(구형·신형·종류주권)를 보통주 재무 + 우선주 주가·배당으로 계산기에 돌려 관문·점수·리포트에 넣는다.

**Architecture:** `assemble()`에 `preferred: PreferredShare | None`을 더해 같은 조립 경로를 쓴다. `collect`는 보통주를 다 처리한 뒤 우선주를 처리한다. 업종·기준 점검은 보통주만 센다. KRX 시세에 거래대금을 더해 '거래 적음' 칩을 단다.

**Tech Stack:** Python 3.13 / uv, pytest, vanilla JS + node --test.

**Spec:** `docs/superpowers/specs/2026-11-24-preferred-shares-design.md`

## Global Constraints

- 공식 API만. 키 출력 금지. 보통주 판정·엑셀 판정 일치·점수 규칙은 바꾸지 않는다.
- 사용자에게 보이는 글은 한국어 해요체.
- `PriceRow`에 필드를 더할 때 기본값을 둬서 기존 6개 인자 생성이 깨지지 않게 한다.
- 저장된 sqlite(`data/vsf.sqlite3`)는 지우지 않는다. 표에 칸을 더할 때는 `ALTER TABLE … ADD COLUMN`으로 기존 자료를 지킨다.

## Review Focus

1. 우선주 종류가 여럿인 회사 → 모두 DART '우선주' 한 줄 DPS를 쓰고 카드에 한계를 적는다 (Task 2·5 테스트).
2. 하루 한도로 보통주 도중 멈춤 → 남은 우선주는 제외가 아니라 pending (Task 3 `test_quota_defers_preferred_to_pending`).
3. 같은 회사를 업종 통계에 두 번 세지 않는다 (Task 4 `test_industry_counts_common_only`).
4. 예전 sqlite(거래대금 칸 없음) → 자동으로 칸을 더하고 기존 시세는 그대로 (Task 1 `test_old_price_table_gets_value_column`).
5. 예전 data.js(우선주 키 없음) → 화면 오류 없음 (Task 5 JS).

---

### Task 1: KRX 거래대금
**Files:** `src/vsf/data/store.py`, `src/vsf/data/krx.py`, `src/vsf/liquidity.py`(새), 테스트 `tests/test_store.py`·`tests/test_krx.py`·`tests/test_liquidity.py`
**Produces:**
- `PriceRow.value: float | None = None` (그날 거래대금, 원)
- store `prices` 표에 `value REAL` 칸 (없으면 ALTER로 추가), put/get이 읽고 씀
- `KrxClient.daily(day, need_value: bool = False)`: 캐시된 날인데 그날 행의 거래대금이 모두 None이고 `need_value`면 다시 받아 저장
- `liquidity.average_value(krx, codes: set[str], until: date, weeks: int = 13) -> dict[str, tuple[float, int]]`: 주말 거래일(`week_ends`) + `until`의 거래대금 평균과 날 수. 값 없는 날은 뺀다.
- `THIN_TRADING_WON = 100_000_000`
- [ ] 테스트: value 왕복, 옛 표에 칸 추가, need_value 재요청 1회, 평균·날 수 계산 → RED → 구현 → GREEN → 커밋 `feat: KRX trading value for a thin-trading check`

### Task 2: 우선주 조립
**Files:** `src/vsf/data/assemble.py`, 테스트 `tests/test_assemble.py`
**Produces:**
- `PreferredShare(code: str, name: str, price: PriceRow, year_end: dict[int, PriceRow])` (frozen)
- `CompanyInfo.common_code: str | None = None`
- `assemble(..., preferred: PreferredShare | None = None)`: DPS는 '우선' 줄, 연말 PER은 우선주 종가 × 보통주 주식 수 보정 ÷ EPS, PBR·가격·이름·코드는 우선주, 분할 확인은 보통주. 출처 글은 "우선주", 메모 앞에 "우선주: 재무는 보통주(코드) 것, 주가·배당은 우선주." 노트 `PREF_NOTE`(우선주 종류가 여럿이면 같은 배당).
- `quick_fail_check(rows, year, kind="보통")`, `assemble_quick_fail(..., kind="보통")`
- [ ] 테스트: 우선주 DPS 줄 선택, PER·PBR이 우선주 가격, EPS·ROE는 보통주와 같음, 우선 줄 없으면 확인 표시, quick fail kind → RED → 구현 → GREEN → 커밋 `feat: assemble a preferred share from company financials and its own price and dividends`

### Task 3: 수집
**Files:** `src/vsf/collect.py`, `tests/fakes.py`, 테스트 `tests/test_collect.py`
**Produces:**
- `preferred_base(code: str) -> str` (앞 다섯 자리 + "0")
- `collect`: 목록에서 우선주(`listing_exclusion == "우선주"`)는 따로 모아 보통주 뒤에 `_process(ctx, item, common=base)`로 처리. 보통주 단계에서 한도에 걸리면 우선주 전부 pending. `_defer`는 우선주를 제외가 아니라 pending으로.
- `collect_one`: 우선주 코드도 처리.
- [ ] 테스트: 우선주 레코드(common_code, 우선주 가격·DPS), 보통주 없음→회사 사유로 제외/실패, 한도→pending, collect_one 우선주 → RED → 구현 → GREEN → 커밋 `feat: collect preferred shares after their companies`

### Task 4: 평가·업종·기준 점검
**Files:** `src/vsf/evaluate.py`, `src/vsf/criteria_check.py`, 테스트
- 업종 표는 `common_code is None`인 레코드만으로 만들고, 우선주는 `table.get(common_code)`.
- `criteria_check` 모집단에서 우선주 제외.
- [ ] 테스트 `test_industry_counts_common_only`, `test_criteria_check_skips_preferred` → 커밋 `feat: count each company once in industry and criteria checks`

### Task 5: payload·cli·리포트
**Files:** `src/vsf/report/payload.py`, `src/vsf/cli.py`, `src/vsf/report/assets/report.js`·`report.css`, 테스트 `tests/test_payload.py`·`tests/test_cli.py`·`tests/js/*`
**Produces:** 종목 payload에 `share_class`("보통"|"우선"), `common_code`, `common_price`, `common_dps`(최근 해), `liquidity`({"avg": 원, "days": n} 또는 null), payload `run.thin_trading_won`.
- cli: 우선주와 그 보통주 코드에 대해 `average_value` 계산(실패해도 리포트는 계속).
- JS: 목록 칩 '우선주'·'거래 적음', 카드 머리 링크, '우선주' 상자(보통주 주가·할인율·DPS 비교·거래대금·한계 문장). 예전 data.js 호환.
- [ ] 테스트 → 커밋 `feat: preferred shares in the report`

### Task 6: /자문·README·설계 메모
- card.py가 우선주면 보통주 코드·할인율·한계 문장을 출력. README 분석 대상·리포트 읽기에 우선주. 원래 설계에 한 줄.
- [ ] 커밋 `docs: preferred shares in /자문 and the README`

### 끝난 뒤
- 실제 실행(`uv run run.py --no-open`), 우선주 순위·현대차2우B 확인, 사용자에게 보고.
