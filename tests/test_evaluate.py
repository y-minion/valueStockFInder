from helpers import collected_with_kia, settings_with
from vsf.evaluate import evaluate, evaluate_one


def test_evaluate_applies_override_and_extra_gate():
    s = settings_with(overrides={"30": {"roe_min": 20.0}}, use_in_verdict=True)      # 기아 induty "30121", 종목 1개
    r = evaluate(collected_with_kia(), s).results["000270"]
    assert r.criteria.roe_min == 20.0 and r.cells["D78"] == "탈락"
    assert r.industry.group_code == "ALL" and r.extra_gate1 == "탈락"     # 1개뿐 → 전체 시장, 순위 100% > 50%


def test_evaluate_defaults_buy_and_fingerprint():
    run = evaluate(collected_with_kia(), settings_with())
    r = run.results["000270"]
    assert r.state == "buy" and r.near and r.extra_gate1 is None
    assert round(r.summary.buy_line, 1) == 69713.6
    assert run.settings_fp["criteria"]["safety_margin"] == 0.25


def test_evaluate_one_without_industry():
    company, assembled = collected_with_kia().records["000270"]
    assert evaluate_one(company, assembled, settings_with(), None).extra_gate1 is None
    r = evaluate_one(company, assembled, settings_with(use_in_verdict=True), None)
    assert r.extra_gate1 == "입력 필요"
