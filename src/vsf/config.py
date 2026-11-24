"""settings.toml / keys.toml 읽기와 값 검사."""
import json
import math
import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date
from pathlib import Path

from vsf.model import Criteria


class ConfigError(Exception):
    """설정 오류. 메시지는 한국어이고 사용자에게 그대로 보여줘요."""


CRITERIA_LABELS: dict[str, str] = {
    "required_return": "요구수익률",
    "safety_margin": "안전마진",
    "roe_min": "ROE 최소",
    "debt_ratio_max": "부채비율 최대",
    "interest_coverage_min": "이자보상배율 최소",
    "ocf_to_ni_min": "영업현금흐름÷순이익 최소",
    "payout_min": "배당성향 하한",
    "payout_max": "배당성향 상한",
    "fcf_to_div_min": "잉여현금흐름÷배당 최소",
    "abnormal_ratio": "비정상인 해 기준",
    "isa_weight_max": "개별 종목 비중 상한",
    "watch_range": "관심 목록 범위",
    "near_range": "근접 범위",
    "use_in_verdict": "업종 비교를 판정에 넣기",
    "roe_top_percent": "업종 ROE 상위 비율",
    "min_group_size": "업종 최소 묶음 크기",
    "overrides": "업종별 기준 덮어쓰기",
    "include": "금융회사 포함",
    "bank_cet1_min": "은행·금융지주 보통주자본비율 최소",
    "insurer_kics_min": "보험 지급여력비율 최소",
    "securities_ncr_min": "증권 순자본비율 최소",
    "top_n": "점수 순위 첫 화면 개수",
    "grade_a": "A등급 경계",
    "grade_b": "B등급 경계",
    "grade_c": "C등급 경계",
    "subsidiary_stake_min": "상장 자회사로 볼 지분율",
    "items": "점수 항목",
}

_SECTIONS = ("criteria", "report", "industry", "paths", "dart", "financial", "score", "backtest")

_RATE_KEYS = {
    "required_return", "safety_margin", "payout_min", "payout_max",
    "abnormal_ratio", "isa_weight_max", "watch_range", "near_range",
}


@dataclass(frozen=True)
class ReportSettings:
    watch_range: float = 0.20
    near_range: float = 0.10


@dataclass(frozen=True)
class IndustrySettings:
    use_in_verdict: bool = False
    roe_top_percent: float = 50.0
    min_group_size: int = 5
    overrides: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class FinancialSettings:
    include: bool = True
    bank_cet1_min: float = 9.0
    insurer_kics_min: float = 130.0
    securities_ncr_min: float = 100.0


@dataclass(frozen=True)
class ItemRule:
    """점수 항목 하나: 배점(points)과 구간(steps: (경계, 점수)를 위에서부터 봐요)."""

    points: float
    steps: tuple[tuple[float, float], ...] = ()
    none_points: float | None = None    # 자사주 보유 비율: 0주일 때 점수


# 항목 키 → 비교 방향. lt 미만 · le 이하 · ge 이상 · gt 초과 · flag 예/아니오 · freq 한 해 지급 횟수 이상
ITEM_OPS: dict[str, str] = {
    "per": "lt", "pbr": "lt", "ratio": "le",
    "roe": "ge", "no_loss": "flag", "ttm": "ge",
    "payout": "flag", "coverage": "flag",
    "yield": "gt", "streak": "ge", "freq": "freq", "buyback": "flag", "cancel": "gt", "treasury": "lt",
    "subsidiary": "flag",
}

DEFAULT_ITEMS: dict[str, ItemRule] = {
    # 2026-11-24 조정: 싼가 35→25 (상위권에서 거의 만점이라), 배당 지속성 10 새로 (스펙 13장)
    "per": ItemRule(10, ((5, 10), (8, 7), (10, 5), (15, 2))),
    "pbr": ItemRule(3, ((0.3, 3), (0.6, 2), (1.0, 1))),
    "ratio": ItemRule(12, ((0.75, 12), (0.9, 8), (1.0, 5), (1.2, 2))),
    "roe": ItemRule(10, ((15, 10), (10, 7), (8, 5), (5, 2))),
    "no_loss": ItemRule(5),
    "ttm": ItemRule(5, ((0.9, 5), (0.7, 3))),
    "payout": ItemRule(5),
    "coverage": ItemRule(5),
    "yield": ItemRule(10, ((7, 10), (5, 7), (3, 5), (0, 2))),
    "streak": ItemRule(5, ((7, 5), (5, 4), (3, 3))),
    "freq": ItemRule(5, ((4, 5), (2, 3))),
    "buyback": ItemRule(7),
    "cancel": ItemRule(8, ((2, 8), (1.5, 5), (0.5, 3))),
    "treasury": ItemRule(5, ((2, 4), (5, 2)), none_points=5),
    "subsidiary": ItemRule(5),
}


