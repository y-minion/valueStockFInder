"""네이버 뉴스 검색 (NAVER API HUB, 네이버 클라우드). 키는 선택이고, 오류 메시지에는 키를 넣지 않아요.

네이버 개발자센터는 2026-07-31부터 검색 API 새 신청을 받지 않아요. 새 키는 NAVER API HUB에서 나오고,
옛 주소(openapi.naver.com)와 옛 헤더(X-Naver-Client-Id)로는 인증이 안 돼요 (401).
"""
from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime

import httpx

from vsf.data.http import get_with_retry

URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
_TAG = re.compile(r"<[^>]*>")


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


def _date(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


class NaverAuthError(ValueError):
    """네이버가 키를 받아 주지 않아요 (HTTP 401·403). 메시지에는 키가 들어가지 않아요."""


class NaverNews:
    def __init__(self, client_id: str, client_secret: str, http: httpx.Client | None = None) -> None:
        self._headers = {"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": client_secret}
        self._http = http or httpx.Client(timeout=30)

    def search(self, query: str, n: int = 5) -> list[dict]:
        resp = get_with_retry(self._http, URL, headers=self._headers,
                              params={"query": query, "display": n, "sort": "date"})
        if resp.status_code in (401, 403):
            raise NaverAuthError(f"네이버 검색 키가 맞지 않아요 (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"네이버 뉴스 검색 오류 {resp.status_code}")
        items = resp.json().get("items", [])
        return [{"title": _clean(i.get("title", "")),
                 "url": i.get("originallink") or i.get("link") or "",
                 "date": _date(i.get("pubDate", ""))} for i in items[:n]]
