import json
from pathlib import Path

import pytest
from helpers import write_settings

from vsf.config import ConfigError, FinancialSettings, load_keys, load_settings, settings_fingerprint
from vsf.model import Criteria

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_settings_are_excel_defaults():
    s = load_settings(ROOT / "settings.toml")
    assert s.criteria == Criteria()
    assert (s.report.watch_range, s.report.near_range) == (0.20, 0.10)
    assert s.industry.use_in_verdict is False and s.industry.min_group_size == 5
    assert s.calculator_path == Path("/Users/youngmin/가치투자/배당주_분석_계산기.xlsx")
    assert s.dart_daily_budget == 19000
    assert s.data_dir == ROOT / "data"


def test_bad_value_message(tmp_path):
    p = write_settings(tmp_path, criteria={"safety_margin": '"25%"'})
    with pytest.raises(ConfigError) as e:
        load_settings(p)
    assert "safety_margin" in str(e.value) and "숫자" in str(e.value)


def test_rate_out_of_range(tmp_path):
    p = write_settings(tmp_path, criteria={"safety_margin": "1.5"})
    with pytest.raises(ConfigError, match="0보다 크고 1보다 작아야"):
        load_settings(p)


def test_unknown_key(tmp_path):
    p = write_settings(tmp_path, criteria={"roe_minimum": "8"})
    with pytest.raises(ConfigError, match="roe_minimum"):
        load_settings(p)


def test_payout_order(tmp_path):
    p = write_settings(tmp_path, criteria={"payout_min": "0.7"})
    with pytest.raises(ConfigError, match="payout_min"):
        load_settings(p)


def test_industry_override_parsing(tmp_path):
    p = write_settings(tmp_path, overrides='"35" = { roe_min = 6 }')
    assert load_settings(p).industry.overrides == {"35": {"roe_min": 6.0}}
    with pytest.raises(ConfigError, match="roe_minn"):
        load_settings(write_settings(tmp_path, overrides='"35" = { roe_minn = 6 }'))


def test_missing_dart_key(tmp_path):
    (tmp_path / "keys.toml").write_text('[krx]\nauth_key = "x"\n')
    with pytest.raises(ConfigError, match="DART"):
        load_keys(tmp_path / "keys.toml")


def test_krx_key_optional_for_dart_only_use(tmp_path):
    (tmp_path / "keys.toml").write_text('[dart]\napi_key = "d"\n[krx]\nauth_key = "  "\n')
    keys = load_keys(tmp_path / "keys.toml", require_krx=False)
    assert keys.krx is None and keys.dart == "d"


def test_blank_krx_key_still_required_by_default(tmp_path):
    (tmp_path / "keys.toml").write_text('[dart]\napi_key = "d"\n[krx]\nauth_key = ""\n')
    with pytest.raises(ConfigError, match="KRX 인증키가 없어요"):
        load_keys(tmp_path / "keys.toml")


def test_fingerprint_is_json_roundtrip():
    s = load_settings(ROOT / "settings.toml")
    assert json.loads(json.dumps(settings_fingerprint(s)))["criteria"]["required_return"] == 0.10


@pytest.mark.parametrize("key,text", [
    ("roe_min", "inf"), ("debt_ratio_max", "-inf"), ("safety_margin", "nan"), ("required_return", "+inf"),
    ("near_range", "nan"), ("watch_range", "inf"), ("roe_top_percent", "inf"), ("roe_top_percent", "nan"),
])
def test_non_finite_numbers_are_rejected(tmp_path, key, text):
    p = write_settings(tmp_path, criteria={key: text})      # 그 키가 있는 줄을 바꿔요 ([report]·[industry]도)
    with pytest.raises(ConfigError, match=key) as e:
        load_settings(p)
    assert "inf나 nan은 쓸 수 없어요" in str(e.value)


def test_non_finite_override_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="roe_min") as e:
        load_settings(write_settings(tmp_path, overrides='"35" = { roe_min = inf }'))
    assert "inf나 nan은 쓸 수 없어요" in str(e.value) and '"35"' in str(e.value)


@pytest.mark.parametrize("extra", ["\n[criterias]\nroe_min = 8\n", "\n[reports]\n"])
def test_unknown_top_level_section_is_rejected(tmp_path, extra):
    p = write_settings(tmp_path)
    p.write_text(p.read_text(encoding="utf-8") + extra, encoding="utf-8")
    name = extra.split("[")[1].split("]")[0]
    with pytest.raises(ConfigError, match=rf"\[{name}\]") as e:
        load_settings(p)
    assert "알 수 없는" in str(e.value)


