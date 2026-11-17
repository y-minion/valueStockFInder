# Financial Companies, Boundary Marks and Criteria Check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze financial holdings, banks, insurers, securities and card/capital companies with sector criteria. Mark values within one step of a threshold. Add a criteria check page with one-step what-ifs.

**Architecture:**
- Collection classifies each company (`universe.py` + `collect.py`), and the kind rides on `CompanyInfo.financial_kind`.
- `engine.compute` takes an optional `FinancialGate` and overlays the sector verdicts between gate ② and gate ③, so the glance text (B7, B8, B15) follows them.
- With `financial=None`, `engine.compute` stays the exact Excel port.
- Boundary marks and the criteria check are views computed after evaluation, in their own modules, and shipped in `data.js`.

**Tech Stack:** Python 3.13 via `uv`, stdlib dataclasses/statistics; plain browser JS (`report.js`) tested with `node:test`.

**Spec:** `docs/superpowers/specs/2026-11-15-financial-companies-and-criteria-checks-design.md` (extends `docs/superpowers/specs/2026-11-14-weekly-dividend-screener-design.md`).

## Global Constraints

- All user-facing text is plain Korean in the style of the existing copy.
- Missing numbers stay `None`, never 0.
- "해당 없음" is used only for:
  - the four fields that do not fit financial companies (부채비율, 이자보상배율, 영업현금흐름, 설비투자);
  - the gate rows built on those fields (D79, D80, D81, D89).
- `compute(inputs, criteria, extra_gate1)` with `financial=None` returns exactly what it returns today. Every existing engine/oracle/export test stays green without edits.
- Boundary marks never change a verdict or a state.
- `[financial] include = false` reproduces today's behavior exactly:
  - non-holding companies with industry codes 64/65/66 → excluded "금융회사";
  - holding companies without current assets → excluded "금융지주".
- Never print, log or commit API keys. Tests never read `keys.toml`. Never modify the original calculator file.
- Before every commit: `uv run pytest -q` and `node --test tests/js/` are both green.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01N6v6w6xPXU2yu2wnS62Ax7
  ```

## Review Focus

1. A financial company with a blank net-income year (e.g. newly listed): the loss check is '입력 필요' and gate ① is '확인 필요'. The blank alone never makes it '탈락'. (Task 4: `test_loss_year_fails_and_blank_year_needs_input`)
2. `include = false` gives the old exclusions. Old snapshots and old `data.js` (no financial fields) still load and render. (Task 2: `test_include_false_keeps_old_exclusions`; Task 5: `test_old_snapshot_without_financial_reads_none`; Task 7: `old data without financial fields still renders`)
3. A financial stock carried from last week (partial run) or exported with `--excel` from the snapshot gets the sector verdict, not the general one. (Task 5: `test_carried_financial_stock_counts_with_sector_verdict`; Task 6: `test_excel_from_snapshot_notes_sector_verdict`)
4. Payout near a bound is compared after rounding to 2 decimals, as the engine does. (Task 8: `test_payout_compared_after_rounding`)
5. Criteria check edge cases. (Task 9: `test_partial_quick_fail_and_invalid_variant`)
   - A partial run is marked `partial`.
   - Quick-fail stocks are not counted.
   - A variant that would make `payout_min ≥ payout_max` is reported as `None`, not a crash.

---

### Task 1: `[financial]` settings

**Files:**
- Modify: `src/vsf/config.py`, `settings.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class FinancialSettings: include: bool = True; bank_cet1_min: float = 9.0; insurer_kics_min: float = 130.0; securities_ncr_min: float = 100.0`
  - `Settings.financial: FinancialSettings = FinancialSettings()`. This is a new last field, so existing `Settings(...)` calls keep working.
  - `settings_fingerprint(s)` gains the key `"financial": asdict(s.financial)`.
  - `CRITERIA_LABELS` gains these entries:
    - `"include": "금융회사 포함"`
    - `"bank_cet1_min": "은행·금융지주 보통주자본비율 최소"`
    - `"insurer_kics_min": "보험 지급여력비율 최소"`
    - `"securities_ncr_min": "증권 순자본비율 최소"`

- [ ] **Step 1: Write the failing tests**

```python
def test_financial_defaults_and_fingerprint(tmp_path):
    s = load_settings(write_settings(tmp_path))
    assert s.financial == FinancialSettings(True, 9.0, 130.0, 100.0)
    assert settings_fingerprint(s)["financial"] == {
        "include": True, "bank_cet1_min": 9.0, "insurer_kics_min": 130.0, "securities_ncr_min": 100.0}

def test_shipped_settings_have_financial_defaults():
    assert load_settings(Path("settings.toml")).financial == FinancialSettings()

@pytest.mark.parametrize("body,msg", [
    ('include = "yes"', "true 또는 false여야 해요"),
    ("bank_cet1_min = 0", "0보다 커야 해요"),
    ('insurer_kics_min = "130%"', "숫자여야 해요"),
    ("unknown = 1", "알 수 없는 항목이에요")])
