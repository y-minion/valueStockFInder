"""금감원 FISIS 자본비율 클라이언트 테스트. 녹화한 실제 응답을 MockTransport로 돌려줘요."""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fakes import mem_store

from vsf.data.fisis import FisisAuthError, FisisClient, FisisError

REC = Path(__file__).parent / "fixtures" / "fisis" / "recorded"
KEY = "FISISSECRET" + "0" * 21
TODAY = date(2026, 11, 16)
DART = json.loads((REC / "dart_names.json").read_text(encoding="utf-8"))


def _load(name):
    return json.loads((REC / f"{name}.json").read_text(encoding="utf-8"))


STATS = {}      # (finance_cd, listNo) -> body
for _p in REC.glob("stat_*.json"):
    _body = _load(_p.stem)
    STATS[(_body["result"]["list"][0]["finance_cd"], _p.stem.rsplit("_", 1)[1])] = _body


class FakeFisis:
    def __init__(self, error=None, status=200):
        self.requests: list[httpx.Request] = []
        self.error = error
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        q = request.url.params
        assert q["auth"] == KEY
        if self.status != 200:
            return httpx.Response(self.status, text="x")
        if self.error:
            return httpx.Response(200, json={"result": {"err_cd": self.error, "err_msg": "오류"}})
        if request.url.path.endswith("companySearch.json"):
            return httpx.Response(200, json=_load(f"company_{q['partDiv']}_{q['lang']}"))
        body = STATS.get((q["financeCd"], q["listNo"]),
                         {"result": {"err_cd": "000", "err_msg": "정상", "list": []}})
        return httpx.Response(200, json=body)

    def count(self, name):
        return sum(r.url.path.endswith(name) for r in self.requests)


def client(fake=None, tmp_path=None):
    fake = fake or FakeFisis()
    c = FisisClient(KEY, mem_store(), http=httpx.Client(transport=httpx.MockTransport(fake)),
                    today=lambda: TODAY, min_interval=0, sleep=lambda s: None)
    return c, fake


def last_numeric(stat, accounts):
    rows = _load(stat)["result"]["list"]
    for acc in accounts:
        good = [r for r in rows if r["account_cd"] == acc and _num(r["a"])]
        if good:
            r = max(good, key=lambda r: r["base_month"])
            return float(r["a"]), f"{r['base_month'][:4]}-{r['base_month'][4:]}"
    raise AssertionError("no numeric row")


def _num(a):
    try:
        return float(a) > 0
    except ValueError:
        return False


def names(code):
    d = DART[code]
    return (d["corp_name"], d["corp_name_eng"], d["stock_name"])


def test_companies_skip_closed_and_cache_monthly():
    c, fake = client()
    rows = c.companies("L", "kr")
    assert rows and all("[폐]" not in n for _, n in rows)
    assert ("0012028", "주식회사 케이비금융지주") in rows
    n = len(fake.requests)
    assert c.companies("L", "kr") == rows and len(fake.requests) == n
    en = c.companies("L", "en")
    assert all("[closed]" not in n for _, n in en)


@pytest.mark.parametrize("kind, code, stat, accounts, src", [
    ("금융지주", "105560", "stat_kb_SL008", ("C2",), "SL008"),
    ("금융지주", "055550", "stat_shinhan_SL008", ("C2",), "SL008"),
    ("은행", "024110", "stat_ibk_SA014", ("A2",), "SA014"),
    ("보험", "032830", "stat_samsunglife_SH021", ("D", "A"), "SH021"),
    ("보험", "000810", "stat_samsungfire_SI021", ("D", "A"), "SI021"),
    ("증권", "016360", "stat_samsungsec_SF308", ("E",), "SF308"),
])
def test_capital_ratio_for_each_kind(kind, code, stat, accounts, src):
    c, fake = client()
    got = c.capital_ratio(kind, names(code))
    value, month = last_numeric(stat, accounts)
    assert got is not None and got.value == value and got.base_month == month
    assert got.source.startswith("금감원 금융통계정보시스템") and KEY not in got.source
    stat_req = [r for r in fake.requests if r.url.path.endswith("statisticsInfoSearch.json")][-1]
    p = stat_req.url.params
    assert p["term"] == "Q" and p["endBaseMm"] == "202611" and p["startBaseMm"] == "202511"
    assert "accountCd" not in p
    n = len(fake.requests)
    assert c.capital_ratio(kind, names(code)) == got and len(fake.requests) == n     # 캐시


def test_samsung_life_uses_account_a_because_d_is_zero():
    c, _ = client()
    got = c.capital_ratio("보험", names("032830"))
    assert got.value == 208.17 and "지급여력비율" in got.source


def test_unmatched_or_card_kind_gives_none():
    c, fake = client()
    assert c.capital_ratio("카드·캐피탈", ("삼성카드", "", "")) is None
    assert c.capital_ratio("은행", ("없는은행(주)", "NO SUCH BANK", "없음")) is None
    assert c.capital_ratio("은행", ("", "", "")) is None
    assert fake.count("statisticsInfoSearch.json") == 0


@pytest.mark.parametrize("code", ["010", "011", "012", "013"])
def test_auth_error_codes_raise_auth_error_without_key_in_message(code):
    c, _ = client(FakeFisis(error=code))
    with pytest.raises(FisisAuthError) as e:
        c.companies("A", "kr")
    assert code in str(e.value) and "인증키가 맞지 않아요" in str(e.value) and KEY not in str(e.value)


def test_other_errors_raise_fisis_error():
    for fake in (FakeFisis(error="100"), FakeFisis(status=403)):
        c, _ = client(fake)
        with pytest.raises(FisisError) as e:
            c.companies("A", "kr")
        assert not isinstance(e.value, FisisAuthError)
        assert KEY not in str(e.value)


def test_unparsable_json_raises_fisis_error():
    def handler(request):
        return httpx.Response(200, text="<html>")
    c = FisisClient(KEY, mem_store(), http=httpx.Client(transport=httpx.MockTransport(handler)),
                    today=lambda: TODAY, min_interval=0, sleep=lambda s: None)
    with pytest.raises(FisisError):
        c.companies("A", "kr")


def test_calls_are_counted():
    c, fake = client()
    c.companies("L", "kr")
    assert c._store.count_calls("fisis", TODAY) == 1