def test_unknown_top_level_key_is_rejected(tmp_path):
    p = write_settings(tmp_path)
    p.write_text("safety_margin = 0.3\n" + p.read_text(encoding="utf-8"), encoding="utf-8")   # 표 밖에 쓴 값
    with pytest.raises(ConfigError, match="safety_margin"):
        load_settings(p)


def test_financial_defaults_and_fingerprint(tmp_path):
    s = load_settings(write_settings(tmp_path))
    assert s.financial == FinancialSettings(True, 9.0, 130.0, 100.0)
    assert settings_fingerprint(s)["financial"] == {
        "include": True, "bank_cet1_min": 9.0, "insurer_kics_min": 130.0, "securities_ncr_min": 100.0}


def test_shipped_settings_have_financial_defaults():
    assert load_settings(ROOT / "settings.toml").financial == FinancialSettings()


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


def test_fisis_key_is_optional(tmp_path):
    (tmp_path / "keys.toml").write_text('[dart]\napi_key = "d"\n[krx]\nauth_key = "k"\n')
    assert load_keys(tmp_path / "keys.toml").fisis is None
    (tmp_path / "keys.toml").write_text('[dart]\napi_key = "d"\n[krx]\nauth_key = "k"\n[fisis]\nauth_key = "  "\n')
    assert load_keys(tmp_path / "keys.toml").fisis is None
    (tmp_path / "keys.toml").write_text('[dart]\napi_key = "d"\n[krx]\nauth_key = "k"\n[fisis]\nauth_key = "f"\n')
    assert load_keys(tmp_path / "keys.toml").fisis == "f"


# ---- [score] ----
from vsf.config import ItemRule, ScoreSettings  # noqa: E402


def test_shipped_score_defaults():
    s = load_settings(ROOT / "settings.toml").score
    assert s == ScoreSettings()
    assert sum(r.points for r in s.items.values()) == 100
    assert s.items["per"].steps == ((5, 15), (8, 11), (10, 7), (15, 3))
    assert s.items["treasury"].none_points == 5
    assert (s.top_n, s.grade_a, s.grade_b, s.grade_c, s.subsidiary_stake_min) == (50, 80, 70, 50, 30.0)


def test_score_steps_override(tmp_path):
    p = write_settings(tmp_path, score={"per": "{ points = 20, steps = [[5, 20], [8, 12]] }"})
    s = load_settings(p).score
    assert s.items["per"] == ItemRule(20, ((5, 20), (8, 12)))
    assert s.items["pbr"] == ScoreSettings().items["pbr"]


def test_score_scalar_override(tmp_path):
    s = load_settings(write_settings(tmp_path, score={"top_n": "30"})).score
    assert s.top_n == 30 and s.items == ScoreSettings().items


@pytest.mark.parametrize("body,word", [
    ('{ points = 5, steps = [[5, 9]] }', "배점"),                 # 구간 점수 > 배점
    ('{ points = 15, steps = [[8, 11], [5, 15]] }', "순서"),      # 미만인데 경계가 내려가요
    ('{ points = -1 }', "0 이상"),
    ('{ points = 15, steps = [[5]] }', "[경계, 점수]"),
    ('{ points = 15, color = 3 }', "알 수 없는"),
])
def test_bad_score_item(tmp_path, body, word):
    with pytest.raises(ConfigError) as e:
        load_settings(write_settings(tmp_path, score={"per": body}))
    assert word in str(e.value)


def test_descending_steps_for_at_least_items(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_settings(write_settings(tmp_path, score={"roe": "{ points = 10, steps = [[8, 5], [15, 10]] }"}))
    assert "순서" in str(e.value)


def test_unknown_score_item(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_settings(write_settings(tmp_path, score={"growth": "{ points = 10 }"}))
    assert "알 수 없는" in str(e.value)


@pytest.mark.parametrize("key,value", [("top_n", "0"), ("grade_a", "60"), ("subsidiary_stake_min", "150")])
def test_bad_score_scalars(tmp_path, key, value):
    with pytest.raises(ConfigError):
        load_settings(write_settings(tmp_path, score={key: value}))


def test_fingerprint_has_score():
    fp = settings_fingerprint(load_settings(ROOT / "settings.toml"))
    assert fp["score"]["items"]["per"]["points"] == 15 and fp["score"]["top_n"] == 50
    import json as _json
    _json.dumps(fp)


def test_fingerprint_survives_json_round_trip():
    fp = settings_fingerprint(load_settings(ROOT / "settings.toml"))
    import json as _json
    assert _json.loads(_json.dumps(fp)) == fp          # 다음 주에 '배점이 바뀌었어요'가 잘못 뜨지 않게