def test_financial_bad_values(tmp_path, body, msg):
    path = write_settings(tmp_path)
    text = path.read_text(encoding="utf-8")
    # the copied settings.toml already has a [financial] table: replace its body
    head, _, _ = text.partition("[financial]")
    path.write_text(head + "[financial]\n" + body + "\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_settings(path)
    assert "[financial]" in str(e.value) and msg in str(e.value)
```

`[financial]` must be the last table in `settings.toml` so the `partition` above keeps every other table.

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_config.py -q`
  - Expected: FAIL (`FinancialSettings` is undefined).

- [ ] **Step 3: Implement**
  - Add `"financial"` to `_SECTIONS`.
  - Parse `[financial]` after `[dart]`.
  - `include` follows the `[industry] use_in_verdict` pattern, with the message "true 또는 false여야 해요.".
  - The three minimums go through `_checked`. They are not rate keys, so each must be greater than 0.
  - Unknown keys go through `_no_unknown("[financial]", …)`.
  - Append the block from spec §3.5 verbatim (with its comments) as the last table of `settings.toml`.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: [financial] settings for sector criteria`

---

### Task 2: Classify financial companies during collection

**Files:**
- Modify: `src/vsf/data/universe.py`, `src/vsf/data/assemble.py` (one `CompanyInfo` field only), `src/vsf/collect.py`, `src/vsf/cli.py` (pass the flag)
- Test: `tests/test_universe.py`, `tests/test_collect.py`

**Interfaces:**
- Consumes: `FinancialSettings.include` (Task 1).
- Produces:
  - `FINANCIAL_KINDS = ("금융지주", "은행", "보험", "증권", "카드·캐피탈")` in `universe.py`.
  - `def financial_kind(company: dict) -> str | None`. It is for non-holding companies only. By `induty_code` prefix:
    - "641" → "은행"
    - "651" or "652" → "보험"
    - "6612" → "증권"
    - "6491" → "카드·캐피탈"
    - any other "64"/"65"/"66" code → "그 밖"
    - "64992" (holding) and non-financial codes → `None`
  - `def is_financial_holding(fin: FinRows | None) -> bool`. True when `fin` is not None and its latest balance sheet has no current-assets line (today's `holding_exclusion` rule). Remove `holding_exclusion` and move its tests to this name.
  - `def company_exclusion(company: dict, include_financial: bool = True) -> str | None`.
    - The `acc_mt` rule is unchanged.
    - For a non-holding financial company:
      - `include_financial=True`: kind "그 밖" → "금융회사(그 밖)"; the five supported kinds → `None`.
      - `include_financial=False`: → "금융회사".
  - `CompanyInfo.financial_kind: str | None = None`. This is a new last field. It holds a value only for the five kinds.
  - Signatures:
    - `collect(dart, krx, store, today, progress=print, *, include_financial: bool = True)`
    - `collect_one(dart, krx, store, today, code, *, include_financial: bool = True)`
    - `_Context.include_financial: bool`
  - `_process` changes:
    - Compute the kind from `financial_kind(raw)`.
    - For a holding, after `fin_a` is fetched and `is_financial_holding(fin_a)` is true:
      - when included, the kind is "금융지주";
      - otherwise raise `_Excluded("금융지주")`.
    - Quick-fail stops before statements are fetched. So a quick-failed holding keeps `financial_kind=None`, while non-holding financials keep their kind.
    - A holding whose statements are missing still fails with `NO_FIN` (spec §9 rule 5).
  - `cli._weekly_run` and `cli._excel` pass `include_financial=settings.financial.include`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("code,kind", [
    ("64121", "은행"), ("65110", "보험"), ("65121", "보험"), ("65200", "보험"), ("66121", "증권"),
    ("64911", "카드·캐피탈"), ("64201", "그 밖"), ("6419", "그 밖"), ("66", "그 밖"),
    ("64992", None), ("30121", None), ("", None)])
def test_financial_kind(code, kind):
    assert financial_kind({"induty_code": code}) == kind

def test_company_exclusion_includes_supported_financials():
    assert company_exclusion({"acc_mt": "12", "induty_code": "64121"}) is None
    assert company_exclusion({"acc_mt": "12", "induty_code": "64201"}) == "금융회사(그 밖)"
    assert company_exclusion({"acc_mt": "12", "induty_code": "64121"}, include_financial=False) == "금융회사"
```

In `tests/test_universe.py`:
- Make the existing parametrized `test_company_exclusion` call `company_exclusion(co, include_financial=False)`. Its expectations stay as they are, which pins the old behavior.
- Rename the `holding_exclusion` tests to `is_financial_holding` with True/False expectations.

In `tests/test_collect.py`:

```python
def test_financial_companies_are_analyzed_with_their_kind():
    c = run(FakeDart({"000270": FakeDart.entry(induty_code="64121")}))
    assert c.records["000270"][0].financial_kind == "은행"

def test_financial_holding_is_analyzed_as_its_kind():
    bank_holding = synthetic(defaults=False)
    c = run(FakeDart.with_company("000270", induty_code="64992", fin={2025: bank_holding, 2023: bank_holding}))
    assert c.records["000270"][0].financial_kind == "금융지주" and c.excluded == {}

def test_include_false_keeps_old_exclusions():
    c = collect(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, progress=noop,
                include_financial=False)
    assert set(c.excluded) == {"우선주", "스팩", "금융회사", "결산월 12월 아님"}
    bank_holding = synthetic(defaults=False)
    held = collect(FakeDart.with_company("000270", induty_code="64992", fin={2025: bank_holding, 2023: bank_holding}),
                   FakeKrx.default(), mem_store(), D, progress=noop, include_financial=False)
    assert held.excluded == {"금융지주": [("000270", "기아")]}

def test_holding_without_statements_fails_instead_of_general_verdict():
    c = run(FakeDart.with_company("000270", induty_code="64992", fin={}))
    assert [f[0] for f in c.failed] == ["000270"] and "000270" not in c.records
```

Update the existing tests:
- `test_exclusions_bucketed` now expects `{"우선주", "스팩", "금융회사(그 밖)", "결산월 12월 아님"}`. The fake company 055550 has industry code "6419", which is "그 밖".
- `test_holding_company_without_current_assets_is_financial_holding` moves into the `include_financial=False` test above.

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_universe.py tests/test_collect.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: classify financial companies instead of excluding them`

---

### Task 3: Leave sector-mismatched numbers blank for financial companies

**Files:**
- Modify: `src/vsf/data/assemble.py`
- Test: `tests/test_assemble.py`

**Interfaces:**
- Consumes: `CompanyInfo.financial_kind` (Task 2).
- Produces: when `company.financial_kind` is not None, `assemble(...)` changes as follows.
  - Every `YearRow` has `debt_ratio`, `interest_coverage`, `ocf` and `capex` set to `None`.
  - There are no `sources` entries for rows 31, 32, 34 and 35.
  - There are no notes or flags about those four. In particular, there is none of the "…년 이자보상배율은 '이자의 지급'으로 계산했어요" notes.
  - Everything else is as today.
- `assemble_quick_fail` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_financial_company_leaves_sector_mismatched_numbers_blank():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    a = assemble(replace(co, financial_kind="은행"), L, fin_a, fin_b, divs, ye, price, d)
    for y in a.inputs.years:
        assert (y.debt_ratio, y.interest_coverage, y.ocf, y.capex) == (None, None, None, None)
        assert None not in (y.eps, y.roe, y.net_income, y.dividends_paid)
    assert not any(cell[1:] in ("31", "32", "34", "35") for cell in a.sources)
    assert not any("이자보상배율" in n for n in a.notes)
    assert assemble(co, L, fin_a, fin_b, divs, ye, price, d).inputs.years[0].debt_ratio is not None
```

- [ ] **Step 2: Run to verify it fails**
  - Command: `uv run pytest tests/test_assemble.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement.** Skip the four computations when the kind is set. Do not compute them and then drop them, because the interest notes are written during the computation.

- [ ] **Step 4: Run to verify it passes**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: leave debt, coverage and cash-flow numbers blank for financial companies`

---

### Task 4: Sector verdicts in the engine

**Files:**
- Create: `src/vsf/financial.py`
- Modify: `src/vsf/engine.py`, `src/vsf/evaluate.py`
- Test: `tests/test_financial.py` (new), `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `FinancialSettings` (Task 1), `CompanyInfo.financial_kind` (Task 2).
- Produces in `financial.py`:
  - `@dataclass(frozen=True) class CapitalRatio: value: float; base_month: str; source: str`. The value is a percent and `base_month` looks like "2026-09".
  - `@dataclass(frozen=True) class FinancialGate: kind: str; capital: CapitalRatio | None; capital_min: float | None`.
  - `CAPITAL_LABELS = {"금융지주": "보통주자본비율", "은행": "보통주자본비율", "보험": "지급여력비율(K-ICS)", "증권": "순자본비율", "카드·캐피탈": "자본비율"}`
  - `CAPITAL_HELP = "자본비율은 금감원 금융통계정보시스템(fisis.fss.or.kr)이나 사업보고서 '자본적정성'에서 확인해 주세요."`
  - `def financial_gate(kind: str | None, capital: CapitalRatio | None, fs: FinancialSettings) -> FinancialGate | None`. It returns `None` when `kind` is None. `capital_min` by kind:
    - 금융지주, 은행 → `fs.bank_cet1_min`
    - 보험 → `fs.insurer_kics_min`
    - 증권 → `fs.securities_ncr_min`
    - 카드·캐피탈 → `None`
  - `def gate_to_dict(g: FinancialGate | None) -> dict | None` and `def gate_from_dict(d: dict | None) -> FinancialGate | None`. These are a JSON round trip.
  - `FIN_CELLS = ("F_LOSS_B", "F_LOSS_C", "F_LOSS_D", "F_CAP_B", "F_CAP_C", "F_CAP_D", "F_CAP_SRC")`
- Produces in `engine.py`: `compute(inputs, criteria, extra_gate1=None, *, financial: FinancialGate | None = None) -> SheetValues`.
  - With `financial` set, apply the overlay below right after `_gate2` and before `_gate3`, and include `FIN_CELLS` in the output.
  - With `None`, nothing changes. The output has no `FIN_CELLS` keys.
- Overlay rules (exact):
  - Rows built on mismatched fields:
    - B79, B80, B81, B89 = `None`
    - C79, C80, C81, C89 = "해당 없음"
    - D79, D80, D81, D89 = "해당 없음"
  - Loss check, using net income row 33 (B33..F33):
    - `F_LOSS_B` = `float(number of non-blank years ≤ 0)` if any year is non-blank, else `None`.
    - `F_LOSS_C` = "5년 모두 흑자".
    - `F_LOSS_D` = "탈락" if any non-blank value is ≤ 0; else "입력 필요" if fewer than 5 years are non-blank; else "통과".
  - Capital check:
    - `F_CAP_B` = `capital.value`, or `None`.
    - `F_CAP_C` = `f"≥ {capital_min:g}%"`, or "기준 없음" when `capital_min` is None.
    - `F_CAP_D` = "직접 확인" if `capital` or `capital_min` is None; else "통과" if `value ≥ capital_min`; else "탈락".
    - `F_CAP_SRC` = `f"{capital.source} ({capital.base_month} 기준)"` if `capital` is set, else `CAPITAL_HELP`.
  - Gate results:
    - `combine(items)` gives "탈락" if any item is "탈락"; else "확인 필요" if any item is "입력 필요" or "직접 확인"; else "통과".
    - D82 = `combine([D78, F_LOSS_D, F_CAP_D] + ([extra_gate1] if extra_gate1 is not None else []))`
    - D90 = `combine([D86, D87, D88])`
- Produces in `evaluate.py`:
  - `StockResult.financial: FinancialGate | None = None` (new last field).
  - `evaluate_one` passes `financial=financial_gate(company.financial_kind, None, settings.financial)` to `compute` and stores the same gate on the result. Capital stays `None` until Task 11.
  - `state_of(inputs, criteria, extra, report, financial: FinancialGate | None = None)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_financial.py`

```python
BANK = FinancialGate(kind="은행", capital=None, capital_min=9.0)

def _with_net_income(inputs, values):              # {year: value or None}
    years = tuple(replace(y, net_income=values.get(y.year, y.net_income)) for y in inputs.years)
    return replace(inputs, years=years)

def test_general_compute_is_unchanged():
    i = _kia_inputs(60000.0)
    assert compute(i, Criteria()) == compute(i, Criteria(), None, financial=None)
    assert not set(FIN_CELLS) & set(compute(i, Criteria()))

def test_sector_rows_replace_general_rows():
    v = compute(_kia_inputs(60000.0), Criteria(), financial=BANK)
    assert [v[a] for a in ("D79", "D80", "D81", "D89")] == ["해당 없음"] * 4
    assert v["F_LOSS_D"] == "통과" and v["F_CAP_D"] == "직접 확인" and v["F_CAP_SRC"] == CAPITAL_HELP
    assert v["D82"] == "확인 필요" and v["B7"] == "확인 필요"

def test_capital_ratio_pass_and_fail():
    ok = replace(BANK, capital=CapitalRatio(13.2, "2026-09", "FISIS 국내은행 자본비율"))
    v = compute(_kia_inputs(60000.0), Criteria(), financial=ok)
    assert (v["F_CAP_C"], v["F_CAP_D"], v["D82"]) == ("≥ 9%", "통과", "통과")
    assert v["F_CAP_SRC"] == "FISIS 국내은행 자본비율 (2026-09 기준)"
    low = replace(ok, capital=replace(ok.capital, value=8.5))
    assert compute(_kia_inputs(60000.0), Criteria(), financial=low)["D82"] == "탈락"

def test_loss_year_fails_and_blank_year_needs_input():
    loss = _with_net_income(_kia_inputs(60000.0), {2023: -100.0})
    assert compute(loss, Criteria(), financial=BANK)["F_LOSS_D"] == "탈락"
    v = compute(_with_net_income(_kia_inputs(60000.0), {2021: None}), Criteria(), financial=BANK)
    assert v["F_LOSS_D"] == "입력 필요" and v["D82"] == "확인 필요"

def test_gate2_drops_fcf_and_glance_follows_new_gates():
    # capex far above OCF: the general FCF check fails, the sector gate ignores it
    # (the example sheet leaves capex and dividends_paid blank, so set both)
    i = _kia_inputs(60000.0)
    heavy = replace(i, years=tuple(replace(y, capex=(y.ocf or 0) * 10, dividends_paid=1000.0) for y in i.years))
    assert compute(heavy, Criteria())["D90"] == "탈락"
    v = compute(heavy, Criteria(), financial=BANK)
    assert v["D90"] != "탈락" and "관문 ②에서 탈락" not in v["B15"]

def test_extra_gate1_still_counts():
    ok = replace(BANK, capital=CapitalRatio(13.2, "2026-09", "x"))
    assert compute(_kia_inputs(60000.0), Criteria(), "탈락", financial=ok)["D82"] == "탈락"

def test_card_capital_has_no_automatic_check():
    g = financial_gate("카드·캐피탈", None, FinancialSettings())
    v = compute(_kia_inputs(60000.0), Criteria(), financial=g)
    assert g.capital_min is None and (v["F_CAP_C"], v["F_CAP_D"]) == ("기준 없음", "직접 확인")

def test_financial_gate_thresholds_and_round_trip():
    fs = FinancialSettings()
    assert [financial_gate(k, None, fs).capital_min for k in ("금융지주", "은행", "보험", "증권")] == [9.0, 9.0, 130.0, 100.0]
    assert financial_gate(None, None, fs) is None
    g = FinancialGate("보험", CapitalRatio(180.5, "2026-06", "FISIS"), 130.0)
    assert gate_from_dict(json.loads(json.dumps(gate_to_dict(g)))) == g and gate_from_dict(None) is None
```

In `tests/test_evaluate.py`:

```python
def test_evaluate_one_uses_sector_verdict_for_financials():
    co, L, fin_a, fin_b, divs, ye, price, d = synthetic_company()
    bank = replace(co, financial_kind="은행")
    a = assemble(bank, L, fin_a, fin_b, divs, ye, price, d)
    r = evaluate_one(bank, a, settings_with(), None)
    assert r.financial == FinancialGate("은행", None, 9.0) and r.cells["D79"] == "해당 없음"
    assert state_of(a.inputs, r.criteria, None, ReportSettings(), financial=r.financial) == r.state
```

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_financial.py tests/test_evaluate.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.
  - `financial.py` imports `FinancialSettings` from `vsf.config`.
  - `engine.py` imports `FinancialGate`, `FIN_CELLS` and `CAPITAL_HELP` from `vsf.financial`.
  - There must be no import cycle.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass, with existing tests unchanged.

- [ ] **Step 5: Commit** — `feat: sector verdicts for financial companies in the engine`

---

### Task 5: Snapshots and change causes keep the sector verdict

**Files:**
- Modify: `src/vsf/snapshot.py`, `src/vsf/changes.py`
- Test: `tests/test_snapshot.py`, `tests/test_changes.py`

**Interfaces:**
- Consumes (Task 4): `FinancialGate`, `CapitalRatio`, `gate_to_dict`, `gate_from_dict`, `StockResult.financial`, and `state_of(..., financial=)`.
- Produces in `snapshot.py`:
  - `SnapStock.financial: FinancialGate | None = None`.
  - Each stock document gets the key `"financial"`, holding `gate_to_dict(...)` or `null`.
  - `_read` uses `gate_from_dict(s.get("financial"))`, so old files without the key read as `None`.
  - Carried stocks keep their gate.
  - `_carried_counts` passes `financial=h.financial` to `compute`.
- Produces in `changes.py`:
  - `_SECTIONS = ("criteria", "report", "industry", "financial")`.
  - `criteria_changes` skips any section that is absent from `prev_fp`, so it emits no entries for it.
  - `detect_changes` passes a gate to `state_of` for `s_a` and `s_b`:
    - `None` when `cur.financial` is None;
    - `cur.financial` when `p.financial` is None;
    - otherwise `FinancialGate(p.financial.kind, p.financial.capital, cur.financial.capital_min)`, which is last week's data judged with this week's threshold.

- [ ] **Step 1: Write the failing tests**
  - `test_financial_gate_round_trips_through_snapshot`: save a run whose stock has `FinancialGate("보험", CapitalRatio(180.5, "2026-06", "FISIS"), 130.0)`, load it back, and the gate is equal.
  - `test_old_snapshot_without_financial_reads_none`: write a gzip snapshot whose stock document lacks `"financial"`. `load_previous(...).stocks[code].financial is None`.
  - `test_carried_financial_stock_counts_with_sector_verdict`: a held stock has inputs with a loss year (`net_income` −100 in one year) and a gate `FinancialGate("은행", None, 9.0)`. The saved `counts["gate12_ok"]` does not count it. With `financial=None`, the same inputs would count.
  - `test_criteria_changes_skip_missing_financial_section`:
    - `criteria_changes({"criteria": {...}}, {"criteria": {...}, "financial": {...}})` has no financial entries.
    - With `include` True → False in both fingerprints, the result is `[{"key": "include", "label": "금융회사 포함", "old": True, "new": False}]`.
  - `test_change_cause_uses_sector_verdict`:
    - Last week: a bank stock whose inputs include a loss year. Its sector state is "out", while the general verdict would be "buy".
    - This week: the same price, and inputs without the loss year. The state is "buy".
    - The change is `new_buy` with causes `("재무 갱신",)`.

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_snapshot.py tests/test_changes.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: snapshots and change causes keep the sector verdict`

---

### Task 6: Excel export notes the sector verdict

**Files:**
- Modify: `src/vsf/financial.py`, `src/vsf/export_xlsx.py`, `src/vsf/cli.py`
- Test: `tests/test_financial.py`, `tests/test_export_xlsx.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 and `SnapStock.financial` (Task 5).
- Produces `def financial_memo(g: FinancialGate, cells: SheetValues) -> str`. It returns exactly:
  `f"금융회사({g.kind})라 금융업 기준으로 판정했어요: 관문 ① {D82} (ROE 5년 평균 {roe}, 최근 5년 적자 {loss}, {CAPITAL_LABELS[g.kind]} {cap}), 관문 ② {D90}. 부채비율·이자보상배율·현금흐름은 금융회사에 맞지 않아 비워 뒀어요."`
  - `roe` = `f"{B78:.1f}%"`, or "—" when B78 is not a number.
  - `loss` comes from `F_LOSS_D`: "통과" → "없음", "탈락" → "있음", anything else → "확인 필요".
  - `cap` = `f"{value:g}% · {base_month} 기준 · {F_CAP_D}"` when `g.capital` is set, else "직접 확인".
- Produces `export_xlsx(..., extra_note="", flags=(), financial_note: str = "")`.
  - `_memo` order: `inputs.memo`, then flags, then `" " + financial_note` (when not empty), then `NUMBERS_GUIDE`, then the industry part.
- `cli._excel` changes:
  - Gate source:
    - snapshot path: `held.financial`;
    - `collect_one` path: `result.financial` from `evaluate_one`.
  - Compute `full = compute(inputs, criteria, extra, financial=gate)`.
  - Build `flags` from `full` as now.
  - Set `note = financial_memo(gate, full)` if `gate` is set, else "".
  - The exported cells stay `compute(inputs, criteria, None)`. This is the Excel-parity rule.

- [ ] **Step 1: Write the failing tests**

```python
def test_financial_memo_text():
    m = financial_memo(BANK, compute(_kia_inputs(60000.0), Criteria(), financial=BANK))
    assert m.startswith("금융회사(은행)라 금융업 기준으로 판정했어요: 관문 ① 확인 필요 (ROE 5년 평균 ")
    assert "%, 최근 5년 적자 없음, 보통주자본비율 직접 확인), 관문 ② " in m
    assert m.endswith("부채비율·이자보상배율·현금흐름은 금융회사에 맞지 않아 비워 뒀어요.")
```

  - `test_memo_order_with_financial_note` (in `tests/test_export_xlsx.py`): the B23 text is memo + flag + note + guide + industry, in that order.
  - `test_excel_collect_one_notes_sector_verdict` (in `tests/test_cli.py`):
    - Use a fake company with industry code "64121".
    - B23 contains "금융회사(은행)라 금융업 기준으로 판정했어요".
    - The exported D79 evaluates as Excel would ("입력 필요", because the cells are blank). Check it with `compute(inputs, criteria, None)["D79"]`.
  - `test_excel_from_snapshot_notes_sector_verdict`: a snapshot stock carrying a bank gate gives the same note.
  - The existing general-stock `--excel` tests stay unchanged. Add an assertion that their B23 has no "금융업 기준".

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_financial.py tests/test_export_xlsx.py tests/test_cli.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: --excel notes the sector verdict for financial companies`

---

### Task 7: The report shows financial companies

**Files:**
- Modify: `src/vsf/report/payload.py`, `src/vsf/report/assets/report.js`, `tests/js/sample_data.js`
- Test: `tests/test_payload.py`, `tests/js/report.test.js`

**Interfaces:**
- Consumes: `StockResult.financial`, `CAPITAL_LABELS`, `FinancialSettings.include`, `prev.settings_fp`.
- Produces in the payload:
  - `stock["financial"]`: `None`, or `{"kind", "capital_label", "capital_min", "capital": {"value", "base_month", "source"} | None}`.
  - Financial stocks' `cells` already contain `FIN_CELLS`, because they come from `compute`.
  - `run["financial_started"] = prev is not None and "financial" not in prev.settings_fp and settings.financial.include`.
  - Keep `SCHEMA` unchanged. The JS must tolerate missing new fields.
- Produces in `report.js`:
  - `cardHead`: for a financial stock, add `chip(kind + " · 금융업 기준으로 판정했어요", "info")`.
  - `gate1Table` for a financial stock. Rows in this order, as (label | B | C | D):
    1. ROE: row 78, as now.
    2. "최근 5년 적자 없음" | "적자 {F_LOSS_B}년", or "—" | `F_LOSS_C` | `F_LOSS_D`
    3. `capital_label` | `F_CAP_B` + "%" and the base month, or "—" | `F_CAP_C` | `F_CAP_D`
    4. Rows 79–81: `LABELS[row]` | "—" | "해당 없음" | "해당 없음"
    5. The industry row, as now.
    6. The result row 82.
  - When `F_CAP_D` is "직접 확인", put `<p class="muted">` + `F_CAP_SRC` after the table.
  - `gate2Table`: row 89 already holds "해당 없음" in C and D, and B renders "—".
  - `inputTable`: for a financial stock, rows 31, 32, 34 and 35 show "해당 없음" in every year column.
  - `watchTable`: for a financial stock, add `chip("금융", "info")` after `flagChip(s)`.
  - `banners`: when `run.financial_started`, show `banner("금융회사를 금융업 기준으로 분석하기 시작했어요", "info")`.
  - `CRIT_PERCENT` gains "bank_cet1_min", "insurer_kics_min" and "securities_ncr_min".
- `sample_data.js` gains one financial stock: code "105560", name "KB금융", kind "금융지주", capital `null`, with `F_*` cells as `compute` would give.

- [ ] **Step 1: Write the failing tests**

```js
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
```

  Python tests in `tests/test_payload.py`:
  - a financial stock has the `financial` dict and a general stock has `None`;
  - `financial_started` is true only when `prev` exists without a `"financial"` key and `include` is true.

- [ ] **Step 2: Run to verify they fail**
  - Command: `node --test tests/js/ ; uv run pytest tests/test_payload.py -q`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: report cards and first page for financial companies`

---

### Task 8: Boundary marks and the near-miss list

**Files:**
- Create: `src/vsf/boundary.py`
- Modify: `src/vsf/report/payload.py`, `src/vsf/report/assets/report.js`, `tests/js/sample_data.js`
- Test: `tests/test_boundary.py`, `tests/test_payload.py`, `tests/js/report.test.js`

**Interfaces:**
- Consumes: cells from `compute` (with `FIN_CELLS` for financials), `Criteria`, `FinancialGate`, `ReportSettings`.
- Produces in `boundary.py`:
  - `STEPS = {"roe_min": 1.0, "debt_ratio_max": 25.0, "interest_coverage_min": 0.5, "ocf_to_ni_min": 0.1, "payout": 0.05, "fcf_to_div_min": 0.1}`
  - `CAPITAL_STEPS = {"금융지주": 1.0, "은행": 1.0, "보험": 10.0, "증권": 100.0}`
  - `@dataclass(frozen=True) class Boundary: cell: str; label: str; value: float; threshold: float; gap: float; unit: str; passed: bool`
    - `gap` = `round(value − threshold, 4)` in display units.
    - Payout is ×100 with unit "%p". ROE, 부채비율 and 자본비율 use "%p". The ratios use "배".
    - `value` and `threshold` are also in display units.
  - `def boundaries(cells: SheetValues, criteria: Criteria, financial: FinancialGate | None) -> tuple[Boundary, ...]`. Each item compares the same value the engine compares:

    | Cell | Label | Compared as |
    |---|---|---|
    | D78 | "ROE 5년 평균" | B78 ≥ `roe_min` |
    | D79 | "부채비율" | B79 < `debt_ratio_max` |
    | D80 | "이자보상배율" | B80 ≥ `interest_coverage_min` |
    | D81 | "영업현금흐름÷순이익" | numeric B81 ≥ `ocf_to_ni_min` |
    | D88 | "배당성향" | `excel_round(B88, 2)` against the nearest of `payout_min`/`payout_max` |
    | D89 | "잉여현금흐름÷배당" | B89 ≥ `fcf_to_div_min` |
    | F_CAP_D | `CAPITAL_LABELS[kind]` | `F_CAP_B` ≥ `capital_min`; only kinds in `CAPITAL_STEPS` |

    - An item is a boundary when its D verdict is "통과" or "탈락" and |native value − native threshold| ≤ its step. Payout uses native fractions with step 0.05.
    - Items whose D verdict is "입력 필요", "해당 없음" or "직접 확인" are never boundaries.
    - Order follows the table above.
  - `def near_miss_state(cells: SheetValues, bounds: tuple[Boundary, ...], report: ReportSettings) -> str | None`. It returns `None` unless:
    - D82 or D90 is "탈락", and
    - every "탈락" among D78–D81, D86–D89, `F_LOSS_D` and `F_CAP_D` is a failed `Boundary`.

    Otherwise it returns the state with those items passing: "buy" if D110 == "통과"; else "watch" if B109 ≤ `watch_range`; else "out".
- Payload:
  - `stock["boundaries"] = [asdict(b) for b in boundaries(r.cells, r.criteria, r.financial)]`.
  - Top-level `"near_miss"`: the codes with state "out" and `near_miss_state(...)` in ("buy", "watch"), sorted by (ratio is None, ratio, code).
- `report.js`:
  - In both gate tables, after the verdict badge of a boundary row:
    - failed: `chip("경계 · 기준까지 " + fmt(|gap|) + unit, "warn")`
    - passed: `chip("경계 · 기준보다 " + fmt(|gap|) + unit + " 여유", "info")`
  - First page, after the watchlist: `<h2>아깝게 탈락 (기준 한 칸 안쪽)</h2>` with one row per code. Each row is `stockLink` plus its failed boundaries as "{label} {value}{unit sans 'p'} · 기준까지 {|gap|}{unit}", e.g. "ROE 5년 평균 7.6% · 기준까지 0.4%p".
  - Omit the section when the list is empty.

- [ ] **Step 1: Write the failing tests** in `tests/test_boundary.py`, plus JS tests for both chips and the section

```python
def test_roe_just_below_is_a_failed_boundary():
    cells = {"B78": 7.6, "D78": "탈락"}
    assert boundaries(cells, Criteria(), None) == (Boundary("D78", "ROE 5년 평균", 7.6, 8.0, -0.4, "%p", False),)

def test_payout_compared_after_rounding():
    (b,) = boundaries({"B88": 0.595, "D88": "통과"}, Criteria(), None)       # rounds to 0.60 = payout_max
    assert (b.cell, b.threshold, b.gap, b.passed) == ("D88", 60.0, 0.0, True)

def test_far_values_and_unjudged_items_are_ignored():
    cells = {"B78": 12.0, "D78": "통과", "B79": None, "D79": "입력 필요", "D80": "해당 없음"}
    assert boundaries(cells, Criteria(), None) == ()

def test_capital_boundary_uses_kind_step():
    g = FinancialGate("보험", CapitalRatio(125.0, "2026-06", "FISIS"), 130.0)
    (b,) = boundaries({"F_CAP_B": 125.0, "F_CAP_D": "탈락"}, Criteria(), g)
    assert (b.label, b.gap, b.passed) == ("지급여력비율(K-ICS)", -5.0, False)

def test_near_miss_requires_every_failure_borderline():
    cells = {"B78": 7.6, "D78": "탈락", "B79": 300.0, "D79": "탈락", "D82": "탈락", "D90": "통과",
             "D110": "통과", "B109": 0.0}
    assert near_miss_state(cells, boundaries(cells, Criteria(), None), ReportSettings()) is None
    cells.update({"D79": "통과", "B79": 100.0})
    assert near_miss_state(cells, boundaries(cells, Criteria(), None), ReportSettings()) == "buy"
```

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_boundary.py -q ; node --test tests/js/`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass.

- [ ] **Step 5: Commit** — `feat: boundary marks and a near-miss list`

---

### Task 9: Criteria check page

**Files:**
- Create: `src/vsf/criteria_check.py`, `src/vsf/report/assets/criteria.html`
- Modify: `src/vsf/report/payload.py`, `src/vsf/report/assets/report.js`, `tests/js/sample_data.js`
- Test: `tests/test_criteria_check.py`, `tests/test_payload.py`, `tests/js/report.test.js`

**Interfaces:**
- Consumes: `StockResult` (with `.financial`), `Settings`, `STEPS`/`CAPITAL_STEPS` (Task 8), `compute`, `summarize`, `watch_state`.
- Produces `def criteria_check(results: dict[str, StockResult], settings: Settings, partial: bool) -> dict`, with this JSON shape:

```
{"partial": bool,
 "groups": [{"group": "일반 회사" | "금융회사", "n": int, "rows": [Row, ...]}],      # group omitted when empty
 "industry": [{"group_name": str, "size": int, "roe_median": float | None}, ...]}
Row     = {"key": str, "label": str, "threshold": float, "unit": "%" | "배",
           "dist": {"n": int, "p25": float, "median": float, "p75": float} | None,
           "pass_now": int | None, "stricter": Variant | None, "looser": Variant | None}
Variant = {"threshold": float, "pass": int | None,
           "watch_in": [[code, name], ...], "watch_out": [[code, name], ...]}
```

- Population:
  - Results whose `assembled.quick_fail` is False.
  - "일반 회사" is the results with `financial is None`; "금융회사" is the rest.
- Rows:
  - General group, in this order: `roe_min` (B78/D78, %), `debt_ratio_max` (B79/D79, %), `interest_coverage_min` (B80/D80, 배), `ocf_to_ni_min` (numeric B81/D81, 배), `payout_min` and `payout_max` (`excel_round(B88, 2)` ×100 against D88, %), `fcf_to_div_min` (B89/D89, 배), `required_return`, `safety_margin`.
  - Financial group, in this order: `roe_min`, then one capital row per kind present (`bank_cet1_min` covers 금융지주 and 은행; `insurer_kics_min` covers 보험; `securities_ncr_min` covers 증권; the distribution is over `F_CAP_B` and the verdict is `F_CAP_D`), then `payout_min`, `payout_max`, `required_return`, `safety_margin`.
  - Labels come from `CRITERIA_LABELS`.
  - Thresholds and values are in display units: rates ×100.
  - For `required_return` and `safety_margin`: `dist` = `None` and `pass_now` = `None`.
- Steps:
  - Use `STEPS` and `CAPITAL_STEPS`, plus `required_return` 0.01 and `safety_margin` 0.05.
  - "stricter" moves the threshold against the stock: min-type keys `+step`; `debt_ratio_max` and `payout_max` `−step`; `required_return` and `safety_margin` `+step`.
  - "looser" is the opposite move.
- Variant judgement. For every stock in the group:
  - Change only that criterion by the delta, starting from the stock's own effective criteria (`dataclasses.replace`). For capital, use `replace(gate, capital_min=gate.capital_min ± step)`.
  - Recompute `watch_state(summarize(compute(inputs, criteria2, extra_gate1, financial=gate2)), settings.report)`.
  - `pass` = the count of "통과" in the row's D cell. It is `None` for `required_return` and `safety_margin`.
  - `watch_in` and `watch_out` = stocks entering or leaving {"buy", "watch"} compared with their current state, as `[code, name]` sorted by code.
  - The whole variant is `None` when, for any stock, the change would make `payout_min ≥ payout_max` or push a rate key outside (0, 1).
- `dist`:
  - `n == 0` → `None`;
  - `n == 1` → p25 = median = p75 = the value;
  - else `statistics.quantiles(values, n=4, method="inclusive")`.
- `industry`: unique `r.industry` groups (`group_name`, `size`, `roe_median`), sorted by size descending, then name.
- Payload: top-level `"criteria_check" = criteria_check(run.results, settings, partial=bool(run.collected.pending))`.
- `criteria.html`: `index.html` with `<title>기준 점검</title>`.
- `report.js`:
  - Boot `renderCriteria(data)` when the path ends with "criteria.html".
  - `criteriaLine` appends `<a href="criteria.html">기준 점검</a>`.
  - When `partial`: `banner("일부만 분석해서 참고만 하세요", "warn")`.
  - One table per group, with the columns 기준 | 지금 기준 | 분포 (25%·중간·75%) | 통과 | 한 칸 엄하게 | 한 칸 느슨하게.
    - Each variant cell shows the threshold, the pass count, and the watchlist change as "+{n}/−{n}".
    - A missing variant shows "계산 안 함".
  - Under each table, list the `watch_in`/`watch_out` names per variant.
  - Data without `criteria_check` shows "이 리포트에는 기준 점검 자료가 없어요".
- `write_report` already copies every asset file. Verify that `criteria.html` lands next to `index.html`.

- [ ] **Step 1: Write the failing tests** in `tests/test_criteria_check.py`
  - Build results with a local helper `_result(code, name, inputs, settings, financial_kind=None)` that calls `evaluate_one` with:
    - `CompanyInfo("99" + code, code, name, "KOSPI", "30121", "12", financial_kind)`;
    - `Assembled(inputs, (), (), {}, False, 2025)`.
  - Vary ROE by replacing `YearRow.roe` in `_kia_inputs(...)`.
  - Tests:
    - `test_distribution_and_pass_counts`: three stocks with ROE averages 6, 8.5 and 12.
      - The `roe_min` row has dist median 8.5 and `pass_now` 2.
      - "stricter" has threshold 9.0 and pass 1.
      - "looser" has threshold 7.0 and pass 2.
    - `test_watchlist_changes_on_one_step`: a stock with ROE 7.6 that is priced inside the watch range. It appears in `looser.watch_in` of the `roe_min` row.
    - `test_partial_quick_fail_and_invalid_variant`:
      - a quick-fail result is not counted;
      - `partial=True` is echoed;
      - with `payout_min` 0.55 and `payout_max` 0.60, the `payout_min` row's "stricter" is `None`.
    - `test_financial_group_rows`: a bank with `CapitalRatio(13.2, …)`. The financial group has a `bank_cet1_min` row with `pass_now` 1 and no `debt_ratio_max` row.
  - JS tests:
    - the page renders both groups;
    - the partial banner appears;
    - "계산 안 함" appears for a `None` variant;
    - old data without `criteria_check` shows the fallback text.

- [ ] **Step 2: Run to verify they fail**
  - Command: `uv run pytest tests/test_criteria_check.py -q ; node --test tests/js/`
  - Expected: FAIL.

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run to verify they pass**
  - Command: `uv run pytest -q && node --test tests/js/`
  - Expected: all pass. Report the time `criteria_check` takes for 2,000 synthetic results in the task report (target well under 60 s).

- [ ] **Step 5: Commit** — `feat: criteria check page with one-step what-ifs`

---

### Task 10 (controller): Real-data check

The controller runs this task, not an implementer subagent, because it needs the user's DART key.
- Add `"KB금융": "105560", "삼성화재": "000810", "삼성증권": "016360"` to `COMPANIES` in `tools/record_fixtures.py`, and record with `uv run python tools/record_fixtures.py dart`.
- Write `tests/test_financial_recorded.py` with `@pytest.mark.recorded("dart")`. For each of the three companies:
  - the recorded company classifies to its kind: 금융지주 (via `is_financial_holding` on the recorded statements), 보험 and 증권;
  - `assemble` leaves the four fields blank;
  - `compute` with the gate gives D79–D81 "해당 없음", `F_LOSS_D` "통과" and D82 "확인 필요".
- Rerun the functional harness (51 companies plus these three, with fake KRX prices). Check:
  - the financial companies appear with sector verdicts;
  - the general companies' results are unchanged from the 2026-11-15 run.
- Commit: `test: record real DART data for a holding, an insurer and a broker`.

### Task 11 (BLOCKED until the user's FISIS key): Capital ratios from FISIS

Not part of this execution. When the key is in `keys.toml [fisis] auth_key`:
- Add `Keys.fisis`.
- Build a `FisisClient` for `companySearch`, `statisticsListSearch`, `accountListSearch` and `statisticsInfoSearch` (`https://fisis.fss.or.kr/openapi/…json`).
- Name mapping:
  - match the listed name to `finance_cd`;
  - insurers are searched in both H and I;
  - a holding uses its own ratio;
  - cache in the store and refresh monthly.
- Record real responses to fix `listNo`/`accountCd`.
- Add `Assembled.capital`, which `collect` sets.
- Replace `None` with it in `evaluate_one`.
- Get a review.

Until then, every financial company shows "직접 확인" for its capital ratio.
