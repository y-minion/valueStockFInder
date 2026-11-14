"""여러 테스트가 같이 쓰는 도우미."""
import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from vsf.model import (FORMULA_CELLS, Criteria, SheetValues, StockInputs, inputs_from_dict,
                       to_cells)

ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / "tests" / "fixtures" / "oracle"
ORACLE_NAMES: list[str] = sorted(p.stem for p in ORACLE_DIR.glob("*.json"))


def write_settings(tmp_path: Path, criteria: dict[str, str] | None = None,
                   overrides: str | None = None) -> Path:
    """배포용 settings.toml을 tmp_path에 복사하고 해당 줄만 바꿔요.

    criteria: {키: TOML 값 글자}. 이미 있는 키는 줄을 바꾸고, 없는 키는 [criteria] 끝에 넣어요.
    overrides: [industry.overrides] 본문 전체를 이 글자로 바꿔요.
    """
    text = (ROOT / "settings.toml").read_text(encoding="utf-8")
    for key, value in (criteria or {}).items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        if pattern.search(text):
            text = pattern.sub(lambda _: f"{key} = {value}", text, count=1)
        else:
            text = text.replace("\n[report]", f"{key} = {value}\n\n[report]", 1)
    if overrides is not None:
        text = re.sub(r"(\[industry\.overrides\]\n).*?(?=^\[)",
                      lambda m: m.group(1) + overrides + "\n\n", text, count=1, flags=re.S | re.M)
    out = tmp_path / "settings.toml"
    out.write_text(text, encoding="utf-8")
    return out


