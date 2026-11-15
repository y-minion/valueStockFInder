"""녹화 도구가 HTTP 오류에서 API 키를 드러내지 않는지 확인해요 (네트워크·keys.toml 안 씀)."""
import json

import httpx
import pytest

from tools.record_fixtures import RecorderError, fetch

KEY = "SECRETKEY" + "0" * 31


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(500),
    lambda req: (_ for _ in ()).throw(httpx.ConnectError("boom", request=req)),
])
def test_fetch_error_never_contains_key(handler, capsys):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RecorderError) as e:
        fetch(http, "company.json", KEY, corp_code="1")
    exc = e.value
    assert exc.__cause__ is None and exc.__context__ is None
    assert "company.json" in str(exc)
    out = capsys.readouterr()
    assert KEY not in str(exc) and KEY not in repr(exc) and KEY not in out.out + out.err
    assert "500" in str(exc) or "ConnectError" in str(exc)


def test_fetch_krx_error_never_contains_key():
    from tools.record_fixtures import fetch_krx
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(403)))
    with pytest.raises(RecorderError) as e:
        fetch_krx(http, "stk_bydd_trd", KEY, "20251230")
    assert KEY not in str(e.value) and "stk_bydd_trd" in str(e.value) and "403" in str(e.value)
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_first_rows_json_keeps_raw_first_rows_without_key():
    from tools.record_fixtures import first_rows_json
    bodies = {
        "stk_bydd_trd_20251230": {"OutBlock_1": [{"ISU_CD": "999999", "TDD_CLSPRC": "1", "ECHO": KEY},
                                                 {"ISU_CD": "000270"}]},
        "ksq_bydd_trd_20251230": {"OutBlock_1": []},
        "stk_isu_base_info_20261113": {"respMsg": "x"},
    }
    text = first_rows_json(bodies, KEY)
    assert KEY not in text
    assert json.loads(text) == {
        "stk_bydd_trd_20251230": {"ISU_CD": "999999", "TDD_CLSPRC": "1", "ECHO": "REMOVED"},   # 거르지 않은 첫 줄
        "ksq_bydd_trd_20251230": None, "stk_isu_base_info_20261113": None}


def test_record_krx_saves_raw_first_rows(tmp_path):
    from tools.record_fixtures import RAW_FIRST_ROWS, record_krx

    def handler(req):
        service, day = req.url.path.rsplit("/", 1)[-1], req.url.params["basDd"]
        assert req.headers["AUTH_KEY"] == KEY
        first = {"ISU_SRT_CD" if "base" in service else "ISU_CD": f"{service[:3]}{day}", "ODD_FIELD": "?"}
        return httpx.Response(200, json={"OutBlock_1": [first, {"ISU_CD": "000270", "ISU_SRT_CD": "000270"}]})

    assert record_krx(KEY, tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler))) == 0
    raw = json.loads((tmp_path / RAW_FIRST_ROWS).read_text(encoding="utf-8"))
    assert set(raw) == {"stk_isu_base_info_20261113", "ksq_isu_base_info_20261113", "stk_bydd_trd_20251230",
                        "ksq_bydd_trd_20251230", "stk_bydd_trd_20261113", "ksq_bydd_trd_20261113"}
    assert raw["ksq_bydd_trd_20251230"] == {"ISU_CD": "ksq20251230", "ODD_FIELD": "?"}    # 고른 종목이 아니어도
    assert RAW_FIRST_ROWS == "_raw_first_rows.json"


def _keys_root(tmp_path, monkeypatch):
    from tools import record_fixtures
    (tmp_path / "keys.toml").write_text(f'[dart]\napi_key = "{"d" * 40}"\n[krx]\nauth_key = ""\n',
                                        encoding="utf-8")
    monkeypatch.setattr(record_fixtures, "ROOT", tmp_path)
    return record_fixtures


def test_main_dart_runs_without_krx_key(tmp_path, monkeypatch):
    rf = _keys_root(tmp_path, monkeypatch)
    got = []
    monkeypatch.setattr(rf, "record_dart", lambda key, folder: got.append(key) or 0)
    assert rf.main(["dart"]) == 0
    assert got == ["d" * 40]


def test_main_krx_still_needs_krx_key(tmp_path, monkeypatch, capsys):
    rf = _keys_root(tmp_path, monkeypatch)
    monkeypatch.setattr(rf, "record_krx", lambda key, folder: 0)
    assert rf.main(["krx"]) == 2
    assert "KRX 인증키가 없어요" in capsys.readouterr().err