def _default_items() -> dict[str, ItemRule]:
    return dict(DEFAULT_ITEMS)


@dataclass(frozen=True)
class ScoreSettings:
    top_n: int = 50
    grade_a: float = 80.0      # 초과면 A
    grade_b: float = 70.0
    grade_c: float = 50.0
    subsidiary_stake_min: float = 30.0
    items: dict[str, ItemRule] = field(default_factory=_default_items)


NORMAL_EPS_RULES = ("average", "lower")   # 정상 EPS: 5년 평균 | 5년 평균과 최근 해 EPS 중 낮은 값


@dataclass(frozen=True)
class Variant:
    """백테스트에서 '지금 규칙'과 나란히 돌려 볼 규칙 하나 ([backtest.variants])."""
    name: str
    criteria: tuple[tuple[str, float], ...] = ()   # [criteria] 바꾸기
    normal_eps: str = "average"                   # "lower"면 정상 EPS = 5년 평균과 최근 해 EPS 중 낮은 값
    sell_on_gate_fail: bool = False               # 산 뒤 관문 ①②가 탈락으로 바뀌면 팔기


@dataclass(frozen=True)
class BacktestSettings:
    """백테스트 (2026-11-24 백테스트 설계 3·5·7장). 기준값은 [criteria] 그대로이고, 여기는 투자 규칙과 비교 대상이에요."""
    start: date = date(2018, 4, 1)
    end: date = date(2026, 11, 20)
    second_start: date = date(2020, 11, 2)
    monthly: float = 1_300_000.0
    max_holdings: int = 5
    cost_rate: float = 0.0025
    min_trade: float = 10_000.0
    max_weight: float = 0.2                   # 살 때 한 종목이 전체 평가액에서 넘지 않을 비중
    min_trading_value: float = 100_000_000.0  # 20일 평균 거래대금이 이보다 적은 종목은 사지 않아요 (원)
    cma: tuple[tuple[str, date], ...] = (("214980", date(2018, 1, 1)), ("357870", date(2020, 7, 7)))
    benchmarks: tuple[tuple[str, str], ...] = (
        ("나스닥100 (TIGER 미국나스닥100)", "etf:133690"),
        ("S&P500 환헤지 (TIGER 미국S&P500선물(H))", "etf:143850"),
        ("코스피", "index:코스피"),
        ("고배당 ETF (PLUS 고배당주)", "etf:161510"))
    second_benchmarks: tuple[tuple[str, str], ...] = (
        ("S&P500 환노출 (TIGER 미국S&P500)", "etf:360750"),
        ("코스피 200 배당 포함 (25/50 NTR)", "index:코스피 200 25/50 NTR 지수"))
    variants: tuple[Variant, ...] = (
        Variant("지금 규칙"),
        Variant("배당성향 하한 없음", criteria=(("payout_min", 0.0),)),
        Variant("정상 EPS = 5년 평균과 최근 해 중 낮은 값", normal_eps="lower"),
        Variant("관문 ①② 탈락하면 팔기", sell_on_gate_fail=True))


@dataclass(frozen=True)
class Settings:
    criteria: Criteria
    report: ReportSettings
    industry: IndustrySettings
    calculator_path: Path
    dart_daily_budget: int
    data_dir: Path
    reports_dir: Path
    exports_dir: Path
    financial: FinancialSettings = FinancialSettings()
    score: ScoreSettings = ScoreSettings()
    backtest: BacktestSettings = BacktestSettings()


@dataclass(frozen=True)
class Keys:
    dart: str
    krx: str | None
    naver_id: str | None
    naver_secret: str | None
    fisis: str | None = None


def _bad(where: str, key: str, why: str) -> ConfigError:
    return ConfigError(f"settings.toml의 {where} {key} 값이 잘못됐어요: {why}")