def load_oracle(name: str) -> tuple[StockInputs, Criteria, SheetValues]:
    """tests/fixtures/oracle/<name>.json → (입력, 기준, 수식 칸 값)."""
    doc = json.loads((ORACLE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return inputs_from_dict(doc["inputs"]), Criteria(**doc["criteria"]), doc["cells"]


def assert_cells_match(got: SheetValues, want: SheetValues, cells: Iterable[str]) -> None:
    """숫자는 상대·절대 1e-9 안에서, 글자와 None은 정확히 같아야 해요. 어긋난 칸을 모두 모아 보여줘요."""
    bad = []
    for addr in cells:
        g, w = got.get(addr), want.get(addr)
        both_num = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (g, w))
        same = math.isclose(g, w, rel_tol=1e-9, abs_tol=1e-9) if both_num else (g == w and type(g) is type(w))
        if not same:
            bad.append(f"{addr}: 나온 값 {g!r} / 기대한 값 {w!r}")
    assert not bad, "칸 값이 달라요:\n" + "\n".join(bad)


def _normalize(v):
    """엑셀에서 읽은 값을 정답 자료와 같은 모양으로: "" → None, 정수 → float, 날짜 → date."""
    if isinstance(v, datetime):
        return v.date()
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return v


def _read(template: Path, sheet: str, addresses: Iterable[str]) -> dict:
    wb = openpyxl.load_workbook(template, data_only=True)
    ws = wb[sheet]
    return {a: _normalize(ws[a].value) for a in addresses}


def input_values(template: Path, sheet: str, exclude: Iterable[str] = ()) -> dict:
    """시트에서 to_cells가 만드는 입력 칸 주소의 값을 읽어요."""
    skip = set(exclude)
    return _read(template, sheet, [a for a in to_cells(StockInputs()) if a not in skip])


def stored_values(template: Path, sheet: str) -> SheetValues:
    """시트에 저장돼 있는 FORMULA_CELLS의 값 (엑셀이 마지막으로 저장한 값)."""
    return _read(template, sheet, FORMULA_CELLS)


def approx_cells(cells: dict, exclude: Iterable[str] = ()) -> dict:
    """to_cells 결과의 숫자를 pytest.approx로 감싸서, 엑셀에서 읽은 값과 == 로 비교할 수 있게 해요."""
    skip = set(exclude)
    return {a: (pytest.approx(float(v), rel=1e-9, abs=1e-9)
                if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for a, v in cells.items() if a not in skip}


RECORDED_DART = ROOT / "tests" / "fixtures" / "dart" / "recorded"
_RECORDED_FIN = {"kia": "000270", "cheil": "030000"}
_NO_ID = "-표준계정코드 미사용-"


def load_fin(name: str):
    """녹화한 재무제표 응답을 읽어요. 이름 예: "kia_2025_cfs" → fin_000270_2025_cfs.json."""
    from vsf.data.dart import FinRows

    company, year, fs = name.split("_")
    doc = json.loads((RECORDED_DART / f"fin_{_RECORDED_FIN[company]}_{year}_{fs}.json")
                     .read_text(encoding="utf-8"))
    rows = doc["list"]
    return FinRows(rows=rows, fs=fs.upper(), rcept_no=rows[0]["rcept_no"])


def fin_row(sj_div: str, account_id: str, account_nm: str, thstrm="", frmtrm="", bfefrmtrm="",
            ord: int = 1) -> dict:
    """fnlttSinglAcntAll 목록 한 줄을 문서화된 모양 그대로 만들어요 (금액은 글자)."""
    return {"rcept_no": "20260310000001", "reprt_code": "11011", "bsns_year": "2025",
            "corp_code": "99000270", "sj_div": sj_div, "account_id": account_id,
            "account_nm": account_nm, "thstrm_amount": str(thstrm), "frmtrm_amount": str(frmtrm),
            "bfefrmtrm_amount": str(bfefrmtrm), "ord": str(ord), "currency": "KRW"}


def synthetic(capex_name: str | None = None, eps_rows: list[tuple[str, float]] | None = None,
              extra: list[dict] | None = None, defaults: bool = True):
    """합성 재무제표 (FinRows). 이자비용 줄은 일부러 없어요.

    capex_name: 주면 유형자산 취득 줄이 표준계정코드 없이 이 이름으로만 들어가요.
    eps_rows: [(이름, 값), …]이면 기본 EPS 줄 대신 이 줄들을 넣어요 (모두 EPS 표준계정코드).
    extra: 덧붙일 줄. defaults=False면 기본 줄 없이 extra만 써요.
    """
    from vsf.data.dart import FinRows

    rows: list[dict] = []
    if defaults:
        rows += [
            fin_row("BS", "ifrs-full_CurrentAssets", "유동자산", "5,000,000", "4,000,000", "3,000,000", 1),
            fin_row("BS", "ifrs-full_Liabilities", "부채총계", "8,000,000", "7,000,000", "6,000,000", 2),
            fin_row("BS", "ifrs-full_Equity", "자본총계", "20,000,000", "18,000,000", "16,000,000", 3),
            fin_row("IS", "ifrs-full_ProfitLoss", "당기순이익(손실)", "7,600,000", "6,000,000", "5,000,000", 4),
            fin_row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                    "지배기업의 소유주에게 귀속되는 당기순이익(손실)", "7,560,983", "5,900,000", "4,900,000", 5),
            fin_row("IS", "dart_OperatingIncomeLoss", "영업이익", "9,000,000", "7,000,000", "6,000,000", 6),
            fin_row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름",
                    "10,000,000", "9,000,000", "8,000,000", 7),
            fin_row("CF", _NO_ID if capex_name else
                    "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                    capex_name or "유형자산의 취득", "-3,000,000", "-2,500,000", "-2,000,000", 8),
            fin_row("CF", "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "배당금의 지급",
                    "-1,500,000", "-1,200,000", "-1,000,000", 9),
        ]
        if eps_rows is None:
            rows.append(fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", "기본주당이익(손실)",
                                "19,382", "15,000", "12,000", 10))
    for i, (name, value) in enumerate(eps_rows or []):
        rows.append(fin_row("IS", "ifrs-full_BasicEarningsLossPerShare", name, f"{value:,}",
                            ord=20 + i))
    rows += extra or []
    return FinRows(rows=rows, fs="CFS", rcept_no="20260310000001")


# ---- Task 10: 계산기 입력 조립 ----

RECORDED_KRX = ROOT / "tests" / "fixtures" / "krx" / "recorded"
_RECORDED_DIV_YEARS = (2025, 2023, 2021, 2019, 2017)
_CORP_CLS_MARKET = {"Y": "KOSPI", "K": "KOSDAQ"}


