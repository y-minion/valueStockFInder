# 주간 배당주 스크리너 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uv run run.py` 한 줄로 코스피·코스닥 보통주 전체에 사용자의 엑셀 배당주 계산기(관문 ①②③)를 똑같이 적용하고, 이번 주 변화·관심 목록·종목 상세를 브라우저 HTML 리포트로 보여주며, `uv run run.py --excel 종목코드`로 Numbers에서 열 계산기 파일을 채워 만든다.

**Architecture:**
- 계산 엔진(`vsf.engine`)은 엑셀 `분석_빈칸` 시트의 수식 칸 152개를 그대로 옮긴 순수 함수예요. 정답은 원본 수식을 `formulas` 라이브러리로 계산해 고정해 둔 자료(oracle fixtures)예요.
- 데이터 층(`vsf.data`)은 OpenDART·KRX OPEN API 응답을 SQLite에 저장하고, 계산기 입력(`StockInputs`)을 출처·경고와 함께 조립해요.
- 매 실행 결과를 스냅샷으로 남기고 지난 스냅샷과 비교해 변화와 원인을 구해요. 리포트는 정적 파일(HTML 껍데기 + `data.js` + 브라우저에서 그리는 `report.js`)이에요.
- 엑셀 내보내기는 원본 xlsx를 XML 수준에서 복사·수정해서 그래프와 서식을 지켜요.

**Tech Stack:** Python 3.13 (uv로 실행), httpx, lxml, sqlite3(표준 라이브러리), pytest. 개발용으로 formulas·openpyxl(정답 자료 생성). 리포트는 외부 라이브러리 없는 HTML/CSS/JS(Node 18 `node --test`로 테스트). Numbers 확인은 AppleScript(`osascript`).

**Spec:** `docs/superpowers/specs/2026-11-14-weekly-dividend-screener-design.md`

## Global Constraints

- 실행 명령: `uv run run.py`(주간), `uv run run.py --excel <종목코드>`(내보내기). `--no-open`이면 브라우저·Numbers를 열지 않아요. Python ≥ 3.12.
- 공식 API만 써요: OpenDART `https://opendart.fss.or.kr/api/`, KRX OPEN API `https://data-dbg.krx.co.kr/svc/apis/sto/`, 네이버 검색 API(선택). 화면 긁기는 금지예요.
- 원본 계산기(`settings.toml`의 `paths.calculator`, 기본 `/Users/youngmin/가치투자/배당주_분석_계산기.xlsx`)는 읽기만 해요. 이미 있는 내보내기 파일은 절대 덮어쓰지 않아요.
- 못 가져온 숫자는 `None`(빈칸)이에요. 0은 '실제로 0'일 때만 써요.
- 판정 문구는 엑셀과 글자 하나까지 같아야 해요: `통과` `탈락` `확인 필요` `입력 필요` `직접 확인` `계산 불가` `싸요` `제값` `비싸요` `정상` `비정상` `제외(직접)` `넣음` `뺌`.
- 기본 기준값:
  - 요구수익률 0.10, 안전마진 0.25
  - ROE 최소 8, 부채비율 최대 200, 이자보상배율 최소 3, 영업현금흐름÷순이익 최소 1.0
  - 배당성향 하한 0.20·상한 0.60, 잉여현금흐름÷배당 최소 1.0
  - 비정상인 해 기준 0.5, 개별 종목 비중 상한 0.10
  - 관심 목록 범위 0.20, 근접 0.10
  - 업종 비교를 판정에 넣기: 꺼짐, 최소 묶음 5개
- 단위:
  - 33–36행 금액은 억 원(원 ÷ 1e8, 소수 둘째 자리 반올림)
  - ROE·부채비율은 % 숫자(15.6)
  - PER·PBR·이자보상배율은 소수 둘째 자리
- 대상: 코스피·코스닥 보통주.
  - 제외 사유 문구는 정확히: `우선주`, `리츠`, `스팩`, `투자회사 등`, `금융회사`, `금융지주`, `결산월 12월 아님`.
  - 비금융 지주회사(LG 등)는 남겨요.
- 사용자에게 보이는 글(리포트, 터미널 메시지, 엑셀 메모)은 모두 한국어예요.
- git에 올리지 않는 것: `keys.toml`, `data/`, `reports/`, `exports/`, `.superpowers/`, `.venv/`. 원본 계산기는 저장소에 복사하지 않아요.
- 종목별 기준은 없어요. 기준은 `settings.toml` 공통값 + 업종 단위 덮어쓰기뿐이에요.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 붙여요.
- 키가 필요한 단계(Task 6, 7, 19, 20)에서 `keys.toml`에 키가 없으면, 추측하지 말고 멈춰서 사용자에게 요청해요.

## Review Focus

테스트가 다루지 않으면 실제 사용에서 가장 먼저 문제가 될 다섯 가지예요. 각각 담당 task에 테스트를 넣었어요.

