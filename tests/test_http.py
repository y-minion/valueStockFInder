import httpx
import pytest

from vsf.data.http import NetworkError, get_with_retry


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_retries_5xx_then_succeeds():
    codes = iter([503, 503, 200])
    sleeps = []
    c = _client(lambda r: httpx.Response(next(codes)))
    assert get_with_retry(c, "http://x/a", sleep=sleeps.append).status_code == 200
    assert sleeps == [1, 2]


def test_4xx_returned_without_retry():
    calls = []
    def h(r):
        calls.append(1); return httpx.Response(404)
    sleeps = []
    assert get_with_retry(_client(h), "http://x/a", sleep=sleeps.append).status_code == 404
    assert len(calls) == 1 and sleeps == []


def test_connect_error_raises_network_error_without_query():
    def h(r):
        raise httpx.ConnectError("boom")
    with pytest.raises(NetworkError) as e:
        get_with_retry(_client(h), "http://x/a", params={"crtfc_key": "SECRET"}, sleep=lambda s: None)
    assert "http://x/a" in str(e.value) and "SECRET" not in str(e.value)


def test_persistent_5xx_raises():
    c = _client(lambda r: httpx.Response(500))
    with pytest.raises(NetworkError):
        get_with_retry(c, "http://x/a", sleep=lambda s: None)