def load_company(name: str):
    """녹화한 company.json → CompanyInfo. 이름 예: "kia" → company_000270.json."""
    from vsf.data.assemble import CompanyInfo

    doc = json.loads((RECORDED_DART / f"company_{_RECORDED_FIN[name]}.json").read_text(encoding="utf-8"))
    return CompanyInfo(corp_code=doc["corp_code"], code=doc["stock_code"], name=doc["corp_name"],
                       market=_CORP_CLS_MARKET.get(doc.get("corp_cls", ""), ""),
                       induty_code=doc["induty_code"], acc_mt=doc["acc_mt"])


def load_divs(name: str) -> dict[int, list[dict]]:
    """녹화한 배당 보고서 5개 → {사업연도: 목록}. 파일: div_{코드}_{연도}.json."""
    code = _RECORDED_FIN[name]
    return {y: json.loads((RECORDED_DART / f"div_{code}_{y}.json").read_text(encoding="utf-8"))["list"]
            for y in _RECORDED_DIV_YEARS}


def _recorded_prices(code: str) -> dict:
    """녹화한 KRX 일별매매정보 파일들에서 한 종목의 PriceRow를 날짜별로 모아요."""
    from vsf.data.accounts import parse_amount
    from vsf.data.krx import DAILY_FIELDS, MARKETS
    from vsf.data.store import PriceRow

    f = DAILY_FIELDS
    out: dict[date, PriceRow] = {}
    for prefix, market in MARKETS:
        for path in sorted(RECORDED_KRX.glob(f"{prefix}_bydd_trd_*.json")):
            day = datetime.strptime(path.stem.rsplit("_", 1)[1], "%Y%m%d").date()
            for r in json.loads(path.read_text(encoding="utf-8"))["OutBlock_1"]:
                if str(r.get(f["code"], "")).strip() == code:
                    out[day] = PriceRow(day, code, str(r.get(f["name"], "")).strip(), market,
                                        parse_amount(r.get(f["close"])), parse_amount(r.get(f["shares"])))
    return out


def load_year_end(name: str) -> dict:
    """녹화한 KRX 일별 자료 중 12월 날짜(연말 거래일)만 → {연도: PriceRow}."""
    return {d.year: row for d, row in _recorded_prices(_RECORDED_FIN[name]).items() if d.month == 12}


def load_price(name: str, day: date):
    """녹화한 KRX 일별 자료에서 그날 종목의 PriceRow."""
    return _recorded_prices(_RECORDED_FIN[name])[day]


def div_rows(thstrm: str, frmtrm: str, lwfr: str, year: int = 2025) -> list[dict]:
    """alotMatter 목록 (문서화된 모양). 보통주 '주당 현금배당금(원)' 줄이 당기·전기·전전기 값을 가져요.

    실제 응답처럼 보통주 배당수익률 줄이 먼저 오고, 값이 없는 우선주 줄도 같이 와요.
    """
    def row(se: str, knd: str, a: str, b: str, c: str) -> dict:
        return {"rcept_no": f"{year + 1}0310000123", "corp_cls": "Y", "corp_code": "99000270",
                "corp_name": "기아", "se": se, "stock_knd": knd, "thstrm": a, "frmtrm": b, "lwfr": c,
                "stlm_dt": f"{year}-12-31"}

    return [row("주당액면가액(원)", "", "5,000", "5,000", "5,000"),
            row("현금배당성향(%)", "", "35.1", "26.1", "25.3"),
            row("현금배당수익률(%)", "보통주", "5.6", "6.4", "5.6"),
            row("현금배당수익률(%)", "우선주", "-", "-", "-"),
            row("주당 현금배당금(원)", "보통주", thstrm, frmtrm, lwfr),
            row("주당 현금배당금(원)", "우선주", "-", "-", "-")]