1. **올해 사업보고서를 아직 안 낸(늦게 낸) 회사.** 그 회사의 가장 최근 연도로 5년을 잡아야 해요. 다른 회사의 연도와 섞이면 안 돼요. → Task 13 `test_late_filer_uses_previous_year`
2. **주말·공휴일·아침 일찍 실행해서 오늘 KRX 자료가 없을 때.** 가장 최근 거래일로 물러나고, 그 날짜를 주가 기준일로 써야 해요. → Task 7 `test_latest_trading_day_skips_empty_days`
3. **실행 중 일부 종목에서 네트워크 오류나 API 점검이 날 때.** 그 종목만 '가져오지 못함'으로 남기고 나머지는 계속해야 해요. → Task 13 `test_network_error_isolated_to_one_stock`
4. **파일·시트 이름에 못 쓰는 글자(`/ : * ? [ ] \`)나 31자 넘는 종목명.** 안전한 이름으로 바꿔서 저장해야 해요. → Task 18 `test_unsafe_names_are_sanitized`
5. **`settings.toml`에 잘못된 값을 넣었을 때** (`safety_margin = "25%"`, `1.5`, 오타 난 키). 어떤 항목이 왜 잘못됐는지 한국어로 알려주고, 종료 코드 2로 끝나야 해요. 트레이스백은 보이면 안 돼요. → Task 1 `test_bad_value_message` 외, Task 19 `test_config_error_exit_code`

## 진행 단계 (중간 점검)

- **M1 (Task 1–4):** 계산 엔진이 엑셀 수식과 일치해요. 키 없이 할 수 있어요.
- **M2 (Task 5–13):** 실제 자료로 `StockInputs`를 만들어요. Task 6부터는 키가 필요해요.
- **M3 (Task 14–17):** 스냅샷, 변화, 리포트.
- **M4 (Task 18–20):** 엑셀 내보내기, 명령어, 실제 자료 검증.

---

### Task 1: 프로젝트 뼈대와 설정·키 불러오기

**Files:**
- Create: `pyproject.toml`, `run.py`, `settings.toml`, `keys.example.toml`, `src/vsf/__init__.py`, `src/vsf/model.py`, `src/vsf/config.py`, `tests/test_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `vsf.model.Criteria`: frozen dataclass. 필드와 기본값은 Global Constraints 순서 그대로예요.
    - `required_return=0.10`, `safety_margin=0.25`
    - `roe_min=8.0`, `debt_ratio_max=200.0`, `interest_coverage_min=3.0`, `ocf_to_ni_min=1.0`
    - `payout_min=0.20`, `payout_max=0.60`, `fcf_to_div_min=1.0`
    - `abnormal_ratio=0.5`, `isa_weight_max=0.10`
  - `vsf.config.ReportSettings(watch_range=0.20, near_range=0.10)`
  - `vsf.config.IndustrySettings(use_in_verdict=False, roe_top_percent=50.0, min_group_size=5, overrides: dict[str, dict[str, float]] = {})`
  - `vsf.config.Settings(criteria, report, industry, calculator_path: Path, dart_daily_budget: int, data_dir: Path, reports_dir: Path, exports_dir: Path)`
    - 상대 경로는 `settings.toml`이 있는 폴더 기준이에요.
  - `vsf.config.Keys(dart: str, krx: str, naver_id: str | None, naver_secret: str | None)`
  - `vsf.config.ConfigError(Exception)`: 메시지는 한국어, 사용자에게 그대로 보여줘요.
  - `load_settings(path: Path) -> Settings`
  - `load_keys(path: Path) -> Keys`
  - `settings_fingerprint(s: Settings) -> dict`: `{"criteria": {...}, "report": {...}, "industry": {...}}`, JSON으로 저장 가능.
  - `CRITERIA_LABELS: dict[str, str]`: 키 → 한국어 이름.
    - criteria 11개 + `watch_range`·`near_range`·`use_in_verdict`·`roe_top_percent`·`min_group_size`
    - 예: `"required_return": "요구수익률"`

- [ ] **Step 1: 뼈대 파일 만들기**

`pyproject.toml`:
```toml
[project]
name = "vsf"
version = "0.1.0"
description = "주간 배당주 스크리너"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27", "lxml>=5.2"]

[dependency-groups]
dev = ["pytest>=8.2", "formulas>=1.2", "openpyxl>=3.1.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vsf"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "tests"]   # tests에서 `import tools.dump_formulas`, `from helpers import …`
markers = [
  "template: 원본 계산기 파일이 있어야 도는 테스트 (없으면 건너뜀)",
  "slow: formulas로 엑셀 파일을 다시 계산하는 느린 테스트",
]
```

`run.py`: `from vsf.cli import main` → `raise SystemExit(main())`.

`.gitignore`에 추가: `keys.toml`, `data/`, `reports/`, `exports/`, `.venv/`, `__pycache__/`, `.pytest_cache/`. `.superpowers/`는 이미 있어요.

`keys.example.toml`:
```toml
# 이 파일을 keys.toml로 복사해서 키를 넣어요. keys.toml은 git에 올라가지 않아요.
[dart]
api_key = ""        # OpenDART 인증키 40자리 (필수)
[krx]
auth_key = ""       # KRX OPEN API 인증키 (필수)
[naver]
client_id = ""      # 네이버 검색 API (선택, 비워두면 뉴스는 링크만)
client_secret = ""
```

`settings.toml`:
- `[criteria]` 11개 항목의 기본값을 넣어요.
- 항목마다 엑셀 `기준값` 시트 D열 설명을 한 줄로 줄인 한국어 주석을 달아요.
- 다른 섹션:
  - `[report]`: `watch_range`, `near_range`
  - `[industry]`: `use_in_verdict`, `roe_top_percent`, `min_group_size`
  - `[industry.overrides]`: 비어 있고, 주석 예시 `# "35" = { roe_min = 6 }`
  - `[paths]`: `calculator`, `data_dir = "data"`, `reports_dir = "reports"`, `exports_dir = "exports"`
  - `[dart]`: `daily_budget = 19000`

- [ ] **Step 2: 실패하는 테스트 쓰기** (`tests/test_config.py`)

```python
ROOT = Path(__file__).resolve().parents[1]

def test_shipped_settings_are_excel_defaults():
    s = load_settings(ROOT / "settings.toml")
    assert s.criteria == Criteria()
    assert (s.report.watch_range, s.report.near_range) == (0.20, 0.10)
    assert s.industry.use_in_verdict is False and s.industry.min_group_size == 5
    assert s.calculator_path == Path("/Users/youngmin/가치투자/배당주_분석_계산기.xlsx")
    assert s.dart_daily_budget == 19000

def test_bad_value_message(tmp_path):        # Review Focus 5
    p = write_settings(tmp_path, criteria={"safety_margin": '"25%"'})
    with pytest.raises(ConfigError) as e: load_settings(p)
    assert "safety_margin" in str(e.value) and "숫자" in str(e.value)

def test_rate_out_of_range(tmp_path):
    p = write_settings(tmp_path, criteria={"safety_margin": "1.5"})
    with pytest.raises(ConfigError, match="0보다 크고 1보다 작아야"): load_settings(p)

def test_unknown_key(tmp_path):
    p = write_settings(tmp_path, criteria={"roe_minimum": "8"})
    with pytest.raises(ConfigError, match="roe_minimum"): load_settings(p)

def test_payout_order(tmp_path):
    p = write_settings(tmp_path, criteria={"payout_min": "0.7"})
    with pytest.raises(ConfigError, match="payout_min"): load_settings(p)

def test_industry_override_parsing(tmp_path):
    p = write_settings(tmp_path, overrides='"35" = { roe_min = 6 }')
    assert load_settings(p).industry.overrides == {"35": {"roe_min": 6.0}}
    with pytest.raises(ConfigError, match="roe_minn"):
        load_settings(write_settings(tmp_path, overrides='"35" = { roe_minn = 6 }'))

def test_missing_dart_key(tmp_path):
    (tmp_path / "keys.toml").write_text('[krx]\nauth_key = "x"\n')
    with pytest.raises(ConfigError, match="DART"): load_keys(tmp_path / "keys.toml")

def test_fingerprint_is_json_roundtrip():
    s = load_settings(ROOT / "settings.toml")
    assert json.loads(json.dumps(settings_fingerprint(s)))["criteria"]["required_return"] == 0.10
```

`write_settings(tmp_path, criteria=..., overrides=...)`는 테스트 파일 안의 도우미예요. 배포용 `settings.toml`을 복사한 뒤 해당 줄만 바꿔요.

- [ ] **Step 3: 실패 확인**
  - Run: `uv sync && uv run pytest tests/test_config.py -v`
  - Expected: FAIL (`vsf.config` 없음)

- [ ] **Step 4: `src/vsf/model.py`의 `Criteria`와 `src/vsf/config.py` 구현**
  - 표준 `tomllib`로 읽어요.
  - 값 검사 규칙:
    - 비율 항목(`required_return`, `safety_margin`, `payout_*`, `abnormal_ratio`, `isa_weight_max`, `watch_range`, `near_range`)은 0 < x < 1
    - 나머지 숫자는 > 0
    - `payout_min < payout_max`, `near_range <= watch_range`
    - `0 < roe_top_percent <= 100`, `min_group_size`는 1 이상 정수
  - 모든 오류는 `ConfigError("settings.toml의 [criteria] safety_margin 값이 잘못됐어요: …")` 모양이에요.

- [ ] **Step 5: 통과 확인**
  - Run: `uv run pytest tests/test_config.py -v`
  - Expected: PASS

- [ ] **Step 6: 커밋**
  - `git add pyproject.toml uv.lock run.py settings.toml keys.example.toml .gitignore src tests`
  - `git commit -m "feat: project scaffold with settings and keys loading"`

---

### Task 2: 입력 모델과 정답 자료(oracle)

**Files:**
- Modify: `src/vsf/model.py`
- Create:
  - `tools/dump_formulas.py`, `tools/make_oracle_fixtures.py`
  - `tests/conftest.py`, `tests/helpers.py`, `tests/engine_cases.py`
  - `tests/fixtures/oracle/*.json` (생성물)
  - `tests/test_model.py`, `tests/test_oracle_fixtures.py`

**Interfaces:**
- Consumes: `Criteria`, `load_settings` (Task 1)
- Produces (`vsf.model`):
  - 타입 별칭
    - `Num = float | None`
    - `Cell = float | str | None`: `None`은 엑셀의 빈칸이나 `""`
    - `SheetValues = dict[str, Cell]`: 키는 `FORMULA_CELLS`
  - `YearRow`: frozen. 기본값은 모두 `None` / `False`.
    - `year: int | None`, `eps`, `per`, `dps`, `roe`, `debt_ratio`, `interest_coverage`, `net_income`, `ocf`, `capex`, `dividends_paid`
    - `exclude_avg: bool`, `exclude_div: bool`
  - `Gate4Inputs`: frozen. 모두 `str = ""`.
    - `reason`(B129), `q1`(B130), `q2`(B131), `q3`(B132), `judgment`(B133), `why`(B134)
  - `StockInputs`: frozen.
    - `name: str = ""`(B18), `code: str = ""`(B19), `price: Num`(B20), `price_date: date | None`(B21), `pbr: Num`(B22), `memo: str = ""`(B23)
    - `years: tuple[YearRow, ...]`: 길이 5, B→F, 오래된 해 → 최근 해
    - `prior_years: tuple[int | None, ...]`(41행), `prior_dps: tuple[Num, ...]`(42행): 길이 5
    - `normal_eps_override: Num`(B95), `my_eps: Num`(B125), `gate4: Gate4Inputs`
  - `FORMULA_CELLS: tuple[str, ...]`: `분석_빈칸`에서 수식이 든 칸 152개의 주소, 위→아래, 왼쪽→오른쪽 순서. `tools/dump_formulas.py`의 출력을 붙여 넣어요.
  - `to_cells(inputs) -> dict[str, float | str | date | None]`: 입력 칸 주소 → 값.
    - 1번 표는 26–38행 B–F, 1-1번은 41–42행 B–F
    - X 표시는 `"X"`, 빈 글자는 `None`, B19는 글자
  - `criteria_to_cells(c) -> dict[str, float]`: `'기준값'!B5..B15`, `Criteria` 필드 순서대로.
  - `inputs_to_dict(i) -> dict` / `inputs_from_dict(d) -> StockInputs`: 날짜는 `"YYYY-MM-DD"`.
- Produces (테스트 도우미, `tests/helpers.py`):
  - `ORACLE_NAMES: list[str]`
  - `load_oracle(name) -> tuple[StockInputs, Criteria, SheetValues]`
  - `assert_cells_match(got: SheetValues, want: SheetValues, cells: Iterable[str])`: 숫자는 `math.isclose(rel_tol=1e-9, abs_tol=1e-9)`, 글자와 `None`은 정확히 같아야 해요.
- Produces (`tests/conftest.py`): fixture `template_path`. `load_settings(ROOT/"settings.toml").calculator_path`가 없으면 `pytest.skip("원본 계산기 파일이 없어요")`.

- [ ] **Step 1: `tools/dump_formulas.py` 작성 및 실행**
  - 템플릿 zip에서 `분석_빈칸` 시트 XML을 찾아요. 시트 이름 → `workbook.xml` → rels 경로로 찾고, 시트 번호를 고정해서 쓰지 않아요.
  - `<f>`가 있는 칸을 `주소<TAB>수식`으로 출력해요 (HTML 엔티티는 풀어서).
  - Run: `uv run python tools/dump_formulas.py | wc -l`
  - Expected: `152`
  - 이 주소 목록을 `FORMULA_CELLS`로 붙여 넣어요.

- [ ] **Step 2: `tests/engine_cases.py` 작성**

`CASES: dict[str, tuple[StockInputs, Criteria]]`. 예시 두 종목은 엑셀 예시 시트의 노란 칸 값이에요. 주가 기준일은 2026-11-09, B23 메모는 `""`예요.

```python
CHEIL = StockInputs(name="제일기획", code="030000", price=19500.0, price_date=date(2026,11,9), pbr=1.43,
  years=rows(years=(2021,2022,2023,2024,2025),
    eps=(1634,1913,1849,2049,2049), per=(13.98,12.05,10.29,8.289999999999999,10.25),
    dps=(990,1150,1110,1230,1230), roe=(15.64,16.68,15.09,15.03,13.63),
    debt_ratio=(125.51,125.26,122.65,124.32,125.93), interest_coverage=(36.38,44.97,28.23,32.66,22.32),
    net_income=(1654.85,1937.32,1873.02,2075.17,2075.46), ocf=(2495,1842,2667,3464,2123)),
  prior_years=(2016,2017,2018,2019,2020), prior_dps=(300,760,770,820,840),
  gate4=Gate4Inputs(reason="주요 고객사(삼성 계열)가 마케팅 예산을 줄이고 원화가 강해져서 올해 이익이 줄었다."))
KIA = StockInputs(name="기아", code="000270", price=97000.0, price_date=date(2026,11,9), pbr=0.62,
  years=rows(years=(2021,2022,2023,2024,2025),
    eps=(11874,13495,22168,24893,19382), per=(6.92,4.39,4.51,4.05,6.28),
    dps=(3000,3500,5600,6500,6800), roe=(14.69,14.57,20.44,19.09,12.91),
    debt_ratio=(91.48,87.34999999999999,73.18000000000001,66.11,61.76),
    interest_coverage=(29.72,30.85,63.02,121.2,115.56),
    net_income=(47604.5,54094.29,87769.7,97729.57000000001,75609.83), ocf=(74000,93000,113000,126000,91000)),
  prior_years=(2016,2017,2018,2019,2020), prior_dps=(1100,800,900,1150,1000),
  gate4=Gate4Inputs(reason="미국 관세, 할인 경쟁(인센티브 증가), 중국 전기차의 공세로 이익이 2024년 정점에서 내려오고 있다."))
```

`rows(...)`는 같은 파일 안의 도우미예요. 열별 튜플로 `YearRow` 5개를 만들어요. 나머지 사례는 `dataclasses.replace`로 바꿔 만들어요. 기준은 따로 적지 않으면 `Criteria()`예요.

| 이름 | 바꾸는 것 | 확인하는 것 |
|---|---|---|
| `blank` | `StockInputs()` | 모든 '입력 필요' 경로 |
| `cheil`, `kia` | 위 그대로 | 예시 |
| `kia_negative_eps` | eps=(-500,-800,300,200,-100) | 정상 EPS ≤ 0 → '계산 불가', ③ 탈락 |
| `kia_abnormal_year` | years[1].eps=3000 | '비정상' 해가 평균에서 빠짐 |
| `kia_x_marks` | years[2].exclude_avg=True, years[0].exclude_div=True | '제외(직접)', '뺌' |
| `kia_zero_dps` | years[3].dps=0, prior_dps[2]=0 | 거른 해 → ② 탈락, 0 다음 해 증감률 빈칸 |
| `kia_cov999_no_debt` | years[4].interest_coverage=999, years[4].debt_ratio=None | 999, 부채비율 '입력 필요' |
| `kia_ni_sum_negative` | net_income=(-50000,-60000,10000,5000,20000) | '순이익 합계 0 이하' → 탈락 |
| `kia_count_mismatch` | years[0].ocf=None, capex=(None,None,20000,20000,20000) | B81·B89 빈칸 |
| `kia_partial_years` | years[0]=years[1]=YearRow(), prior 모두 None | 앞 두 해가 빈 경우 |
| `kia_full_pass` | price=60000, capex=(20000,)*5, prior_dps=(800,900,1000,1100,1150), gate4=(reason, "예","예","예","일시적","근거") | 네 관문 모두 통과 문장 |
| `kia_gate3_pass_gate2_check` | `kia_full_pass`에서 prior_dps=KIA의 값, gate4=Gate4Inputs() | '관문 ③은 통과했어요…' 문장 |
| `kia_gate4_fail` | `kia_full_pass`에서 judgment="구조적" | '숫자는 모두 통과했지만…' 문장 |
| `payout_round_edge` | CHEIL에서 eps=(2000,)*5, dps=(1210,)*5 | 배당성향 평균 0.605 → ROUND → 0.61 → 탈락 |
| `override_eps` | KIA에서 normal_eps_override=25000, my_eps=21000 | B95·B125 경로 |
| `criteria_alt` | KIA + Criteria(required_return=0.08, safety_margin=0.30, roe_min=15, payout_max=0.5) | 기준이 수식까지 전달됨 |
| `text_inputs` | KIA에서 gate4.q1="모르겠음", name="A&B<C>" | 문장 칸, ④ 탈락 |

- [ ] **Step 3: `tools/make_oracle_fixtures.py` 작성 및 실행**

사례마다:
1. 템플릿을 임시 폴더에 복사하고 `openpyxl.load_workbook`으로 열어요.
2. `분석_빈칸`과 `기준값`만 남기고 다른 시트를 지워요. 비교표의 INDIRECT 오류를 피하고 속도를 높이려는 거예요.
3. `to_cells`와 `criteria_to_cells` 값을 써요. 날짜는 `datetime`으로 써요.
4. 저장한 뒤 `formulas.ExcelModel().loads(tmp).finish().calculate()`로 계산해요.
5. `FORMULA_CELLS` 값을 정리해요.
   - `[[v]]` → `v`, numpy 숫자 → `float`, `""` → `None`
   - 엑셀 오류 값 → `"#ERR:<이름>"`
6. `tests/fixtures/oracle/<이름>.json`에 `{"inputs":…, "criteria":…, "cells":…}`로 저장해요.

`payout_round_edge`의 D88은 엑셀 규칙(소수 둘째 자리에서 반쪽은 0에서 먼 쪽으로 반올림 → 0.61 → `탈락`)이 정답이에요. `formulas`가 다르게 계산하면 그 칸만 손으로 고치고 `"_note"`에 이유를 적어요.

- Run: `uv run python tools/make_oracle_fixtures.py`
- Expected: `17개 사례 저장`, 파일 17개

- [ ] **Step 4: 테스트 쓰기**

`tests/test_model.py`:
```python
def test_to_cells_mapping():
    c = to_cells(KIA)
    assert c["B19"] == "000270" and c["F27"] == 19382 and c["B42"] == 1100 and c["B21"] == date(2026,11,9)
    assert c["B37"] is None and to_cells(replace_year(KIA, 2, exclude_avg=True))["D37"] == "X"

def test_criteria_to_cells():
    assert criteria_to_cells(Criteria()) == {"B5":0.10,"B6":0.25,"B7":8.0,"B8":200.0,"B9":3.0,"B10":1.0,
        "B11":0.20,"B12":0.60,"B13":1.0,"B14":0.5,"B15":0.10}

def test_dict_roundtrip():
    assert inputs_from_dict(json.loads(json.dumps(inputs_to_dict(KIA)))) == KIA
```

`tests/test_oracle_fixtures.py`:
```python
def test_every_case_has_fixture():
    for name in CASES:
        _, _, cells = load_oracle(name)
        assert set(cells) == set(FORMULA_CELLS) and len(FORMULA_CELLS) == 152

@pytest.mark.template
def test_formula_cells_match_template(template_path):
    assert list(FORMULA_CELLS) == formula_addresses(template_path)   # dump_formulas의 함수 재사용

@pytest.mark.template
def test_example_inputs_match_template(template_path):
    for sheet, case in (("예시_제일기획", "cheil"), ("예시_기아", "kia")):
        assert input_values(template_path, sheet, exclude={"B23"}) == approx_cells(to_cells(CASES[case][0]))

@pytest.mark.template
def test_oracle_vs_stored_example_values(template_path):
    for sheet, case in (("예시_제일기획", "cheil"), ("예시_기아", "kia")):
        assert_cells_match(load_oracle(case)[2], stored_values(template_path, sheet), FORMULA_CELLS)
```

- [ ] **Step 5: 실행**
  - Run: `uv run pytest tests/test_model.py tests/test_oracle_fixtures.py -v`
  - Expected: PASS
  - 마지막 테스트가 실패하면 저장값과 정답이 다른 칸이 있다는 뜻이에요. 차이를 이 계획 아래 메모로 남기고, 정답(oracle)을 기준으로 해요. 저장값은 엑셀이 계산한 게 아니라서 정답으로 쓰지 않아요.

- [ ] **Step 6: 커밋**
  - `git add src/vsf/model.py tools tests`
  - `git commit -m "feat: input model and formula oracle fixtures from the calculator"`

---

### Task 3: 계산 엔진 ① — 해마다 계산한 값, 관문 ①②, 평균값

**Files:**
- Create: `src/vsf/excelfn.py`, `src/vsf/engine.py`, `tests/test_excelfn.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: `StockInputs`, `Criteria`, `SheetValues`, `FORMULA_CELLS` (Task 2)
- Produces:
  - `vsf.excelfn.excel_round(x: float, digits: int) -> float`: `Decimal(repr(x))`를 `ROUND_HALF_UP`으로 반올림해요 (반쪽은 0에서 먼 쪽).
  - `vsf.excelfn.excel_text(x: float | date, fmt: str) -> str`
    - 지원하는 형식은 이것뿐이에요: `"0"`, `"0.0"`, `"0.00"`, `"0%"`, `"#,##0"`, `"#,##0.0"`, `"yyyy-mm-dd"`
    - 다른 형식이면 `ValueError`
  - `vsf.excelfn.is_num(v) -> bool`: `bool`이 아닌 int·float만 True.
  - `vsf.excelfn.average(vals) -> float | None`, `vsf.excelfn.count(vals) -> int`: 숫자만 세요.
  - `vsf.engine.compute(inputs: StockInputs, criteria: Criteria, extra_gate1: str | None = None) -> SheetValues`
    - 이 task에서 맞추는 칸 `PART_A`: 43–55행, 78–90행, 94–100행
    - 나머지 칸은 Task 4에서 채워요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

`tests/test_excelfn.py`:
```python
@pytest.mark.parametrize("x,d,want", [(0.605,2,0.61),(0.6015870660805305,2,0.6),(2.5,0,3.0),(-2.5,0,-3.0),(0.27531662509536,2,0.28)])
def test_excel_round(x, d, want): assert excel_round(x, d) == want

@pytest.mark.parametrize("x,fmt,want", [
    (0.269692307692308,"0%","27%"), (0.281303020851005,"0%","28%"), (0.6015870660805305,"0%","60%"),
    (69713.6069774525,"#,##0","69,714"), (14241,"#,##0","14,241"), (1-0.25,"0.00","0.75"),
    (22.32,"#,##0.0","22.3"), (115.56,"#,##0.0","115.6"), (125.93,"0","126"), (8,"0","8"),
    (3,"0.0","3.0"), (1.0,"0.0","1.0"), (date(2026,11,9),"yyyy-mm-dd","2026-11-09")])
def test_excel_text(x, fmt, want): assert excel_text(x, fmt) == want

def test_excel_text_unknown_format():
    with pytest.raises(ValueError): excel_text(1, "0.000")
```

`tests/test_engine.py`:
```python
PART_A = [a for a in FORMULA_CELLS if 43 <= row(a) <= 55 or 78 <= row(a) <= 100]

@pytest.mark.parametrize("name", ORACLE_NAMES)
def test_part_a_matches_oracle(name):
    inputs, criteria, want = load_oracle(name)
    assert_cells_match(compute(inputs, criteria), want, PART_A)
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_excelfn.py tests/test_engine.py -v`
  - Expected: FAIL (모듈 없음)

- [ ] **Step 3: `excelfn.py`와 `compute`의 PART_A 구현**

`tools/dump_formulas.py`의 수식을 한 칸씩 옮겨요. 아래 엑셀 의미를 지켜요.
- 범위 평균·개수(AVERAGE, COUNT)는 숫자만 봐요. `None`과 글자는 건너뛰어요.
- `COUNTIF(범위,0)`은 숫자 0만 세요. 빈칸은 세지 않아요.
- `COUNTIF(범위,"<0")`은 음수인 숫자만 세요.
- AVERAGEIFS 결과가 없으면(IFERROR) `None`이에요.
- `LEN(x)>0`은 '비어 있지 않은 글자'예요.
- D88은 `excel_round(B88, 2)`로 비교해요.
- C78–C89의 기준 글자는 `excel_text`로 만들어요.

- [ ] **Step 4: 통과 확인**
  - Run: `uv run pytest tests/test_excelfn.py tests/test_engine.py -v`
  - Expected: PASS (17개 사례 모두)

- [ ] **Step 5: 커밋**
  - `git add src/vsf/excelfn.py src/vsf/engine.py tests/test_excelfn.py tests/test_engine.py`
  - `git commit -m "feat: engine part A (yearly values, gates 1-2, averages)"`

---

### Task 4: 계산 엔진 ② — 관문 ③, 5-3·5-4, 한눈에 보기, 관문 ④, 업종 추가 항목

**Files:**
- Modify: `src/vsf/engine.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: Task 3
- Produces:
  - `compute(...)`가 152칸을 모두 채워요. 키 집합은 `set(FORMULA_CELLS)`예요.
  - `extra_gate1`
    - `None`이면 엑셀과 완전히 같아요.
    - `"통과" | "탈락" | "입력 필요"`이면 D82를 계산할 때 D78:D81에 이 값이 다섯 번째 항목으로 더해져요. D82에 의존하는 B7·B15도 그 결과를 따라요.
  - `Summary`: frozen.
    - `gate1, gate2, gate3, gate4: str`
    - `price: Num`
    - `fair_value: Cell`(B105), `method: str | None`(B106)
    - `buy_line: Num`(B107), `ratio: Num`(B108), `drop: Num`(B109)
    - `next_step: str`(B15)
    - `roe_avg: Num`(B78), `payout_avg: Num`(B99), `yield_now: Num`(B115)
  - `summarize(cells: SheetValues) -> Summary`
  - `watch_state(s: Summary, r: ReportSettings) -> Literal["buy", "watch", "out"]`
    - `buy`: gate1·gate2가 '탈락'이 아니고 gate3 == '통과'
    - `watch`: gate1·gate2가 '탈락'이 아니고 drop이 숫자이며 drop ≤ `r.watch_range`
    - 그 밖에는 `out`
  - `is_near(s, r) -> bool`: drop이 숫자이고 drop ≤ `r.near_range`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
@pytest.mark.parametrize("name", ORACLE_NAMES)
def test_all_cells_match_oracle(name):
    inputs, criteria, want = load_oracle(name)
    got = compute(inputs, criteria)
    assert set(got) == set(FORMULA_CELLS)
    assert_cells_match(got, want, FORMULA_CELLS)

def test_extra_gate1_fail_propagates():
    inputs, c, _ = load_oracle("kia_full_pass")
    got = compute(inputs, c, extra_gate1="탈락")
    assert got["D82"] == "탈락" and got["B7"] == "탈락" and got["B15"].startswith("관문 ①에서 탈락했어요")

def test_extra_gate1_missing_makes_check_needed():
    inputs, c, _ = load_oracle("kia_full_pass")
    assert compute(inputs, c, extra_gate1="입력 필요")["D82"] == "확인 필요"

@pytest.mark.parametrize("price,state,near", [(97000,"out",False),(80000,"watch",False),(75000,"watch",True),(60000,"buy",True)])
def test_watch_state(price, state, near):
    inputs, c, _ = load_oracle("kia_full_pass")
    s = summarize(compute(replace(inputs, price=float(price)), c))
    assert watch_state(s, ReportSettings()) == state and is_near(s, ReportSettings()) is near

def test_gate2_fail_is_out_even_if_cheap():
    inputs, c, _ = load_oracle("kia_zero_dps")
    s = summarize(compute(replace(inputs, price=10000.0), c))
    assert s.gate2 == "탈락" and watch_state(s, ReportSettings()) == "out"
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_engine.py -v`
  - Expected: FAIL

- [ ] **Step 3: 나머지 칸과 `Summary`·`watch_state`·`is_near` 구현**
  - 대상 칸: 6–15행, 102–126행, C131·C132, D135.
  - F120:F126 판단은 `E <= 1 - safety_margin + 0.0000001`이면 '싸요', `E <= 1`이면 '제값', 그 밖에는 '비싸요'예요.
  - C11은 `"기준일 " + excel_text(price_date, "yyyy-mm-dd")`예요.

- [ ] **Step 4: 통과 확인**
  - Run: `uv run pytest tests -v`
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/engine.py tests/test_engine.py`
  - `git commit -m "feat: engine part B (gate 3, scenarios, summary, gate 4, industry hook)"`

---

### Task 5: 저장소(SQLite)와 HTTP 도우미

**Files:**
- Create: `src/vsf/data/__init__.py`, `src/vsf/data/store.py`, `src/vsf/data/http.py`, `tests/test_store.py`, `tests/test_http.py`

**Interfaces:**
- Produces:
  - `PriceRow`: frozen. `date: date`, `code: str`, `name: str`, `market: str`, `close: float | None`, `shares: float | None`
  - `Store(path: Path)`: 테이블이 없으면 만들어요.
    - `get_json(key) -> dict | list | None`
    - `put_json(key, body) -> None`
    - `get_bytes(key) -> bytes | None` / `put_bytes(key, body)`
    - `fetched_at(key) -> datetime | None`
    - `delete_prefix(prefix) -> int`
    - `count_calls(source: str, day: date) -> int`
    - `add_call(source: str, day: date) -> None`
    - `put_prices(rows: Iterable[PriceRow]) -> None`
    - `get_prices(day: date) -> dict[str, PriceRow]`
    - `price_dates() -> list[date]`
    - `get_meta(k) -> str | None` / `set_meta(k, v)`
  - `vsf.data.http.NetworkError(Exception)`: 한국어 메시지.
  - `get_with_retry(client: httpx.Client, url: str, *, params=None, headers=None, attempts=3, backoff=(1, 2, 4), sleep=time.sleep) -> httpx.Response`
    - 연결 오류와 5xx만 다시 시도해요.
    - 4xx는 바로 돌려줘요.
    - 끝까지 실패하면 `NetworkError("인터넷 연결이나 서버 문제로 {url} 요청이 실패했어요")`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_json_roundtrip_and_prefix_delete(tmp_path):
    s = Store(tmp_path/"v.sqlite3"); s.put_json("dart:001:fin:2025", {"a":1}); s.put_json("dart:002:fin:2025", {"b":2})
    assert s.get_json("dart:001:fin:2025") == {"a":1}
    assert s.delete_prefix("dart:001:") == 1 and s.get_json("dart:001:fin:2025") is None
    assert s.fetched_at("dart:002:fin:2025") is not None

def test_call_counts_per_day(tmp_path):
    s = Store(tmp_path/"v.sqlite3"); d = date(2026,11,14)
    s.add_call("dart", d); s.add_call("dart", d); s.add_call("krx", d)
    assert (s.count_calls("dart", d), s.count_calls("dart", date(2026,11,15))) == (2, 0)

def test_prices_upsert(tmp_path):
    s = Store(tmp_path/"v.sqlite3"); d = date(2025,12,30)
    s.put_prices([PriceRow(d,"000270","기아","KOSPI",100.0,10.0)]); s.put_prices([PriceRow(d,"000270","기아","KOSPI",101.0,10.0)])
    assert s.get_prices(d)["000270"].close == 101.0 and s.price_dates() == [d]
```

`tests/test_http.py`는 `httpx.MockTransport`를 써요.
- 두 번 503, 그다음 200 → 200을 돌려줘요. `sleep`은 `(1, 2)`로 불려요.
- 404 → 다시 시도 없이 404를 돌려줘요.
- `ConnectError`가 계속 나면 `NetworkError`가 나요.

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_store.py tests/test_http.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - 테이블:
    - `api_cache(key PK, body BLOB, is_json INT, fetched_at TEXT)`
    - `call_log(day, source, n, PK(day, source))`
    - `prices(date, code, name, market, close, shares, PK(date, code))`
    - `meta(k PK, v)`
  - 연결은 하나를 열어 두고, 쓰기마다 commit해요.

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/data tests/test_store.py tests/test_http.py`
  - `git commit -m "feat: sqlite store and retrying http helper"`

---

### Task 6: OpenDART 클라이언트

선행 조건: `keys.toml`에 DART 키가 있어야 해요. 없으면 멈추고 사용자에게 요청해요.

**Files:**
- Create: `src/vsf/data/dart.py`, `tools/record_fixtures.py`, `tests/fixtures/dart/…`, `tests/test_dart.py`

**Interfaces:**
- Consumes: `Store`, `get_with_retry`, `NetworkError` (Task 5)
- Produces:
  - `DartError(Exception)`: `.status: str`
  - `DartQuotaExceeded(DartError)`
  - `FinRows`: frozen. `rows: list[dict]`, `fs: Literal["CFS", "OFS"]`, `rcept_no: str`
  - `DartClient(api_key, store, http: httpx.Client | None = None, daily_budget: int = 19000, min_interval: float = 0.15, today: Callable[[], date] = date.today)`
    - `corp_codes() -> dict[str, str]`
      - `corpCode.xml` zip을 풀어 `stock_code`(공백 제외) → `corp_code`로 바꿔요.
      - 캐시 키 `dart:corpcode`, 7일 유효.
    - `company(corp_code) -> dict | None`
      - `company.json`, 키 `dart:{corp}:company`, 영구 캐시.
    - `financials(corp_code, year, report="11011") -> FinRows | None`
      - `fnlttSinglAcntAll.json`. CFS를 먼저 부르고, `013`이면 OFS를 불러요.
      - `11011`은 키 `dart:{corp}:fin:{year}:{report}`로 영구 캐시.
      - 분기 보고서(`11012`·`11013`·`11014`)는 캐시하지 않아요.
    - `dividends(corp_code, year) -> list[dict] | None`
      - `alotMatter.json`, `reprt_code=11011`. 키 `dart:{corp}:div:{year}`, 영구 캐시.
    - `filings(start, end, detail_type: str | None = "A001", corp_code: str | None = None) -> list[dict]`
      - `list.json`. 90일 넘는 기간은 90일씩 나눠 불러요. `page_count=100`으로 모든 페이지를 받아요. 캐시하지 않아요.
    - `invalidate(corp_code) -> None`: `dart:{corp}:` 캐시를 지워요.
    - `calls_today: int` (property): `store.count_calls("dart", today())`
  - 응답 상태 처리:
    - `000` → 정상
    - `013` → `None` (`filings`는 `[]`)
    - `020` → `DartQuotaExceeded`
    - 그 밖 → `DartError(status, message)`
  - 호출 횟수:
    - 네트워크 호출 직전에 `store.count_calls("dart", today()) >= daily_budget`이면 `DartQuotaExceeded("오늘 DART 호출 한도에 가까워 멈췄어요. 내일 다시 실행하면 이어서 받아요.")`
    - 실제 호출마다 `add_call`. 캐시에서 꺼낸 건 세지 않아요.

- [ ] **Step 1: 실제 응답 녹화**

`tools/record_fixtures.py dart`를 실행해요. 기아(000270)와 제일기획(030000)의 다음 응답을 `tests/fixtures/dart/`에 저장해요.
- corpCode: 두 회사만 남긴 작은 zip
- company
- financials: 2025·2023 사업보고서 CFS
- dividends: 2025·2023·2021·2019·2017
- filings: 2026-03-01~2026-03-31, A001, 첫 페이지 5건만

API 키는 응답과 URL에서 지워요.

- Run: `uv run python tools/record_fixtures.py dart`
- Expected: 파일 목록 출력, 응답 `status`가 모두 `000`

- [ ] **Step 2: 실패하는 테스트 쓰기** (`tests/test_dart.py`, 녹화 파일을 돌려주는 `MockTransport`)

```python
def test_corp_codes_maps_stock_code(dart): assert dart.corp_codes()["000270"] == KIA_CORP   # KIA_CORP: 녹화 파일에서 읽음
def test_financials_cfs_cached(dart, transport):
    f = dart.financials(KIA_CORP, 2025); assert f.fs == "CFS" and f.rows and f.rcept_no
    n = transport.calls; dart.financials(KIA_CORP, 2025); assert transport.calls == n
def test_ofs_fallback_when_cfs_missing(dart_cfs_013): assert dart_cfs_013.financials(KIA_CORP, 2025).fs == "OFS"
def test_no_data_is_none(dart_013): assert dart_013.dividends(KIA_CORP, 2014) is None
def test_status_020_raises(dart_020):
    with pytest.raises(DartQuotaExceeded): dart_020.company(KIA_CORP)
def test_budget_stops_before_network(dart_budget_1, transport):
    dart_budget_1.company(KIA_CORP)
    with pytest.raises(DartQuotaExceeded): dart_budget_1.company(CHEIL_CORP)
    assert transport.calls == 1
def test_filings_split_into_90_day_windows(dart, transport):
    dart.filings(date(2026,1,1), date(2026,7,19))
    assert transport.windows == [("20260101","20260331"),("20260401","20260629"),("20260630","20260719")]
def test_invalidate(dart, store):
    dart.financials(KIA_CORP, 2025); dart.invalidate(KIA_CORP)
    assert store.get_json(f"dart:{KIA_CORP}:fin:2025:11011") is None
```

- [ ] **Step 3: 실패 확인**
  - Run: `uv run pytest tests/test_dart.py -v`
  - Expected: FAIL

- [ ] **Step 4: `DartClient` 구현**
  - 요청 사이에 `min_interval` 이상 쉬어요.
  - `corpCode.xml` 응답이 zip이 아니면 상태 XML을 읽어서 같은 규칙으로 처리해요.

- [ ] **Step 5: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 6: 커밋**
  - `git add src/vsf/data/dart.py tools/record_fixtures.py tests/fixtures/dart tests/test_dart.py`
  - `git commit -m "feat: OpenDART client with caching and daily budget"`

---

### Task 7: KRX OPEN API 클라이언트

선행 조건:
- `keys.toml`에 KRX 키가 있어야 해요.
- 다음 4개 서비스의 이용 승인이 끝나 있어야 해요: 유가증권 일별매매정보, 코스닥 일별매매정보, 유가증권 종목기본정보, 코스닥 종목기본정보.

없으면 멈추고 사용자에게 요청해요.

**Files:**
- Create: `src/vsf/data/krx.py`, `tests/fixtures/krx/…`, `tests/test_krx.py`
- Modify: `tools/record_fixtures.py`

**Interfaces:**
- Consumes: `Store`, `PriceRow`, `get_with_retry`
- Produces:
  - `KrxError(Exception)`
    - 401·403이면: `"KRX OPEN API에서 '{서비스}' 이용 승인이 필요해요. openapi.krx.co.kr에서 이용신청 상태를 확인해 주세요."`
  - `Listed`: frozen. `code`, `name`, `market: Literal["KOSPI", "KOSDAQ"]`, `group: str`(증권구분), `kind: str`(주식종류), `shares: float | None`
  - 응답 필드 이름 상수 (Step 1 녹화로 확인한 뒤 고정):
    - `DAILY_FIELDS = {"code": "ISU_CD", "name": "ISU_NM", "close": "TDD_CLSPRC", "shares": "LIST_SHRS"}`
    - `BASE_FIELDS = {"code": "ISU_SRT_CD", "name": "ISU_ABBRV", "group": "SECUGRP_NM", "kind": "KIND_STKCERT_TP_NM", "shares": "LIST_SHRS"}`
  - `KrxClient(auth_key, store, http=None, min_interval=0.2, today=date.today)`
    - 요청: 헤더 `AUTH_KEY`, 파라미터 `basDd=YYYYMMDD`, 응답 `{"OutBlock_1": [...]}`
    - `listed(day) -> list[Listed]`: `stk_isu_base_info` + `ksq_isu_base_info`
    - `daily(day) -> dict[str, PriceRow]`
      - `stk_bydd_trd` + `ksq_bydd_trd`
      - `day < today()`이고 자료가 있으면 `store.prices`에 저장하고, 다음엔 저장된 걸 써요.
      - 빈 결과는 저장하지 않아요.
    - `latest_trading_day(today: date, max_back: int = 10) -> date`: 자료가 있는 가장 최근 날. 없으면 `KrxError`.
    - `year_end(year) -> date`: 12/31부터 거꾸로 가며 자료가 있는 첫 날.
    - `week_ends(until: date, weeks: int = 52) -> list[date]`: 각 주의 마지막 거래일, 오래된 순.
  - 숫자 문자열 처리: `"1,234"` → `1234.0`, `""`·`"-"` → `None`

- [ ] **Step 1: 실제 응답 녹화**
  - `tools/record_fixtures.py krx`로 녹화해요.
    - 2025-12-30과 2026-11-13의 `*_bydd_trd`
    - 2026-11-13의 `*_isu_base_info`
  - 행은 000270, 030000, 그리고 보통주·우선주·리츠·스팩이 하나씩 섞이도록 6개만 남겨요.
  - 필드 이름이 위 상수와 다르면 상수를 녹화본에 맞춰 고쳐요.
  - Run: `uv run python tools/record_fixtures.py krx`
  - Expected: 응답 행 수 출력

- [ ] **Step 2: 실패하는 테스트 쓰기**

```python
def test_daily_merges_markets_and_parses(krx): 
    rows = krx.daily(date(2025,12,30)); assert rows["000270"].market == "KOSPI" and rows["000270"].close > 0
def test_daily_cached_for_past_days(krx, transport):
    krx.daily(date(2025,12,30)); n = transport.calls; krx.daily(date(2025,12,30)); assert transport.calls == n
def test_latest_trading_day_skips_empty_days(krx_with_empty):          # Review Focus 2
    assert krx_with_empty.latest_trading_day(date(2026,11,15)) == date(2026,11,13)   # 15(일)·14(토) 빈 응답
def test_year_end(krx_with_empty): assert krx_with_empty.year_end(2025) == date(2025,12,30)
def test_week_ends_distinct_and_ordered(krx_calendar):
    w = krx_calendar.week_ends(date(2026,11,13), 52); assert len(w) == 52 and w == sorted(set(w))
def test_unapproved_service_message(krx_403):
    with pytest.raises(KrxError, match="이용 승인"): krx_403.daily(date(2025,12,30))
```

- [ ] **Step 3: 실패 확인**
  - Run: `uv run pytest tests/test_krx.py -v`
  - Expected: FAIL

- [ ] **Step 4: `KrxClient` 구현**

- [ ] **Step 5: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 6: 커밋**
  - `git add src/vsf/data/krx.py tools/record_fixtures.py tests/fixtures/krx tests/test_krx.py`
  - `git commit -m "feat: KRX OPEN API client (listings, daily prices, trading days)"`

---

### Task 8: 재무제표에서 계정 뽑기

**Files:**
- Create: `src/vsf/data/accounts.py`, `tests/test_accounts.py`

**Interfaces:**
- Consumes: `FinRows` (Task 6)
- Produces:
  - `Sourced`: frozen. `value: float | None`, `account: str`, `how: Literal["id", "name", "proxy", "derived"]`
  - `PERIODS = ("thstrm", "frmtrm", "bfefrmtrm")`
  - `parse_amount(s: str | None) -> float | None`: `"1,234"`·`"-1,234"` → 숫자, `""`·`"-"`·`None` → `None`
  - `extract(fin: FinRows, period: str) -> dict[str, Sourced]`: 키는 아래 표의 필드 13개. 못 찾으면 `Sourced(None, "", "id")`.

계정 표 (처음 시작할 목록이에요. Task 20에서 놓치는 회사가 나오면 늘려요):

| 필드 | 재무제표 | account_id (먼저) | 이름 (공백·`(손실)` 지우고 비교) |
|---|---|---|---|
| `net_income_parent` | IS→CIS | `ifrs-full_ProfitLossAttributableToOwnersOfParent` | 지배기업의소유주에게귀속되는당기순이익, 지배기업소유주지분, 지배기업의소유주지분 |
| `profit_loss` | IS→CIS | `ifrs-full_ProfitLoss` | 당기순이익 |
| `eps` | IS→CIS | `ifrs-full_BasicEarningsLossPerShare` | 기본주당이익, 기본주당순이익, 보통주기본주당이익 (여러 줄이면 이름에 '보통주'가 든 줄) |
| `equity_parent` | BS | `ifrs-full_EquityAttributableToOwnersOfParent` | 지배기업의소유주에게귀속되는자본, 지배기업소유주지분 |
| `equity_total` | BS | `ifrs-full_Equity` | 자본총계 |
| `liabilities` | BS | `ifrs-full_Liabilities` | 부채총계 |
| `current_assets` | BS | `ifrs-full_CurrentAssets` | 유동자산 |
| `operating_income` | IS→CIS | `dart_OperatingIncomeLoss` | 영업이익 |
| `interest_expense` | IS→CIS | `ifrs-full_InterestExpense` | 이자비용 |
| `interest_paid` | CF | `ifrs-full_InterestPaidClassifiedAsOperatingActivities`, `ifrs-full_InterestPaidClassifiedAsFinancingActivities` | 이자의지급, 이자지급 |
| `ocf` | CF | `ifrs-full_CashFlowsFromUsedInOperatingActivities` | 영업활동현금흐름, 영업활동으로인한현금흐름 |
| `capex` | CF | `ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`, `ifrs-full_PurchaseOfPropertyPlantAndEquipment` | 유형자산의취득 |
| `dividends_paid` | CF | `ifrs-full_DividendsPaidClassifiedAsFinancingActivities`, `ifrs-full_DividendsPaid` | 배당금의지급, 배당금지급 |

`capex`와 `dividends_paid`는 절댓값으로 저장해요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_kia_2025_core_accounts():
    e = extract(load_fin("kia_2025_cfs"), "thstrm")
    assert e["eps"].value == 19382
    assert math.isclose(e["net_income_parent"].value / 1e8, 75609.83, rel_tol=0.005)
    assert e["ocf"].value > 0 and e["capex"].value > 0 and e["capex"].how in ("id","name")
def test_cheil_2025_core_accounts():
    e = extract(load_fin("cheil_2025_cfs"), "thstrm")
    assert e["eps"].value == 2049 and math.isclose(e["net_income_parent"].value / 1e8, 2075.46, rel_tol=0.005)
def test_name_fallback():   # account_id "-표준계정코드 미사용-"인 합성 행
    assert extract(synthetic(capex_name="유형자산의 취득"), "thstrm")["capex"].how == "name"
def test_common_share_eps_preferred():
    assert extract(synthetic(eps_rows=[("우선주기본주당이익", 110), ("보통주기본주당이익", 100)]), "thstrm")["eps"].value == 100
def test_missing_interest_expense_is_none():
    assert extract(synthetic(), "thstrm")["interest_expense"].value is None
@pytest.mark.parametrize("s,want", [("1,234",1234.0),("-1,234",-1234.0),("",None),("-",None),(None,None)])
def test_parse_amount(s, want): assert parse_amount(s) == want
```

`load_fin`과 `synthetic`은 `tests/helpers.py`에 추가해요. `load_fin`은 녹화한 DART 응답을 읽고, `synthetic`은 키워드 인자로 합성 행을 만들어요.

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_accounts.py -v`
  - Expected: FAIL

- [ ] **Step 3: `extract`·`parse_amount` 구현**
  - account_id가 정확히 같은 줄을 먼저 찾아요.
  - 없으면 정규화한 이름으로 찾아요.
  - 재무제표 종류는 `sj_div`로 고르고, IS를 CIS보다 먼저 봐요.

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/data/accounts.py tests/test_accounts.py tests/helpers.py`
  - `git commit -m "feat: map DART statement rows to calculator accounts"`

---

### Task 9: 액면분할·무상증자 감지와 조정

**Files:**
- Create: `src/vsf/data/splits.py`, `tests/test_splits.py`

**Interfaces:**
- Produces:
  - 상수
    - `SPLIT_LIKE = 1.5`
    - `SPLIT_FLAG = "주식 수가 크게 바뀐 해가 있어요(액면분할·무상증자 가능성). 옛날 EPS·DPS를 확인해 주세요."`
    - `RESTATE_FLAG = "같은 해 EPS가 보고서마다 달라요(정정·재작성 가능성). EPS를 확인해 주세요."`
  - `is_split_like(ratio: float | None) -> bool`: `ratio >= 1.5` 또는 `ratio <= 1/1.5`
  - `close_factor(shares_then: float | None, shares_now: float | None) -> float`: `shares_now/shares_then`이 분할 같으면 `shares_then/shares_now`, 아니면 1.0
  - `overlap_ratio(newer: float | None, older: float | None) -> float | None`: 둘 다 0이 아니고 부호가 같을 때 `older/newer`
  - `SplitCheck`: frozen. `eps_divisor_older: float`, `flags: tuple[str, ...]`
  - `check_splits(eps_newer_at_overlap, eps_older_at_overlap, shares_by_year: dict[int, float | None], latest_year: int) -> SplitCheck`

규칙:
- `r = overlap_ratio(...)`가 `None`이거나 `|r − 1| ≤ 0.02`이면 나누는 값은 1이에요.
- r이 분할 같고, `s = shares[L] / shares[L−2]`가 r의 ±10% 안이면 나누는 값은 r이에요.
- r이 분할 같지 않은데 `|r − 1| > 0.02`이면 나누는 값은 1이고 `RESTATE_FLAG`를 달아요.
- `shares[L] / shares[y]`가 분할 같은 해 y가 하나라도 있으면 `SPLIT_FLAG`를 한 번 달아요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_no_split(): assert check_splits(100, 100, {2021:10,2022:10,2023:10,2024:10,2025:10}, 2025) == SplitCheck(1.0, ())
def test_two_for_one_split_last_year():
    c = check_splits(50, 100, {2023:10,2024:20,2025:20}, 2025); assert c.eps_divisor_older == 2.0 and SPLIT_FLAG in c.flags
def test_big_issuance_is_flag_only():
    c = check_splits(100, 100, {2023:10,2025:16}, 2025); assert c.eps_divisor_older == 1.0 and c.flags == (SPLIT_FLAG,)
def test_restatement_flag():
    c = check_splits(100, 105, {2023:10,2025:10}, 2025); assert c.eps_divisor_older == 1.0 and c.flags == (RESTATE_FLAG,)
def test_close_factor(): assert close_factor(10, 20) == 0.5 and close_factor(10, 11) == 1.0 and close_factor(None, 20) == 1.0
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_splits.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/data/splits.py tests/test_splits.py`
  - `git commit -m "feat: detect splits and restatements across reports"`

---

### Task 10: 계산기 입력 조립

**Files:**
- Create: `src/vsf/data/assemble.py`, `tests/test_assemble.py`

**Interfaces:**
- Consumes: `FinRows`, `extract`, `parse_amount`, `check_splits`, `close_factor`, `PriceRow`, `StockInputs`, `YearRow`, `excel_round`
- Produces:
  - `CompanyInfo`: frozen. `corp_code`, `code`, `name`, `market`, `induty_code`, `acc_mt`
  - `Assembled`: frozen.
    - `inputs: StockInputs`
    - `flags: tuple[str, ...]`: '숫자 확인 필요' 사유
    - `notes: tuple[str, ...]`: 참고 메모
    - `sources: dict[str, str]`: 입력 칸 주소 → 출처 글
    - `quick_fail: bool`
    - `latest_year: int`
  - `dps_from_report(rows: list[dict], year: int) -> dict[int, float | None]`
    - `se`에 "주당 현금배당금"이 들어 있고 `stock_knd == "보통주"`인 줄을 써요. 그런 줄이 없고 '주당 현금배당금' 줄이 하나뿐이면 그 줄을 써요.
    - `{year: thstrm, year−1: frmtrm, year−2: lwfr}`이에요. `"-"`는 0.0이에요.
  - `dps_by_year(div_reports: dict[int, list[dict]]) -> tuple[dict[int, float | None], tuple[str, ...]]`
    - 겹치는 해는 더 최근 보고서 값을 써요.
    - 두 값이 2% 넘게 다르면 플래그 `"{y}년 DPS가 보고서마다 달라요. 확인해 주세요."`
  - `quick_fail_check(latest_div_rows: list[dict] | None, latest_year: int) -> bool`: 최근 3년 중 보통주 DPS가 0인 해가 있으면 True.
  - `assemble(company, latest_year, fin_a: FinRows | None, fin_b: FinRows | None, div_reports: dict[int, list[dict]], year_end: dict[int, PriceRow], price: PriceRow, price_date: date) -> Assembled`
  - `assemble_quick_fail(company, latest_year, div_reports, price, price_date) -> Assembled`

조립 규칙 (L = latest_year):
- **연도 열:** B–F = L−4…L. 41행 = L−9…L−5.
- **어느 보고서의 어느 기간을 쓰나:**
  - `fin_a`(L년 보고서): `thstrm`→L, `frmtrm`→L−1, `bfefrmtrm`→L−2
  - `fin_b`(L−2년 보고서): `frmtrm`→L−3, `bfefrmtrm`→L−4. `thstrm`(L−2)은 겹치는 해라 검사용이에요.
- **EPS:** L…L−2는 A에서, L−3·L−4는 B 값을 `check_splits(...).eps_divisor_older`로 나눠요. 주식 수는 `year_end[y].shares`예요.
- **순이익 (억 원):**
  - `net_income_parent / 1e8`
  - OFS여서 이 값이 없으면 `profit_loss`를 쓰고 메모 `"별도 재무제표 기준이에요"`
- **ROE (%):**
  - 순이익 ÷ 평균 자본 × 100. 평균 자본은 그해와 전해 `equity_parent`의 평균이에요 (OFS면 `equity_total`).
  - 연말 자본은 A·B 어느 보고서에 있든 그해 값을 써요. 둘 다 있으면 A가 먼저예요.
  - 전해 자본이 없으면 그해 자본으로 나누고 메모 `"{y}년 ROE는 기말 자본 기준이에요"`
- **부채비율 (%):** `liabilities / equity_total × 100`
- **이자보상배율:**
  - `operating_income / interest_expense`
  - 이자비용이 없으면 `interest_paid`를 대신 쓰고 메모 `"{y}년 이자보상배율은 '이자의 지급'으로 계산했어요"`
  - 분모가 0이면 999
  - 영업이익이나 분모가 없으면 `None`
- **영업현금흐름, 설비투자, 배당금 지급 총액:** 억 원.
- **연말 PER:**
  - `(year_end[y].close × close_factor(year_end[y].shares, year_end[L].shares)) / EPS_y`
  - EPS > 0이고 종가가 있을 때만 계산해요.
- **PBR:**
  - `price.close / (equity_parent_L / (net_income_parent_L / eps_L))`
  - 모두 양수일 때만 계산하고, 메모 `"PBR은 추정값이에요"`
- **반올림:** 금액·ROE·부채비율·이자보상배율·PER·PBR은 `excel_round(·, 2)`. EPS·DPS는 받은 그대로예요.
- **특별배당 의심:** DPS ÷ EPS > 1이면 메모 `"{y}년 배당성향이 100%를 넘어요(특별배당 의심)"`
- **통화:** 재무제표 행의 `currency`가 `"KRW"`가 아니면 플래그 `"원화가 아닌 재무제표예요(통화: {currency}). 숫자를 확인해 주세요."`
- **출처 글 예시:**
  - F27: `"2025 사업보고서(연결) · ifrs-full_BasicEarningsLossPerShare"`
  - B28: `"2021-12-30 종가 ÷ EPS"`
  - F29: `"2025 사업보고서 배당에 관한 사항(보통주)"`
- **B23 메모:** `"자동 수집 {price_date}: DART 사업보고서 {L}·{L−2}, 배당 {연도들}, 주가 KRX {price_date} 종가."` + 플래그를 이어 붙여요.
- **빈 값:** 없는 값은 `None`으로 둬요. B나 A 보고서가 없으면 그 해들은 비워요.
- **quick fail:**
  - `inputs`에는 이름, 코드, 주가, 날짜, D–F열 DPS, 연도만 채워요.
  - 메모: `"최근 3년 중 배당을 안 준 해가 있어 관문 ②에서 탈락이라, 나머지 숫자는 받지 않았어요."`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_kia_close_to_example_sheet():
    a = assemble(KIA_CO, 2025, load_fin("kia_2025_cfs"), load_fin("kia_2023_cfs"), load_divs("kia"), load_year_end("kia"), PRICE, date(2026,11,13))
    y = a.inputs.years
    assert [r.eps for r in y[2:]] == [22168, 24893, 19382] and [r.dps for r in y] == [3000,3500,5600,6500,6800]
    assert all(math.isclose(r.net_income, w, rel_tol=0.005) for r, w in zip(y, (47604.5,54094.29,87769.7,97729.57,75609.83)))
    assert all(abs(r.roe - w) <= 0.5 for r, w in zip(y[2:], (20.44,19.09,12.91)))   # 2023–2025는 두 연말 자본이 항상 있음
    assert all(abs(r.debt_ratio - w) <= 0.5 for r, w in zip(y, (91.48,87.35,73.18,66.11,61.76)))
    assert all(r.capex is not None and r.capex > 0 for r in y)
    assert a.inputs.prior_dps == (1100.0, 800.0, 900.0, 1150.0, 1000.0) and a.flags == ()
def test_missing_older_report_leaves_blanks():
    a = assemble(KIA_CO, 2025, load_fin("kia_2025_cfs"), None, load_divs("kia"), load_year_end("kia"), PRICE, D)
    assert a.inputs.years[0].eps is None and a.inputs.years[1].ocf is None
def test_interest_proxy_and_999():
    a = assemble(*synthetic_company(interest_expense=None, interest_paid=0))
    assert a.inputs.years[4].interest_coverage == 999 and any("이자의 지급" in n for n in a.notes)
def test_ofs_note(): assert "별도 재무제표 기준이에요" in assemble(*synthetic_company(fs="OFS")).notes
def test_non_krw_flagged(): assert any("원화가 아닌" in f for f in assemble(*synthetic_company(currency="USD")).flags)
def test_quick_fail_detection(): assert quick_fail_check(div_rows(thstrm="1,000", frmtrm="-", lwfr="900"), 2025)
def test_quick_fail_inputs():
    a = assemble_quick_fail(KIA_CO, 2025, {2025: div_rows("1,000","-","900")}, PRICE, D)
    assert a.quick_fail and a.inputs.years[3].dps == 0.0 and a.inputs.years[4].roe is None
def test_special_dividend_note():
    assert any("특별배당 의심" in n for n in assemble(*synthetic_company(dps=3000, eps=2000)).notes)
def test_split_adjusts_older_eps_and_flags():
    a = assemble(*synthetic_company(split_ratio=2))
    assert a.inputs.years[0].eps == ORIGINAL_OLD_EPS / 2 and SPLIT_FLAG in a.flags
```

`load_divs`, `load_year_end`, `synthetic_company`, `div_rows`는 `tests/helpers.py`에 추가해요. 녹화본이나 합성 자료를 돌려줘요. `ORIGINAL_OLD_EPS`는 `synthetic_company`가 쓰는 B 보고서 EPS 상수예요.

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_assemble.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/data/assemble.py tests/test_assemble.py tests/helpers.py`
  - `git commit -m "feat: assemble calculator inputs with sources and flags"`

---

### Task 11: 분석 대상 고르기 (제외 규칙)

**Files:**
- Create: `src/vsf/data/universe.py`, `tests/test_universe.py`

**Interfaces:**
- Consumes: `Listed` (Task 7), `FinRows`, `extract` (Task 6, 8)
- Produces:
  - `listing_exclusion(item: Listed) -> str | None`: 위에서부터 차례로 확인해요.
    1. `kind`에 "보통주"가 없으면 → `"우선주"`
    2. `group`에 "부동산투자"가 있거나 이름에 "리츠"가 있으면 → `"리츠"`
    3. 이름에 "스팩"이나 "기업인수목적"이 있으면 → `"스팩"`
    4. `group`에 "주권"이 없으면 → `"투자회사 등"`
  - `is_holding(company: dict) -> bool`: `induty_code`가 "64992"로 시작
  - `company_exclusion(company: dict) -> str | None`
    - `acc_mt != "12"` → `"결산월 12월 아님"`
    - `induty_code` 앞 두 자리가 64·65·66이고 지주회사가 아니면 → `"금융회사"`
  - `holding_exclusion(fin: FinRows | None) -> str | None`: 지주회사인데 최신 BS에 `current_assets`가 없으면 → `"금융지주"`

- [ ] **Step 1: 실패하는 테스트 쓰기** (표로 돌려요)

```python
@pytest.mark.parametrize("item,want", [
    (L(kind="우선주"), "우선주"), (L(name="하나30호스팩"), "스팩"), (L(group="부동산투자회사"), "리츠"),
    (L(name="맥쿼리인프라", group="투자회사"), "투자회사 등"), (L(), None)])
def test_listing_exclusion(item, want): assert listing_exclusion(item) == want
@pytest.mark.parametrize("co,want", [({"acc_mt":"03","induty_code":"30121"}, "결산월 12월 아님"),
    ({"acc_mt":"12","induty_code":"6419"}, "금융회사"), ({"acc_mt":"12","induty_code":"65110"}, "금융회사"),
    ({"acc_mt":"12","induty_code":"64992"}, None), ({"acc_mt":"12","induty_code":"30121"}, None)])
def test_company_exclusion(co, want): assert company_exclusion(co) == want
def test_holding_with_current_assets_kept(): assert holding_exclusion(fin_with(current_assets=1)) is None
def test_financial_holding_excluded(): assert holding_exclusion(fin_with()) == "금융지주"
```

`L(**kw)`는 기본값이 보통주 `Listed`인 도우미예요. `fin_with(**kw)`는 합성 `FinRows`를 만들어요.

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_universe.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/data/universe.py tests/test_universe.py`
  - `git commit -m "feat: universe exclusion rules"`

---

### Task 12: 업종 묶음과 업종 비교

**Files:**
- Create: `src/vsf/industry.py`, `src/vsf/data/ksic.csv`, `tests/test_industry.py`

**Interfaces:**
- Consumes: `Criteria`, `IndustrySettings`, `StockInputs`
- Produces:
  - `ksic.csv`: 한국표준산업분류 10차의 대분류 21개(A–U)와 중분류 77개(2자리) `code,name`. 출처는 통계청 한국표준분류(KSSC)예요.
  - `IndustryInfo`: frozen. `group_code: str`, `group_name: str`, `size: int`, `roe_median: Num`, `roe_rank_pct: Num`, `debt_median: Num`, `debt_rank_pct: Num`
  - `division(induty_code) -> str`: 앞 두 자리
  - `section(div) -> str`: 01–03→A, 05–08→B, 10–34→C, 35→D, 36–39→E, 41–42→F, 45–47→G, 49–52→H, 55–56→I, 58–63→J, 64–66→K, 68→L, 70–73→M, 74–76→N, 84→O, 85→P, 86–87→Q, 90–91→R, 94–96→S, 97–98→T, 99→U
  - `group_names() -> dict[str, str]`
  - `build_industry(stocks: dict[str, tuple[str, Num, Num]], min_group_size: int) -> dict[str, IndustryInfo]`
    - 입력: 종목코드 → (induty_code, ROE 5년 평균, 최근 부채비율)
    - 묶음 고르기: 중분류 안에서 ROE가 있는 종목이 `min_group_size` 이상이면 중분류. 아니면 대분류. 대분류도 모자라면 `"ALL"`(이름 "전체 시장").
    - ROE 순위: 높은 순으로 매긴 순위 ÷ n × 100, 소수 첫째 자리.
    - 부채비율 순위: 낮은 순으로 매긴 순위 ÷ n × 100.
    - 중간값: `statistics.median`.
    - ROE가 없는 종목도 묶음은 정해 주고, 순위만 `None`이에요.
  - `effective_criteria(base, induty_code, overrides) -> Criteria`: `overrides[division]`이 있으면 그걸, 없으면 `overrides[section]`을 `replace`로 덮어써요.
  - `extra_gate1(info: IndustryInfo | None, s: IndustrySettings) -> str | None`
    - 꺼져 있으면 `None`
    - 순위가 없으면 `"입력 필요"`
    - `roe_rank_pct <= roe_top_percent`면 `"통과"`, 아니면 `"탈락"`
  - `industry_inputs(inputs: StockInputs) -> tuple[Num, Num]`: (ROE 평균, F열 부채비율). B78·B79와 같은 뜻이고 엔진을 거치지 않아요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_names_anchor():
    n = group_names(); assert n["30"] == "자동차 및 트레일러 제조업" and n["64"] == "금융업" and n["C"] == "제조업"
    assert sum(1 for k in n if k.isdigit()) == 77 and sum(1 for k in n if k.isalpha()) == 21
def test_small_division_falls_back_to_section():
    st = {f"A{i}": ("20111", 10.0+i, 100.0) for i in range(6)} | {"B0": ("21000", 30.0, 50.0), "B1": ("21000", 5.0, 80.0)}
    t = build_industry(st, 5)
    assert t["A0"].group_code == "20" and t["B0"].group_code == "C" and t["B0"].roe_rank_pct == 12.5
    assert t["A5"].roe_rank_pct == round(1/6*100, 1) and t["A0"].roe_median == 12.5
def test_overrides_division_then_section():
    assert effective_criteria(Criteria(), "35110", {"35": {"roe_min": 6.0}}).roe_min == 6.0
    assert effective_criteria(Criteria(), "35110", {"D": {"roe_min": 5.0}}).roe_min == 5.0
    assert effective_criteria(Criteria(), "30121", {"35": {"roe_min": 6.0}}).roe_min == 8.0
@pytest.mark.parametrize("on,rank,want", [(False,10.0,None),(True,None,"입력 필요"),(True,50.0,"통과"),(True,50.1,"탈락")])
def test_extra_gate1(on, rank, want):
    assert extra_gate1(info(roe_rank_pct=rank), IndustrySettings(use_in_verdict=on)) == want
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_industry.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/industry.py src/vsf/data/ksic.csv tests/test_industry.py`
  - `git commit -m "feat: industry groups, ranks, overrides and optional gate-1 check"`

---

### Task 13: 자료 모으기 (수집 단계)

**Files:**
- Create: `src/vsf/collect.py`, `tests/fakes.py`, `tests/test_collect.py`

**Interfaces:**
- Consumes: `DartClient`, `KrxClient`, `Store`, `assemble`, `assemble_quick_fail`, `quick_fail_check`, `listing_exclusion`, `company_exclusion`, `is_holding`, `holding_exclusion`, `CompanyInfo`, `Assembled`
- Produces:
  - `Collected`: dataclass.
    - `today: date`, `price_date: date`
    - `records: dict[str, tuple[CompanyInfo, Assembled]]`
    - `excluded: dict[str, list[tuple[str, str]]]`: 사유 → [(코드, 이름)]
    - `failed: list[tuple[str, str, str]]`: (코드, 이름, 사유)
    - `pending: list[tuple[str, str]]`: 하루 한도 때문에 못 받은 종목
    - `total_listed: int`
  - `collect(dart, krx, store, today, progress: Callable[[str], None] = print) -> Collected`
  - `collect_one(dart, krx, store, today, code) -> tuple[CompanyInfo, Assembled] | str`: 실패하면 한국어 사유 글.
  - `tests/fakes.py`: `FakeDart`, `FakeKrx`. 같은 메서드 이름을 갖고, 미리 넣은 응답을 돌려주며, 호출 기록이 남아요. Task 15·19도 써요.

순서 (`collect`):
1. 주가와 종목 목록
   - `price_date = krx.latest_trading_day(today)`
   - `prices = krx.daily(price_date)`, `listed = krx.listed(price_date)`
2. 새 사업보고서 확인
   - `since = store.get_meta("filings_checked")`가 있으면 `dart.filings(since, today, "A001")`의 `corp_code`마다 `dart.invalidate`.
   - 그다음 `set_meta("filings_checked", today.isoformat())`.
3. `corp = dart.corp_codes()`
4. 연말 주가: `y in range(today.year−10, today.year)`마다 `krx.daily(krx.year_end(y))`.
5. 종목마다 차례로 처리해요.
   1. `listing_exclusion` → 제외
   2. corp code가 없으면 → 실패 `"DART에서 회사 정보를 찾지 못했어요"`
   3. `company()`와 `company_exclusion` → 제외
   4. 최근 연도 L 정하기
      - `divs = dart.dividends(corp, today.year−1)`가 있으면 L = today.year−1
      - 없으면 today.year−2로 다시 시도
      - 둘 다 없으면 L = today.year−1이고 배당 자료는 없음
   5. `quick_fail_check`가 참이면 `assemble_quick_fail`로 끝
   6. `fin_a = dart.financials(corp, L)`. 없으면 실패 `"{L}년 사업보고서 재무제표가 없어요"`
   7. 지주회사면 `holding_exclusion(fin_a)` → 제외
   8. `fin_b = dart.financials(corp, L−2)`
   9. 배당: `L−2, L−4, L−6, L−8` 중 2015 이상인 해만 받아요.
   10. `assemble`
6. 오류 처리
   - 종목마다 `NetworkError`·`DartError`·`KrxError`·`ValueError`가 나면 → 실패 목록에 사유를 남기고 계속해요.
   - `DartQuotaExceeded`가 나면 → 그 종목과 남은 종목 모두를 `pending`에 넣고 멈춰요.
7. 진행 상황: 50종목마다 `progress(f"{i}/{n} 종목 처리 중 (오늘 DART 호출 {dart.calls_today:,}회)")`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_late_filer_uses_previous_year():                    # Review Focus 1
    dart = FakeDart.with_company("000270", dividends={2024: KIA_DIVS_2024}, fin={2024: ..., 2022: ...})   # 2025는 013
    rec = collect(dart, FakeKrx.default(), mem_store(), date(2026,11,14), progress=noop).records["000270"]
    assert rec[1].latest_year == 2024 and rec[1].inputs.years[4].year == 2024
def test_network_error_isolated_to_one_stock():              # Review Focus 3
    dart = FakeDart.two_companies(raise_for={"030000": NetworkError("x")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    assert "000270" in c.records and [f[0] for f in c.failed] == ["030000"]
def test_quota_moves_rest_to_pending():
    c = collect(FakeDart.many(quota_after=3), FakeKrx.many(), mem_store(), D, progress=noop)
    assert len(c.records) >= 1 and c.pending and not set(c.pending) & set(c.records)
def test_new_annual_reports_invalidate_cache():
    store = mem_store(); store.set_meta("filings_checked", "2026-11-07")
    dart = FakeDart.default(filings=[{"corp_code": KIA_CORP}]); collect(dart, FakeKrx.default(), store, D, progress=noop)
    assert dart.invalidated == [KIA_CORP] and store.get_meta("filings_checked") == "2026-11-14"
def test_exclusions_bucketed():
    # FakeKrx 목록: 우선주(kind="우선주"), "하나30호스팩", 회사 induty "6419", 회사 acc_mt "03", 보통 회사 1개
    c = collect(FakeDart.exclusion_mix(), FakeKrx.exclusion_mix(), mem_store(), D, progress=noop)
    assert set(c.excluded) == {"우선주","스팩","금융회사","결산월 12월 아님"} and len(c.records) == 1
def test_quick_fail_skips_statements():
    dart = FakeDart.with_company("000270", dividends={2025: div_rows("1,000","-","900")})
    c = collect(dart, FakeKrx.default(), mem_store(), D, progress=noop)
    assert c.records["000270"][1].quick_fail and dart.calls_of("financials") == 0
def test_collect_one_unknown_code(): assert "찾지 못했어요" in collect_one(FakeDart.default(), FakeKrx.default(), mem_store(), D, "999999")
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_collect.py -v`
  - Expected: FAIL

- [ ] **Step 3: `collect`·`collect_one`·`fakes` 구현**
  - `collect_one`은 `collect`의 종목별 처리 함수를 그대로 다시 써요.

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/collect.py tests/fakes.py tests/test_collect.py`
  - `git commit -m "feat: market-wide collection with quota-aware resume"`

---

### Task 14: 계산, 스냅샷, 이번 주 변화와 원인

**Files:**
- Create: `src/vsf/evaluate.py`, `src/vsf/snapshot.py`, `src/vsf/changes.py`, `tests/test_evaluate.py`, `tests/test_snapshot.py`, `tests/test_changes.py`

**Interfaces:**
- Consumes: `compute`, `summarize`, `watch_state`, `is_near`, `build_industry`, `industry_inputs`, `effective_criteria`, `extra_gate1`, `Collected`, `settings_fingerprint`, `CRITERIA_LABELS`
- Produces:
  - `StockResult`: dataclass. `company`, `assembled`, `criteria`, `extra_gate1: str | None`, `cells: SheetValues`, `summary: Summary`, `industry: IndustryInfo | None`, `state: str`, `near: bool`
  - `RunResult`: dataclass. `collected: Collected`, `settings_fp: dict`, `results: dict[str, StockResult]`
  - `evaluate(collected, settings) -> RunResult`: `build_industry` → 종목마다 `effective_criteria` → `extra_gate1` → `compute` → `summarize` → `watch_state`
  - `evaluate_one(company, assembled, settings, industry: IndustryInfo | None) -> StockResult`
  - `SnapStock`: dataclass. `name`, `inputs: StockInputs`, `criteria: Criteria`, `extra_gate1: str | None`, `state: str`, `near: bool`
  - `Snapshot`: dataclass. `date`, `settings_fp: dict`, `counts: dict[str, int]`, `stocks: dict[str, SnapStock]`
  - `run_counts(run) -> dict[str, int]`: 키는 `buy`, `near`, `watch`, `gate12_ok`
  - `save_snapshot(run, runs_dir) -> Path`: `runs_dir/YYYY-MM-DD.json.gz`. 같은 날이면 덮어써요.
  - `load_previous(runs_dir, before: date) -> Snapshot | None`: `before`보다 앞선 날 중 가장 최근이에요. 같은 날 파일은 무시해요.
  - `Change`: frozen. `code`, `name`, `kind: Literal["new_buy", "new_watch", "above_buy", "left"]`, `causes: tuple[str, ...]`
  - `detect_changes(prev: Snapshot | None, run: RunResult, report: ReportSettings) -> list[Change]`
  - `criteria_changes(prev_fp: dict, cur_fp: dict) -> list[dict]`: `{"key", "label", "old", "new"}`

변화 종류와 원인 규칙:
- **종류** (지난 상태 s0 → 지금 상태 s1):
  - buy가 아니었다가 buy → `new_buy`
  - out → watch → `new_watch`
  - buy → watch → `above_buy`
  - out이 아니었다가 out → `left`
- **원인:** 단계를 나눠 다시 계산해서, 어느 단계에서 상태가 바뀌었는지 봐요.
  - `sA = state(prev.inputs, cur.criteria, cur.extra_gate1)`
  - `sB = state(prev.inputs의 price·price_date만 지금 값으로 바꾼 것, cur.criteria, cur.extra_gate1)`
  - s0≠sA → `"기준 변경"`
  - sA≠sB → `"주가"`
  - sB≠s1 → `"재무 갱신"`
- **지난번에 없던 종목:** s1이 out이 아니면 원인은 `("새로 분석됨",)`.
- **이번에 빠진 종목:** 지난번에 있었는데 이번에 없고 s0가 out이 아니면, 종류 `left`, 원인 `("이번에 분석 안 됨",)`.
- **첫 실행** (prev None): `[]`.

- [ ] **Step 1: 실패하는 테스트 쓰기**

테스트 파일 안의 도우미:
- `snap(kia_price, criteria=Criteria(), latest_eps=None, extra=None)` / `run(...)`: `kia_full_pass` 입력으로 `Snapshot` / `RunResult`를 만들어요. 그 사례의 매수선은 69,713.6원이에요.
- `fp(required_return)`: `settings_fingerprint` 모양의 dict를 만들어요.

```python
def test_snapshot_roundtrip_and_same_day_ignored(tmp_path):
    p = save_snapshot(RUN_1114, tmp_path); assert p.name == "2026-11-14.json.gz"
    assert load_previous(tmp_path, date(2026,11,14)) is None
    assert load_previous(tmp_path, date(2026,11,21)).stocks["000270"].inputs == RUN_1114.results["000270"].assembled.inputs
def test_price_drop_is_price_cause():
    ch = detect_changes(snap(kia_price=97000), run(kia_price=60000), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("주가",))]
def test_criteria_only_change():          # 안전마진 0.10 → 매수선 83,656원 > 72,000원
    ch = detect_changes(snap(kia_price=72000), run(kia_price=72000, criteria=Criteria(safety_margin=0.10)), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("기준 변경",))]
def test_financial_update_cause():        # 최근 해 EPS 40,000 → 보수적 적정가(C) 약 110,580원 → 매수선 약 82,940원
    ch = detect_changes(snap(kia_price=72000), run(kia_price=72000, latest_eps=40000), ReportSettings())
    assert ch == [Change("000270","기아","new_buy",("재무 갱신",))]
def test_combined_causes_in_order():      # 97,000원·기본 기준(out) → 기준만 바꾸면 watch → 주가까지 바꾸면 buy
    ch = detect_changes(snap(kia_price=97000), run(kia_price=72000, criteria=Criteria(safety_margin=0.10)), ReportSettings())
    assert ch[0].kind == "new_buy" and ch[0].causes == ("기준 변경","주가")
def test_new_and_missing_stocks():        # 지난번엔 030000(watch)만, 이번엔 000270(buy)만
    ch = detect_changes(snap_only("030000", state="watch"), run_only("000270", kia_price=60000), ReportSettings())
    assert Change("030000","제일기획","left",("이번에 분석 안 됨",)) in ch
    assert Change("000270","기아","new_buy",("새로 분석됨",)) in ch
def test_first_run_no_changes(): assert detect_changes(None, run(kia_price=60000), ReportSettings()) == []
def test_criteria_changes_labels():
    assert criteria_changes(fp(0.10), fp(0.09)) == [{"key":"required_return","label":"요구수익률","old":0.10,"new":0.09}]
def test_evaluate_applies_override_and_extra_gate():
    s = settings_with(overrides={"30": {"roe_min": 20.0}}, use_in_verdict=True)      # 기아 induty "30121", 종목 1개
    r = evaluate(collected_with_kia(), s).results["000270"]
    assert r.criteria.roe_min == 20.0 and r.cells["D78"] == "탈락"
    assert r.industry.group_code == "ALL" and r.extra_gate1 == "탈락"     # 1개뿐 → 전체 시장, 순위 100% > 50%
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_evaluate.py tests/test_snapshot.py tests/test_changes.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - 스냅샷 JSON: `inputs_to_dict`, `asdict(criteria)`, `ensure_ascii=False`, gzip.

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/evaluate.py src/vsf/snapshot.py src/vsf/changes.py tests/test_evaluate.py tests/test_snapshot.py tests/test_changes.py`
  - `git commit -m "feat: evaluate, weekly snapshots and change causes"`

---

### Task 15: 관문 ④ 판단 자료 (관심 목록 종목)

**Files:**
- Create: `src/vsf/extras.py`, `src/vsf/data/naver.py`, `tests/test_extras.py`

**Interfaces:**
- Consumes: `DartClient.filings`/`financials`, `KrxClient.week_ends`/`daily`, `extract`, `RunResult`
- Produces:
  - `NaverNews(client_id, client_secret, http=None)`
    - `search(query, n=5) -> list[dict]`: `{"title", "url", "date"}`, 제목의 HTML 태그는 지워요.
    - 호출: `https://openapi.naver.com/v1/search/news.json?query=…&display=n&sort=date`, 헤더 `X-Naver-Client-Id`·`X-Naver-Client-Secret`
  - `Extras`: frozen.
    - `disclosures: list[dict]`: `{"date", "title", "url"}`, 최근 90일, 최신 10건, url = `https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`
    - `news: list[dict]`
    - `news_link: str`: `https://search.naver.com/search.naver?where=news&query={quote(이름)}`
    - `quarterly: dict | None`
    - `weekly_closes: list[tuple[str, float]]`
    - `notes: tuple[str, ...]`
  - `quarterly_summary(fin: FinRows, year: int, report: str) -> dict`
    - 키: `label`("2026년 3분기 누적" / "2026년 반기 누적" / "2026년 1분기"), `net_income`, `net_income_prev`, `op_income`, `op_income_prev`
    - 금액은 억 원이에요. `thstrm_add_amount`·`frmtrm_add_amount`를 쓰고, 1분기는 `thstrm_amount`·`frmtrm_q_amount`를 써요.
  - `gather_extras(codes, run, dart, krx, naver: NaverNews | None, today) -> dict[str, Extras]`
    - 분기 실적: `today.year`의 `11014`→`11012`→`11013` 순서로 처음 나오는 걸 써요.
    - 주가 흐름: `krx.week_ends(price_date, 52)`
    - 한 부분이 실패하면 그 부분만 비우고 메모를 남겨요(`"최근 공시를 가져오지 못했어요"` 등). 전체 실행은 계속돼요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_quarterly_label_and_values(): q = quarterly_summary(fin_q3(), 2026, "11014"); assert q["label"] == "2026년 3분기 누적" and q["net_income"] == 1.5
def test_no_naver_key_gives_link_only():
    e = gather_extras(["000270"], RUN, FakeDart.default(), FakeKrx.default(), None, D)["000270"]
    assert e.news == [] and e.news_link.endswith("%EA%B8%B0%EC%95%84")
def test_news_titles_stripped(): assert NaverNews("i","s", http=mock_news("<b>기아</b> 실적")).search("기아")[0]["title"] == "기아 실적"
def test_disclosure_failure_isolated():
    e = gather_extras(["000270"], RUN, FakeDart.default(raise_on="filings"), FakeKrx.default(), None, D)["000270"]
    assert e.disclosures == [] and "최근 공시를 가져오지 못했어요" in e.notes and e.quarterly is not None
def test_weekly_closes_52(): assert len(gather_extras(["000270"], RUN, FakeDart.default(), FakeKrx.calendar(), None, D)["000270"].weekly_closes) == 52
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_extras.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/extras.py src/vsf/data/naver.py tests/test_extras.py`
  - `git commit -m "feat: gate-4 research material for watchlist stocks"`

---

### Task 16: 리포트 자료(payload) 만들기

**Files:**
- Create: `src/vsf/report/__init__.py`, `src/vsf/report/payload.py`, `tests/test_payload.py`

**Interfaces:**
- Consumes: `RunResult`, `Change`, `Snapshot`, `Extras`, `Settings`, `run_counts`, `inputs_to_dict`
- Produces:
  - `SCHEMA = 1`
  - `build_payload(run, changes, crit_changes: list[dict], prev: Snapshot | None, extras: dict[str, Extras], settings) -> dict`
  - `write_report(payload, reports_dir) -> Path`
    - `reports_dir/<run.date>/`에 `index.html`, `stock.html`, `report.js`, `report.css`를 `src/vsf/report/assets/`에서 복사하고, `data.js`를 써요.
    - 같은 날이면 덮어써요. 돌려주는 값은 `index.html` 경로예요.
  - `data.js` 내용: `window.VSF_DATA = <json>;`
    - `json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`
  - payload 형태 (키 고정):
    ```
    {"schema":1,
     "run":{"date","price_date","analyzed","total_listed","excluded":{사유:[[code,name]]},"failed":[[code,name,사유]],
            "pending":[[code,name]],"partial":bool,"first_run":bool,"criteria":settings_fp,"criteria_changes":[...]},
     "summary":{"buy","near","watch","gate12_ok","prev":{같은 키}|null},
     "changes":[{"code","name","kind","causes"}],
     "watchlist":[code...],        # state가 buy·watch, ratio 오름차순
     "stocks":{code:{"name","code","market","latest_year","industry":{...}|null,"inputs":{...},"cells":{...},
                     "summary":{...},"state","near","flags":[...],"notes":[...],"sources":{...},"quick_fail":bool,
                     "criteria":{...},"criteria_overridden":bool,"extra_gate1":str|null,"extras":{...}|null}}}
    ```
  - `partial`은 `pending`이 비어 있지 않으면 참이에요.
  - `criteria_overridden`은 그 종목에 적용된 기준이 `settings.criteria`와 다르면(업종 덮어쓰기) 참이에요.

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_watchlist_sorted_by_ratio(): assert build_payload(run_3stocks(), [], [], None, {}, S)["watchlist"] == ["A","B"]   # ratio 0.70, 0.78; C는 out
def test_summary_and_prev_counts(): p = build_payload(RUN, [], [], prev_snap(counts={"buy":1,"near":2,"watch":3,"gate12_ok":40}), {}, S); assert p["summary"]["prev"]["buy"] == 1
def test_flags_and_sources_present(): s = build_payload(RUN_FLAGGED, [], [], None, {}, S)["stocks"]["000270"]; assert s["flags"] and s["sources"]["F27"]
def test_no_nan_and_partial(tmp_path):
    p = build_payload(run_with_pending(), [], [], None, {}, S); assert p["run"]["partial"] is True
    idx = write_report(p, tmp_path); assert idx.name == "index.html"
    assert {f.name for f in idx.parent.iterdir()} == {"index.html","stock.html","report.js","report.css","data.js"}
    assert (idx.parent/"data.js").read_text(encoding="utf-8").startswith("window.VSF_DATA = {")
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_payload.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - Task 17이 채우기 전까지는 `assets/`에 빈 파일 4개를 둬요.

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/report tests/test_payload.py`
  - `git commit -m "feat: report payload and writer"`

---

### Task 17: 리포트 화면 (HTML/CSS/JS)

**Files:**
- Modify: `src/vsf/report/assets/index.html`, `stock.html`, `report.js`, `report.css`
- Create: `tests/js/report.test.js`, `tests/js/sample_data.js`

**Interfaces:**
- Consumes: Task 16의 payload 형태
- Produces (`report.js`):
  - 일반 `<script>`로 불러요. `file://`에서 ES 모듈이 막히기 때문이에요.
  - 전역 함수이면서, `module`이 있으면 `module.exports`로도 내보내요.
  - `esc(s) -> string`
  - `renderIndex(data) -> string`
  - `renderStock(data, code) -> string`
  - `searchStocks(data, query) -> Array<{code, name}>`: 이름 일부나 코드로 찾아요. 최대 20개.
- 부트스트랩:
  - `index.html`: `#app`에 `renderIndex(window.VSF_DATA)`를 넣어요.
  - `stock.html`: `location.hash`(`#000270`)로 `renderStock`. 종목이 없으면 `"이 종목은 이번 실행에서 분석되지 않았어요"`.
  - 두 파일 모두 `<script src="data.js">` 다음에 `<script src="report.js">`예요.

화면 내용 (스펙 7.2·7.3, 문구 고정):
- **첫 페이지 머리**
  - `"{YYYY}년 {M}월 {D}일 실행 · {price_date 같은 형식} 종가 기준 · 분석 {analyzed}개 / 상장 {total_listed}개 · 제외 {n}개"`
- **배너**
  - partial: `"전체 {total}개 중 {analyzed}개만 분석했어요. 내일 다시 실행하면 이어서 받아요."`
  - 기준 변경: `"지난 실행과 기준이 달라졌어요: {label} {old} → {new}"`
  - 첫 실행: `"첫 실행이라 비교할 지난 결과가 없어요"`
- **요약 타일 4개**
  - `"매수선 이하"`, `"매수선까지 10% 이내"`, `"관심 목록 (20% 이내)"`, `"①② 탈락 아님"`
  - 퍼센트는 설정값으로 써요. 지난 실행 값이 있으면 `"지난주 {n}"`.
- **이번 주 변화 표**
  - 종류: `new_buy`="새로 매수선 이하", `new_watch`="새로 관심 목록", `above_buy`="매수선 위로", `left`="관심 목록에서 빠짐"
  - 원인은 칩으로 보여줘요.
- **관심 목록 표의 열**
  - 종목(업종), ①②③ 배지, 주가÷적정가(소수 둘째), 매수선까지(%), 지금 배당수익률(%), 적정가 방법, 업종 ROE 순위(`"상위 {x}%"`), 경고
- **경고 칩**
  - `flags`가 있는 종목에는 첫 페이지 행과 카드 머리 모두에 `"숫자 확인 필요"` 칩을 반드시 붙여요.
- **검색창**과 제외·실패·대기 목록(`<details>`)
- **종목 카드**
  - 머리: 종목명(코드), 업종, 시장, `"최근 연도 {latest_year}"`.
    - `criteria_overridden`이면 `"업종 기준 적용"` 칩을 달아요.
  - 관문 ①②③ 배지와 ④ 배지. D135가 `"입력 필요"`면 ④ 배지는 `"직접 판단 필요"`예요.
  - `extra_gate1`이 있으면 관문 ① 표에 행 하나를 더해요: `"업종 안 ROE 순위" | "상위 {x}%" | "상위 {roe_top_percent}% 이내" | {extra_gate1}`.
  - 현재가, 보수적 적정가(방법), 매수선, 주가÷적정가 막대, B15 문장
  - 적정가 A·B·C
  - 관문 ①·② 표(B/C/D열)
  - 5-1, 5-3, 5-4 표
  - 5년 입력 표 + 그 이전 5년 DPS. 칸마다 출처를 `title`과 출처 표로 보여줘요.
  - EPS 막대 + 정상 EPS 점선 SVG, 10년 DPS 막대 SVG, 주간 종가 선 SVG(extras가 있을 때)
  - 업종 비교 (참고)
  - 관문 ④ 자료: 공시, 뉴스 또는 링크, 분기 실적, 세 질문과 C131·C132 문장
  - 메모(`notes`)
  - `"uv run run.py --excel {code}"` 안내
- **quick fail 카드**
  - 메모를 맨 위에 두고, 배당 표와 판정만 보여줘요.
- **이스케이프:** 모든 글자는 `esc()`를 거쳐요.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`node:test` + `assert`)

`sample_data.js`는 손으로 쓴 작은 payload예요.
- 종목 3개: buy·watch·out
- flagged 1개, quick_fail 1개
- 변화 2개, 기준 변경 1개, 이름에 `<script>`가 든 종목 1개

```js
const r = require('../../src/vsf/report/assets/report.js'); const data = require('./sample_data.js');
test('index shows banners, tiles, changes', () => { const h = r.renderIndex(data);
  for (const s of ['지난 실행과 기준이 달라졌어요','매수선 이하','새로 매수선 이하','주가','지난주']) assert.ok(h.includes(s)); });
test('watchlist order follows payload', () => { const h = r.renderIndex(data); assert.ok(h.indexOf(data.stocks.A.name) < h.indexOf(data.stocks.B.name)); });
test('flagged stock always shows warning chip', () => {
  assert.ok(r.renderIndex(data).includes('숫자 확인 필요')); assert.ok(r.renderStock(data, 'F').includes('숫자 확인 필요')); });
test('names are escaped', () => { assert.ok(!r.renderIndex(data).includes('<script>alert')); });
test('stock card core sections', () => { const h = r.renderStock(data, 'A');
  for (const s of [data.stocks.A.cells.B15, '직접 판단 필요', '<svg', 'uv run run.py --excel A', data.stocks.A.sources.F27]) assert.ok(h.includes(s)); });
test('quick fail card', () => { assert.ok(r.renderStock(data, 'Q').includes('나머지 숫자는 받지 않았어요')); });
test('search by name and code', () => {
  assert.deepEqual(r.searchStocks(data, '기아').map(x => x.code), ['000270']); assert.equal(r.searchStocks(data, '000270').length, 1); });
```

- [ ] **Step 2: 실패 확인**
  - Run: `node --test tests/js/`
  - Expected: FAIL

- [ ] **Step 3: 화면 구현**
  - CSS는 가볍게: 표, 배지 색, 칩, 360px 폭에서도 표가 가로로 스크롤되게.
  - 그래프는 `report.js` 안의 작은 SVG 함수로 그려요.

- [ ] **Step 4: 통과 확인**
  - Run: `node --test tests/js/`
  - Expected: PASS

- [ ] **Step 5: 수동 확인**
  - `uv run python -c "…build_payload(가짜 RunResult)…write_report(…)"`로 만든 `index.html`을 `open`으로 열어요.
  - 검색과 카드 이동이 되는지 봐요.

- [ ] **Step 6: 커밋**
  - `git add src/vsf/report/assets tests/js`
  - `git commit -m "feat: static report pages rendered from data.js"`

---

### Task 18: 엑셀 내보내기 (Numbers용)

**Files:**
- Create: `src/vsf/export_xlsx.py`, `tools/numbers_check.py`, `tests/test_export_xlsx.py`

**Interfaces:**
- Consumes: `to_cells`, `criteria_to_cells`, `FORMULA_CELLS`, `SheetValues`, `StockInputs`, `Criteria`, `compute`
- Produces:
  - `safe_sheet_name(name: str, taken: set[str]) -> str`
    - `[]:*?/\` 를 지우고 앞뒤 공백과 `'`를 잘라요.
    - 31자로 잘라요. 비면 `"분석"`이에요.
    - `taken`과 겹치면 `" (2)"`를 붙여요.
  - `safe_file_stem(text: str) -> str`: `/:\*?"<>|`와 공백을 `_`로 바꿔요.
  - `NUMBERS_GUIDE = "Numbers에서는 ④ 질문 칸에 '예', '아니오', '모르겠음' 중 하나를, 나의 판단 칸에 '일시적', '구조적', '모르겠음' 중 하나를 글자 그대로 입력해요."`
  - `export_xlsx(template: Path, out_dir: Path, inputs: StockInputs, cells: SheetValues, criteria: Criteria, today: date, extra_note: str = "") -> Path`

`export_xlsx` 규칙:
0. **B23 메모:** `inputs.memo + " " + NUMBERS_GUIDE`예요. `extra_note`가 있으면 `" 업종 비교 항목(엑셀에는 없음): " + extra_note`를 덧붙여요.
1. **원본 지키기:** 템플릿을 바이트로 읽어 메모리에서 고쳐요. 결과 경로가 템플릿 경로와 같으면 `ValueError`예요.
2. **시트 찾기:** `workbook.xml`과 rels로 `분석_빈칸`의 XML 경로를 찾아요.
3. **입력 칸 쓰기** (lxml):
   - 숫자: `t="n"` `<v>`
   - 글자: `t="inlineStr"` `<is><t>…</t></is>`
   - B21 날짜: 직렬값 `(d − date(1899,12,30)).days`
   - `None`: 값 자식을 지우고 스타일은 남겨요.
   - 칸이 없으면 행 안에 열 순서를 지켜 끼워 넣어요.
4. **수식 칸 결과값 쓰기:** `<f>`는 그대로 두고 `cells`의 결과값을 `<v>`에 넣어요.
   - 숫자: `t="n"`
   - 글자: `t="str"`
   - `None`: `t="str"`, 빈 `<v/>`
5. **시트 이름 바꾸기:** `workbook.xml`의 시트 이름을 `safe_sheet_name(inputs.name, 다른 시트 이름들)`으로 바꿔요. 그 시트의 drawing → chart XML에서 `'분석_빈칸'!`을 `'<새 이름>'!`으로 바꿔요.
6. **기준값 쓰기:** `기준값` 시트의 B5–B15에 `criteria_to_cells(criteria)`를 써요.
7. **다시 계산 설정:** `<calcPr fullCalcOnLoad="1">`을 유지해요.
8. **파일 이름:** `out_dir/{today}_{safe_file_stem(name)}_{code}.xlsx`. 이미 있으면 `_2`, `_3`…을 붙여요.

`tools/numbers_check.py <xlsx> <expected.json> [--sheet 이름]`:
- `osascript`로 Numbers에서 파일을 열고, 시트 이름의 `table 1`에서 칸 값을 읽어 기대값과 비교해요.
- 이어서 B129에 "테스트", B130·B131·B132에 "예", B133에 "일시적"을 넣고 D135가 `"통과"`로 다시 계산되는지 확인해요.
- 마지막에 저장하지 않고 닫아요.
- 핵심 AppleScript:
  ```applescript
  tell application "Numbers"
    set d to open POSIX file "<xlsx>"
    set t to table 1 of sheet "<시트>" of d
    set v to value of cell "D82" of t
    set value of cell "B130" of t to "예"
    close d saving no
  end tell
  ```

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
@pytest.mark.template
def test_export_kia(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia"); cells = compute(inputs, c)
    before = sha256(template_path); p = export_xlsx(template_path, tmp_path, inputs, cells, c, date(2026,11,14))
    assert p.name == "2026-11-14_기아_000270.xlsx" and sha256(template_path) == before
    x = XlsxReader(p)                                   # tests/helpers.py: zip+lxml로 칸 읽기
    assert "기아" in x.sheet_names and "분석_빈칸" not in x.sheet_names
    assert x.cell("기아","B19") == ("inlineStr","000270") and x.cell("기아","F27")[1] == "19382"
    assert x.cell("기아","B21")[1] == "46335" and x.cell("기아","D82") == ("str","통과")
    assert x.cell("기아","B15")[1] == cells["B15"] and "'기아'!$B$27:$F$27" in x.chart_xml_for("기아")
    assert x.cell("기준값","B5")[1] == "0.1"
    assert NUMBERS_GUIDE in x.cell("기아","B23")[1]
@pytest.mark.template
def test_criteria_written(template_path, tmp_path):
    inputs, _, _ = load_oracle("kia"); c = Criteria(required_return=0.09)
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D); assert XlsxReader(p).cell("기준값","B5")[1] == "0.09"
@pytest.mark.template
def test_never_overwrites(template_path, tmp_path):
    a = export_xlsx(...); b = export_xlsx(...); assert a != b and b.name.endswith("_2.xlsx") and a.exists()
@pytest.mark.template
def test_unsafe_names_are_sanitized(template_path, tmp_path):     # Review Focus 4
    for name in ("A/B:C*D?[E]", "가" * 40):
        p = export_xlsx(template_path, tmp_path, replace(KIA, name=name), compute(replace(KIA, name=name), Criteria()), Criteria(), D)
        sn = [s for s in XlsxReader(p).sheet_names if s not in OTHER_SHEETS][0]
        assert len(sn) <= 31 and not set(sn) & set('[]:*?/\\') and p.exists()
@pytest.mark.template
@pytest.mark.slow
def test_export_recalculates_same(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia_full_pass"); cells = compute(inputs, c)
    got = formulas_eval(export_xlsx(template_path, tmp_path, inputs, cells, c, D), sheet="기아")   # tests/helpers.py
    for a in ("D82","D90","D110","D135","B105","B107","B15"): assert got[a] == pytest.approx(cells[a]) if isinstance(cells[a], float) else got[a] == cells[a]
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_export_xlsx.py -v`
  - Expected: FAIL

- [ ] **Step 3: `export_xlsx`와 `tools/numbers_check.py` 구현**

- [ ] **Step 4: 통과 확인**
  - Run: 같은 명령
  - Expected: PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/export_xlsx.py tools/numbers_check.py tests/test_export_xlsx.py tests/helpers.py`
  - `git commit -m "feat: fill calculator xlsx for Numbers without touching the original"`

---

### Task 19: 명령어 연결 (`run.py`)

**Files:**
- Create: `src/vsf/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: 앞 task의 모든 공개 함수
- Produces:
  - `Deps`: dataclass. 테스트에서 바꿔 끼워요.
    - `make_dart(keys, store, settings)`, `make_krx(keys, store)`, `make_naver(keys) -> NaverNews | None`
    - `today() -> date`, `open_path(Path) -> None`, `keep_awake() -> None`
  - `main(argv: list[str] | None = None, deps: Deps | None = None) -> int`
    - 옵션: `--excel CODE`, `--no-open`, `--settings PATH`(기본 `settings.toml`), `--keys PATH`(기본 `keys.toml`)

동작:
- **설정 오류:** `ConfigError`면 메시지만 stderr에 쓰고 2를 돌려줘요.
- **주간 실행** (기본)
  1. `keep_awake()`: macOS에서 `caffeinate -i -w <pid>`를 띄워요. 없으면 그냥 넘어가요.
  2. `collect` → `evaluate` → `load_previous` → `detect_changes`, `criteria_changes`
     - 스냅샷 폴더 `runs_dir`은 `settings.data_dir / "runs"`, 저장소는 `settings.data_dir / "vsf.sqlite3"`예요.
  3. `gather_extras`: 관심 목록 종목만 (스펙 7.3)
  4. `build_payload` → `write_report` → `save_snapshot`
  5. 요약 출력:
     - `"관심 목록 {n}개, 매수선 이하 {m}개 (새로 {k}개)"`
     - `"리포트: {경로}"`
     - pending이 있으면 `"오늘 DART 호출 한도 때문에 {n}개 종목을 못 받았어요. 내일 다시 실행하면 이어서 받아요."`
  6. `--no-open`이 아니면 `open_path(index)`
  7. 0을 돌려줘요.
- **`--excel CODE`**
  1. `load_previous(runs_dir, today+1일)`의 그 종목이 있으면 그 입력과 기준을 써요.
  2. 없으면 `collect_one` → `evaluate_one(industry=None)`
  3. `export_xlsx` → `"엑셀 파일: {경로}"` 출력 → `--no-open`이 아니면 `open_path`
     - `extra_gate1`이 있으면 `extra_note`는 `"상위 {x}% → {extra_gate1}"`예요.
  4. 종목을 못 찾으면 사유를 출력하고 1을 돌려줘요.
- **예상 못 한 예외**
  - `data/logs/{YYYYMMDD-HHMMSS}.log`에 트레이스백을 써요.
  - 화면에는 `"예상하지 못한 오류가 났어요: {e}. 자세한 내용은 {로그 경로}에 남겼어요."`만 쓰고 1을 돌려줘요.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`FakeDart`·`FakeKrx`, `tmp_path` 설정)

```python
def test_config_error_exit_code(tmp_path, capsys):          # Review Focus 5
    bad = write_settings(tmp_path, criteria={"safety_margin": '"25%"'})
    assert main(["--settings", str(bad), "--no-open"], deps=fake_deps(tmp_path)) == 2
    err = capsys.readouterr().err; assert "safety_margin" in err and "Traceback" not in err
def test_weekly_run_writes_report_and_snapshot(tmp_path):
    d = fake_deps(tmp_path); assert main(["--settings", str(settings_in(tmp_path))], deps=d) == 0
    assert (tmp_path/"reports"/"2026-11-14"/"index.html").exists() and (tmp_path/"data"/"runs"/"2026-11-14.json.gz").exists()
    assert d.opened == [tmp_path/"reports"/"2026-11-14"/"index.html"]
def test_no_open(tmp_path): d = fake_deps(tmp_path); main([..., "--no-open"], deps=d); assert d.opened == []
def test_partial_run_message(tmp_path, capsys):
    main([...], deps=fake_deps(tmp_path, quota_after=1)); assert "내일 다시 실행하면 이어서 받아요" in capsys.readouterr().out
def test_excel_uses_snapshot(tmp_path): ...   # 주간 실행 후 --excel 000270 → exports/에 파일, dart 추가 호출 없음
def test_excel_unknown_code(tmp_path): assert main([..., "--excel", "999999", "--no-open"], deps=fake_deps(tmp_path)) == 1
def test_unexpected_error_logged(tmp_path, capsys): ...   # make_krx가 RuntimeError → 1, 로그 파일 생성, 화면에 Traceback 없음
```

- [ ] **Step 2: 실패 확인**
  - Run: `uv run pytest tests/test_cli.py -v`
  - Expected: FAIL

- [ ] **Step 3: `cli.py` 구현**
  - 기본 `Deps`는 실제 클라이언트, `date.today`, `subprocess.run(["open", path])`를 써요.

- [ ] **Step 4: 통과 확인**
  - Run: `uv run pytest -v && node --test tests/js/`
  - Expected: 모두 PASS

- [ ] **Step 5: 커밋**
  - `git add src/vsf/cli.py tests/test_cli.py`
  - `git commit -m "feat: run.py weekly run and --excel export"`

---

### Task 20: 실제 자료로 확인 (스펙 10장 완료 기준)

선행 조건:
- `keys.toml`의 DART·KRX 키
- Numbers 자동화 허용: 처음 `osascript`를 실행할 때 macOS가 묻는 창에서 사용자가 '허용'

**Files:**
- Create: `tools/compare_examples.py`, `docs/validation/2026-11-XX-real-data-check.md`
- Modify (필요할 때만): `src/vsf/data/accounts.py`, `src/vsf/data/assemble.py`와 해당 테스트

- [ ] **Step 1: 예시 두 종목 비교표 만들기**
  - 2026년 1~3월에 실행하면 L이 2024일 수 있어요. 그러면 연도 열이 예시와 한 칸 어긋나니 그만큼 맞춰서 비교해요.
  - Run: `uv run python tools/compare_examples.py`
  - 하는 일:
    - `collect_one`으로 기아·제일기획을 받아요.
    - 템플릿 예시 시트의 노란 칸과 칸별로 비교해요: 칸, 예시값, 자동값, 차이%, 출처.
    - ①②③ 판정, 적정가 방법, 적정가 차이를 비교해요.
    - 결과를 `docs/validation/<오늘>-real-data-check.md`에 써요.
  - Expected: 파일 생성.
  - 5% 넘게 차이 나는 칸마다 둘 중 하나를 해요.
    - 계정 매핑을 고치고 테스트를 추가해요.
    - 또는 설명을 적어요. 예: 기아 영업현금흐름은 예시가 조 원 단위 반올림값, PER은 한경 표 vs 종가÷EPS, 설비투자가 새로 채워져 관문 ②가 바뀜.

- [ ] **Step 2: 전체 시장 첫 실행**
  - Run: `uv run run.py`
  - Expected: 리포트가 열려요. 첫 실행이라 몇 시간 걸릴 수 있어요.
  - 하루 한도에 걸리면 다음 날 다시 실행해서 이어 받아요.
  - 확인할 것:
    - 머리글 숫자(분석/상장/제외)가 상식적인지
    - 제외 사유별 목록에서 5개씩 골라 사유가 맞는지
    - 실패 목록의 사유
    - '숫자 확인 필요'가 붙은 종목을 검색해서 카드와 첫 페이지 모두에 칩이 보이는지 (스펙 10장 5번)

- [ ] **Step 3: 두 번째 실행으로 변화 원인 확인**
  - `settings.toml`의 `required_return`을 0.09로 바꾸고 `uv run run.py --no-open`을 실행해요.
  - Expected:
    - 기준 변경 배너
    - 변화 표에 '기준 변경' 원인
  - 확인한 뒤 0.10으로 되돌려요.

- [ ] **Step 4: Numbers 확인**
  - Run: `uv run run.py --excel 000270 --no-open`
  - 그다음: `uv run python tools/numbers_check.py exports/<파일>.xlsx <기대값.json>`
    - 기대값은 같은 실행 스냅샷에서 계산한 cells예요.
  - Expected:
    - 모든 칸 일치
    - ④ 입력 뒤 D135 = "통과"
    - EPS 그래프와 색 표시가 보임
  - 마지막으로 사용자가 Numbers에서 한 번 눈으로 확인해요.

- [ ] **Step 5: 결과 기록과 커밋**
  - 검증 문서에 Step 2–4의 결과(숫자, 확인한 종목, 남은 문제)를 적어요.
  - `git add docs/validation tools/compare_examples.py src tests`
  - `git commit -m "test: real-data validation against example sheets and full run"`
