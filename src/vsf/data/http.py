"""Retrying HTTP GET helper."""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx


class NetworkError(Exception):
    """네트워크 또는 서버 문제로 요청이 끝내 실패했어요."""


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    attempts: int = 3,
    backoff: Sequence[float] = (1, 2, 4),
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with retries on connection errors and 5xx. 4xx is returned as is.

    The error message uses the URL without query string so API keys passed as
    params never leak.
    """
    for i in range(attempts):
        try:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code < 500:
                return resp
        except httpx.TransportError:
            pass
        if i < attempts - 1:
            sleep(backoff[min(i, len(backoff) - 1)])
    bare = url.split("?", 1)[0]
    raise NetworkError(f"인터넷 연결이나 서버 문제로 {bare} 요청이 실패했어요")