ORIGINAL_OLD_EPS = 11874.0   # 합성 회사 B 보고서(2023 사업보고서)에 적힌 2021년 EPS
SYN_SHARES = 405_363_347
SYN_PRICE_DATE = date(2026, 11, 13)
_SYN_YEARS = (2021, 2022, 2023, 2024, 2025)
# 합성 회사(가짜 기아)의 2021–2025년 값. 금액은 원, EPS는 원/주, 보고서에 적히는 부호 그대로(현금 유출은 음수).
_SYN_ACCOUNTS: tuple[tuple[str, str, str, tuple[int, ...]], ...] = (
    ("BS", "ifrs-full_CurrentAssets", "유동자산",
     (30_000_000_000_000, 33_000_000_000_000, 38_000_000_000_000, 42_000_000_000_000, 44_000_000_000_000)),
    ("BS", "ifrs-full_Liabilities", "부채총계",
     (29_700_000_000_000, 33_150_000_000_000, 32_980_000_000_000, 35_410_000_000_000, 35_860_000_000_000)),
    ("BS", "ifrs-full_EquityAttributableToOwnersOfParent", "지배기업의 소유주에게 귀속되는 자본",
     (32_400_000_000_000, 37_900_000_000_000, 45_000_000_000_000, 53_500_000_000_000, 58_000_000_000_000)),
    ("BS", "ifrs-full_Equity", "자본총계",
     (32_460_000_000_000, 37_960_000_000_000, 45_060_000_000_000, 53_560_000_000_000, 58_060_000_000_000)),
    ("IS", "dart_OperatingIncomeLoss", "영업이익(손실)",
     (5_065_700_000_000, 7_233_100_000_000, 11_607_900_000_000, 12_667_100_000_000, 9_078_000_000_000)),
    ("IS", "ifrs-full_InterestExpense", "이자비용",
     (170_400_000_000, 234_500_000_000, 184_200_000_000, 104_500_000_000, 78_560_000_000)),
    ("IS", "ifrs-full_ProfitLoss", "당기순이익(손실)",
     (4_790_000_000_000, 5_440_000_000_000, 8_810_000_000_000, 9_810_000_000_000, 7_600_000_000_000)),
    ("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업의 소유주에게 귀속되는 당기순이익(손실)",
     (4_760_450_000_000, 5_409_429_000_000, 8_776_970_000_000, 9_772_957_000_000, 7_560_983_456_789)),
    ("IS", "ifrs-full_BasicEarningsLossPerShare", "기본주당이익(손실)",
     (int(ORIGINAL_OLD_EPS), 13_495, 22_168, 24_893, 19_382)),
    ("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름",
     (7_400_000_000_000, 9_300_000_000_000, 11_300_000_000_000, 12_600_000_000_000, 9_100_012_500_000)),
    ("CF", "ifrs-full_InterestPaidClassifiedAsOperatingActivities", "이자의 지급",
     (-165_000_000_000, -230_000_000_000, -180_000_000_000, -100_000_000_000, -75_000_000_000)),
    ("CF", "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "유형자산의 취득",
     (-1_912_300_000_000, -2_050_000_000_000, -2_511_100_000_000, -2_345_678_901_234, -3_033_300_000_000)),
    ("CF", "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "배당금의 지급",
     (-400_000_000_000, -1_203_000_000_000, -1_402_500_000_000, -2_245_000_000_000, -2_600_000_000_000)),
)
_SYN_PARENT_ONLY = ("ifrs-full_ProfitLossAttributableToOwnersOfParent",
                    "ifrs-full_EquityAttributableToOwnersOfParent")   # 별도 재무제표에는 없는 줄
_SYN_YEAR_END = {2021: (date(2021, 12, 30), 82_600), 2022: (date(2022, 12, 29), 59_200),
                 2023: (date(2023, 12, 28), 100_000), 2024: (date(2024, 12, 30), 100_800),
                 2025: (date(2025, 12, 30), 121_700)}
_SYN_CLOSE_NOW = 97_000
# 배당 보고서 사업연도 → 보통주 주당 현금배당금 (당기, 전기, 전전기)
_SYN_DPS = {2025: ("6,800", "6,500", "5,600"), 2023: ("5,600", "3,500", "3,000"),
            2021: ("3,000", "1,000", "1,150"), 2019: ("1,150", "900", "800"),
            2017: ("800", "1,100", "1,100")}
_KEEP = object()