def _number(where: str, key: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(where, key, f"숫자여야 해요 (지금: {value!r}). 따옴표나 % 없이 숫자만 써요.")
    if not math.isfinite(value):
        raise _bad(where, key, f"inf나 nan은 쓸 수 없어요 (지금: {value}). 보통 숫자로 써요.")
    return float(value)


def _checked(where: str, key: str, value) -> float:
    x = _number(where, key, value)
    if key in _RATE_KEYS:
        if not 0 < x < 1:
            raise _bad(where, key, f"0보다 크고 1보다 작아야 해요 (지금: {x}). 25%는 0.25로 써요.")
    elif x <= 0:
        raise _bad(where, key, f"0보다 커야 해요 (지금: {x}).")
    return x


def _section(raw: dict, name: str) -> dict:
    sec = raw.get(name, {})
    if not isinstance(sec, dict):
        raise ConfigError(f"settings.toml의 [{name}]은 표 형태여야 해요.")
    return sec


def _no_unknown(where: str, sec: dict, allowed: set[str]) -> None:
    for key in sec:
        if key not in allowed:
            raise _bad(where, key, f"알 수 없는 항목이에요. 쓸 수 있는 항목: {', '.join(sorted(allowed))}")


def _score_item(key: str, body) -> ItemRule:
    where = f"[score.{key}]"
    if not isinstance(body, dict):
        raise _bad("[score]", key, "{ points = 배점, steps = [[경계, 점수], …] } 모양이어야 해요.")
    allowed = {"points", "steps"} | ({"none_points"} if key == "treasury" else set())
    _no_unknown(where, body, allowed)
    base = DEFAULT_ITEMS[key]
    points = _number(where, "points", body["points"]) if "points" in body else base.points
    if points < 0:
        raise _bad(where, "points", f"0 이상이어야 해요 (지금: {points}).")

    def pts(name: str, v) -> float:
        x = _number(where, name, v)
        if not 0 <= x <= points:
            raise _bad(where, name, f"점수는 0 이상, 배점({points:g}) 이하여야 해요 (지금: {x:g}).")
        return x

    if "steps" in body:
        raw = body["steps"]
        if not isinstance(raw, list) or any(not isinstance(s, list) or len(s) != 2 for s in raw):
            raise _bad(where, "steps", "[경계, 점수] 쌍의 목록이어야 해요. 예: [[5, 15], [8, 11]]")
        steps = tuple((_number(where, "steps", b), pts("steps", p)) for b, p in raw)
    elif "points" in body:
        steps = tuple((b, min(p, points)) for b, p in base.steps)
    else:
        steps = base.steps
    for b, p in steps:
        if p > points:
            raise _bad(where, "steps", f"점수는 배점({points:g}) 이하여야 해요 (지금: {p:g}).")
    ascending = ITEM_OPS[key] in ("lt", "le")
    bounds = [b for b, _ in steps]
    if any((b2 <= b1) if ascending else (b2 >= b1) for b1, b2 in zip(bounds, bounds[1:])):
        way = "커지는" if ascending else "작아지는"
        raise _bad(where, "steps", f"경계는 위에서부터 {way} 순서여야 해요 (지금: {bounds}).")
    none_points = base.none_points
    if "none_points" in body:
        none_points = pts("none_points", body["none_points"])
    return ItemRule(points, steps, none_points)


def _score_settings(raw: dict) -> ScoreSettings:
    sec = _section(raw, "score")
    scalars = {"top_n", "grade_a", "grade_b", "grade_c", "subsidiary_stake_min"}
    _no_unknown("[score]", sec, scalars | set(ITEM_OPS))
    kw: dict = {}
    if "top_n" in sec:
        n = sec["top_n"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise _bad("[score]", "top_n", f"1 이상의 정수여야 해요 (지금: {n!r}).")
        kw["top_n"] = n
    for key in ("grade_a", "grade_b", "grade_c"):
        if key in sec:
            x = _number("[score]", key, sec[key])
            if x < 0:
                raise _bad("[score]", key, f"0 이상이어야 해요 (지금: {x}).")
            kw[key] = x
    if "subsidiary_stake_min" in sec:
        x = _number("[score]", "subsidiary_stake_min", sec["subsidiary_stake_min"])
        if not 0 < x <= 100:
            raise _bad("[score]", "subsidiary_stake_min", f"0보다 크고 100 이하여야 해요 (지금: {x}).")
        kw["subsidiary_stake_min"] = x
    items = _default_items()
    for key in ITEM_OPS:
        if key in sec:
            items[key] = _score_item(key, sec[key])
    s = ScoreSettings(items=items, **kw)
    if not s.grade_a >= s.grade_b >= s.grade_c:
        raise _bad("[score]", "grade_a", f"등급 경계는 grade_a ≥ grade_b ≥ grade_c여야 해요 "
                                         f"(지금: {s.grade_a:g}, {s.grade_b:g}, {s.grade_c:g}).")
    return s


_BT = "[backtest]"
_BT_KEYS = {"start", "end", "second_start", "monthly", "max_holdings", "cost_rate", "min_trade", "cma",
            "benchmarks", "second_benchmarks", "variants", "max_weight", "min_trading_value"}
_VARIANT_KEYS = {"normal_eps", "sell_on_gate_fail"}


def _bt_date(key: str, value) -> date:
    if not isinstance(value, date) or hasattr(value, "hour"):
        raise _bad(_BT, key, f"날짜여야 해요 (예: 2018-04-01, 지금: {value!r}).")
    return value


def _bt_targets(key: str, table) -> tuple[tuple[str, str], ...]:
    """비교 대상 표: 이름 = "etf:6자리 코드" 또는 "index:지수 이름"."""
    if not isinstance(table, dict):
        raise _bad(_BT, key, "[backtest.%s] 표여야 해요." % key)
    out = []
    for name, target in table.items():
        ok = isinstance(target, str) and (
            (target.startswith("etf:") and len(target) == 10 and target[4:].isalnum())
            or (target.startswith("index:") and len(target) > 6))
        if not ok:
            raise _bad(_BT, key, f'"{name}"의 값은 "etf:6자리 코드" 또는 "index:지수 이름"이어야 해요 (지금: {target!r}).')
        out.append((str(name), target))
    return tuple(out)


def _variant_value(where: str, key: str, value) -> float:
    """[criteria]와 같은 검사예요. 하한(…_min)은 0도 돼요: 그 하한을 없앤 변형이에요."""
    if _number(where, key, value) == 0 and key.endswith("_min"):
        return 0.0
    return _checked(where, key, value)


def _backtest_settings(raw: dict, criteria: Criteria) -> BacktestSettings:
    sec = _section(raw, "backtest")
    _no_unknown(_BT, sec, _BT_KEYS)
    kw: dict = {}
    for key in ("start", "end", "second_start"):
        if key in sec:
            kw[key] = _bt_date(key, sec[key])
    for key in ("monthly", "min_trade", "cost_rate", "max_weight", "min_trading_value"):
        if key in sec:
            kw[key] = _number(_BT, key, sec[key])
    if "max_weight" in kw and not 0 < kw["max_weight"] <= 1:
        raise _bad(_BT, "max_weight", f"0보다 크고 1 이하여야 해요 (지금: {kw['max_weight']}). 20%는 0.2로 써요.")
    if "min_trading_value" in kw and kw["min_trading_value"] < 0:
        raise _bad(_BT, "min_trading_value", "0 이상이어야 해요 (0이면 거래대금을 보지 않아요).")
    if "monthly" in kw and kw["monthly"] <= 0:
        raise _bad(_BT, "monthly", "0보다 커야 해요.")
    if "min_trade" in kw and kw["min_trade"] < 0:
        raise _bad(_BT, "min_trade", "0 이상이어야 해요.")
    if "cost_rate" in kw and not 0 <= kw["cost_rate"] < 0.1:
        raise _bad(_BT, "cost_rate", f"0 이상 0.1 미만이어야 해요 (지금: {kw['cost_rate']}).")
    if "max_holdings" in sec:
        n = sec["max_holdings"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise _bad(_BT, "max_holdings", f"1 이상의 정수여야 해요 (지금: {n!r}).")
        kw["max_holdings"] = n
    if "cma" in sec:
        rows = sec["cma"]
        if not isinstance(rows, list) or not rows or not all(
                isinstance(r, list) and len(r) == 2 and isinstance(r[0], str) for r in rows):
            raise _bad(_BT, "cma", '[["코드", 날짜], …] 모양이어야 해요.')
        cma = tuple((r[0], _bt_date("cma", r[1])) for r in rows)
        if [d for _, d in cma] != sorted(d for _, d in cma):
            raise _bad(_BT, "cma", "날짜 순서대로 적어야 해요.")
        kw["cma"] = cma
    for key in ("benchmarks", "second_benchmarks"):
        if key in sec:
            kw[key] = _bt_targets(key, sec[key])
    if "variants" in sec:
        table = sec["variants"]
        if not isinstance(table, dict) or not table:
            raise _bad(_BT, "variants", "[backtest.variants] 표여야 해요.")
        crit_fields = {f.name for f in fields(Criteria)}
        variants = []
        for name, body in table.items():
            if not isinstance(body, dict):
                raise _bad(_BT, "variants", f'"{name}"은(는) {{ 키 = 값 }} 모양이어야 해요.')
            where = f"[backtest.variants] {name}"
            _no_unknown(where, body, crit_fields | _VARIANT_KEYS)
            values = tuple((k, _variant_value(where, k, v)) for k, v in body.items() if k in crit_fields)
            merged = replace(criteria, **dict(values))
            if merged.payout_min >= merged.payout_max:
                raise _bad(where, "payout_min", "배당성향 하한은 상한(payout_max)보다 작아야 해요.")
            normal = body.get("normal_eps", "average")
            if normal not in NORMAL_EPS_RULES:
                raise _bad(where, "normal_eps", f'"average"(5년 평균) 또는 "lower"(평균과 최근 해 중 낮은 값)여야 해요 '
                                               f"(지금: {normal!r}).")
            sell = body.get("sell_on_gate_fail", False)
            if not isinstance(sell, bool):
                raise _bad(where, "sell_on_gate_fail", "true 또는 false여야 해요.")
            variants.append(Variant(str(name), values, normal, sell))
        kw["variants"] = tuple(variants)
    bt = BacktestSettings(**kw)
    if not bt.start < bt.end:
        raise _bad(_BT, "end", "끝 날짜(end)는 시작 날짜(start)보다 뒤여야 해요.")
    if not bt.start <= bt.second_start < bt.end:
        raise _bad(_BT, "second_start", "두 번째 실행 시작일은 start와 end 사이여야 해요.")
    return bt


def load_settings(path: Path) -> Settings:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"설정 파일을 찾을 수 없어요: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"settings.toml을 읽을 수 없어요: {e}") from None
    base = path.parent
    for name in raw:
        if name not in _SECTIONS:
            allowed = ", ".join(f"[{x}]" for x in _SECTIONS)
            raise ConfigError(f"settings.toml의 [{name}]은(는) 알 수 없는 부분이에요. 쓸 수 있는 부분: {allowed}")

    crit_fields = {f.name for f in fields(Criteria)}
    crit_raw = _section(raw, "criteria")
    _no_unknown("[criteria]", crit_raw, crit_fields)
    criteria = Criteria(**{k: _checked("[criteria]", k, v) for k, v in crit_raw.items()})
    if criteria.payout_min >= criteria.payout_max:
        raise _bad("[criteria]", "payout_min", "배당성향 하한은 상한(payout_max)보다 작아야 해요.")

    rep_raw = _section(raw, "report")
    _no_unknown("[report]", rep_raw, {"watch_range", "near_range"})
    report = ReportSettings(**{k: _checked("[report]", k, v) for k, v in rep_raw.items()})
    if report.near_range > report.watch_range:
        raise _bad("[report]", "near_range", "근접 범위는 관심 목록 범위(watch_range)보다 크면 안 돼요.")

    ind_raw = _section(raw, "industry")
    _no_unknown("[industry]", ind_raw, {"use_in_verdict", "roe_top_percent", "min_group_size", "overrides"})
    kwargs: dict = {}
    if "use_in_verdict" in ind_raw:
        if not isinstance(ind_raw["use_in_verdict"], bool):
            raise _bad("[industry]", "use_in_verdict", "true 또는 false여야 해요.")
        kwargs["use_in_verdict"] = ind_raw["use_in_verdict"]
    if "roe_top_percent" in ind_raw:
        x = _number("[industry]", "roe_top_percent", ind_raw["roe_top_percent"])
        if not 0 < x <= 100:
            raise _bad("[industry]", "roe_top_percent", f"0보다 크고 100 이하여야 해요 (지금: {x}).")
        kwargs["roe_top_percent"] = x
    if "min_group_size" in ind_raw:
        n = ind_raw["min_group_size"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise _bad("[industry]", "min_group_size", f"1 이상의 정수여야 해요 (지금: {n!r}).")
        kwargs["min_group_size"] = n
    overrides: dict[str, dict[str, float]] = {}
    ov_raw = ind_raw.get("overrides", {})
    if not isinstance(ov_raw, dict):
        raise ConfigError("settings.toml의 [industry.overrides]는 표 형태여야 해요.")
    for code, body in ov_raw.items():
        where = f"[industry.overrides] \"{code}\""
        if not isinstance(body, dict):
            raise _bad("[industry.overrides]", code, "{ 항목 = 값 } 모양이어야 해요.")
        _no_unknown(where, body, crit_fields)
        overrides[str(code)] = {k: _checked(where, k, v) for k, v in body.items()}
        merged = replace(criteria, **overrides[str(code)])
        if merged.payout_min >= merged.payout_max:
            raise _bad(where, "payout_min", "배당성향 하한은 상한(payout_max)보다 작아야 해요.")
    industry = IndustrySettings(overrides=overrides, **kwargs)

    paths = _section(raw, "paths")
    _no_unknown("[paths]", paths, {"calculator", "data_dir", "reports_dir", "exports_dir"})

    def p(key: str, default: str) -> Path:
        v = paths.get(key, default)
        if not isinstance(v, str) or not v:
            raise _bad("[paths]", key, "경로 글자여야 해요.")
        q = Path(v).expanduser()
        return q if q.is_absolute() else base / q

    dart = _section(raw, "dart")
    _no_unknown("[dart]", dart, {"daily_budget"})
    budget = dart.get("daily_budget", 19000)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise _bad("[dart]", "daily_budget", f"0보다 큰 정수여야 해요 (지금: {budget!r}).")

    fin_raw = _section(raw, "financial")
    fin_keys = {"include", "bank_cet1_min", "insurer_kics_min", "securities_ncr_min"}
    _no_unknown("[financial]", fin_raw, fin_keys)
    fin_kwargs: dict = {}
    if "include" in fin_raw:
        if not isinstance(fin_raw["include"], bool):
            raise _bad("[financial]", "include", "true 또는 false여야 해요.")
        fin_kwargs["include"] = fin_raw["include"]
    for key in ("bank_cet1_min", "insurer_kics_min", "securities_ncr_min"):
        if key in fin_raw:
            fin_kwargs[key] = _checked("[financial]", key, fin_raw[key])
    financial = FinancialSettings(**fin_kwargs)
    score = _score_settings(raw)
    backtest = _backtest_settings(raw, criteria)

    return Settings(
        criteria=criteria, report=report, industry=industry, financial=financial, score=score, backtest=backtest,
        calculator_path=p("calculator", "배당주_분석_계산기.xlsx"),
        dart_daily_budget=budget,
        data_dir=p("data_dir", "data"),
        reports_dir=p("reports_dir", "reports"),
        exports_dir=p("exports_dir", "exports"),
    )


def load_keys(path: Path, *, require_krx: bool = True) -> Keys:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"keys.toml이 없어요. keys.example.toml을 keys.toml로 복사해서 키를 넣어 주세요: {path}"
        ) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"keys.toml을 읽을 수 없어요: {e}") from None

    def get(section: str, key: str) -> str | None:
        v = raw.get(section, {}).get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise ConfigError(f"keys.toml의 [{section}] {key} 값은 글자여야 해요.")
        return v.strip() or None

    dart = get("dart", "api_key")
    if not dart:
        raise ConfigError("keys.toml에 DART 인증키가 없어요. [dart] api_key에 OpenDART 인증키를 넣어 주세요.")
    krx = get("krx", "auth_key")
    if not krx and require_krx:
        raise ConfigError("keys.toml에 KRX 인증키가 없어요. [krx] auth_key에 KRX OPEN API 인증키를 넣어 주세요.")
    return Keys(dart=dart, krx=krx, naver_id=get("naver", "client_id"), naver_secret=get("naver", "client_secret"),
                fisis=get("fisis", "auth_key"))


def settings_fingerprint(s: Settings) -> dict:
    """리포트에 남겨 둘 기준값 묶음. JSON으로 저장할 수 있어요."""
    return {
        "criteria": asdict(s.criteria),
        "report": asdict(s.report),
        "industry": asdict(s.industry),
        "financial": asdict(s.financial),
        "score": json.loads(json.dumps(asdict(s.score))),   # 튜플을 리스트로: 다음 주 비교에서 같게 보여요
    }
