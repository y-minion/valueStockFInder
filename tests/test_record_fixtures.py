"""녹화 도구가 HTTP 오류에서 API 키를 드러내지 않는지 확인해요 (네트워크·keys.toml 안 씀)."""
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