def _syn_fin(year: int, table: dict[str, dict[int, float]], fs: str, currency: str, rcept_no: str):
    """table(account_id → {연도: 값})로 year 사업보고서 FinRows를 만들어요 (당기·전기·전전기)."""
    from vsf.data.dart import FinRows

    rows = []
    for i, (sj, account_id, name, _) in enumerate(_SYN_ACCOUNTS, 1):
        if account_id not in table:
            continue
        values = [table[account_id].get(year - back) for back in range(3)]
        amounts = ["" if v is None else f"{v:,}" for v in values]
        rows.append({**fin_row(sj, account_id, name, *amounts, ord=i),
                     "rcept_no": rcept_no, "bsns_year": str(year), "currency": currency})
    return FinRows(rows=rows, fs=fs, rcept_no=rcept_no)


def synthetic_company(*, interest_expense=_KEEP, interest_paid=_KEEP, eps=_KEEP, dps=_KEEP,
                      fs: str = "CFS", split_ratio: float | None = None, currency: str = "KRW") -> tuple:
    """assemble(...)에 그대로 넣는 인자 묶음: 합성 회사(가짜 기아, 최근 연도 2025).

    (company, latest_year, fin_a, fin_b, div_reports, year_end, price, price_date)를 돌려줘요.
    - 숫자를 주면 2025년 값(A 보고서 당기, 2025 배당 보고서 당기)이 그 값이 돼요.
    - None을 주면 그 줄을 빼요 (interest_*·eps는 두 재무제표 모두에서, dps는 2025 배당 보고서에서).
    - fs="OFS": 지배기업 귀속 순이익·자본 줄이 없는 별도 재무제표예요.
    - split_ratio=r: 2024년에 r:1 액면분할한 회사예요. 2024·2025년 연말 주식 수 ×r, 그 종가와 현재가 ÷r,
      A 보고서(2025)의 EPS는 세 해 모두 ÷r이고 B 보고서(2023)는 옛 기준 그대로예요.
    - currency: 재무제표 모든 줄의 통화.
    """
    from vsf.data.assemble import CompanyInfo
    from vsf.data.store import PriceRow

    r = split_ratio or 1
    table_b = {aid: dict(zip(_SYN_YEARS, values, strict=True)) for _, aid, _, values in _SYN_ACCOUNTS}
    table_a = {aid: dict(v) for aid, v in table_b.items()}
    if split_ratio:
        table_a["ifrs-full_BasicEarningsLossPerShare"] = {
            y: v / r for y, v in table_b["ifrs-full_BasicEarningsLossPerShare"].items()}
    for account_id, knob in (("ifrs-full_InterestExpense", interest_expense),
                             ("ifrs-full_InterestPaidClassifiedAsOperatingActivities", interest_paid),
                             ("ifrs-full_BasicEarningsLossPerShare", eps)):
        if knob is None:
            table_a.pop(account_id)
            table_b.pop(account_id)
        elif knob is not _KEEP:
            table_a[account_id][2025] = knob
    if fs == "OFS":
        for account_id in _SYN_PARENT_ONLY:
            table_a.pop(account_id)
            table_b.pop(account_id)
    # 사업보고서 하나는 접수번호 하나예요: 재무제표와 배당에 관한 사항(div_rows)이 같은 번호를 써요.
    fin_a = _syn_fin(2025, table_a, fs, currency, "20260310000123")
    fin_b = _syn_fin(2023, table_b, fs, currency, "20240310000123")

    divs = {y: div_rows(*v, year=y) for y, v in _SYN_DPS.items()}
    if dps is None:
        divs[2025] = [row for row in divs[2025]
                      if not (row["se"] == "주당 현금배당금(원)" and row["stock_knd"] == "보통주")]
    elif dps is not _KEEP:
        divs[2025] = div_rows(f"{dps:,}", *_SYN_DPS[2025][1:], year=2025)

    def after_split(y: int) -> float:
        return r if y >= 2024 else 1

    year_end = {y: PriceRow(d, "000270", "기아", "KOSPI", close / after_split(y),
                            float(SYN_SHARES * after_split(y)))
                for y, (d, close) in _SYN_YEAR_END.items()}
    price = PriceRow(SYN_PRICE_DATE, "000270", "기아", "KOSPI", _SYN_CLOSE_NOW / r, float(SYN_SHARES * r))
    company = CompanyInfo(corp_code="99000270", code="000270", name="기아", market="KOSPI",
                          induty_code="30121", acc_mt="12")
    return company, 2025, fin_a, fin_b, divs, year_end, price, SYN_PRICE_DATE
