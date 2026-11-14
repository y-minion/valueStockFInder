import json
from pathlib import Path

import pytest
from helpers import write_settings

from vsf.config import ConfigError, load_keys, load_settings, settings_fingerprint
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


def test_fingerprint_is_json_roundtrip():
    s = load_settings(ROOT / "settings.toml")
    assert json.loads(json.dumps(settings_fingerprint(s)))["criteria"]["required_return"] == 0.10
