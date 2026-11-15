"""settings.toml / keys.toml 읽기와 값 검사."""
import math
import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
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
}

_SECTIONS = ("criteria", "report", "industry", "paths", "dart")

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
class Settings:
    criteria: Criteria
    report: ReportSettings
    industry: IndustrySettings
    calculator_path: Path
    dart_daily_budget: int
    data_dir: Path
    reports_dir: Path
    exports_dir: Path


@dataclass(frozen=True)
class Keys:
    dart: str
    krx: str | None
    naver_id: str | None
    naver_secret: str | None


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

    return Settings(
        criteria=criteria, report=report, industry=industry,
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
    return Keys(dart=dart, krx=krx, naver_id=get("naver", "client_id"), naver_secret=get("naver", "client_secret"))


def settings_fingerprint(s: Settings) -> dict:
    """리포트에 남겨 둘 기준값 묶음. JSON으로 저장할 수 있어요."""
    return {
        "criteria": asdict(s.criteria),
        "report": asdict(s.report),
        "industry": asdict(s.industry),
    }
