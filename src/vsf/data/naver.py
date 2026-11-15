"""네이버 뉴스 검색 (NAVER API HUB, 네이버 클라우드). 키는 선택이고, 오류 메시지에는 키를 넣지 않아요.

네이버 개발자센터는 2026-07-31부터 검색 API 새 신청을 받지 않아요. 새 키는 NAVER API HUB에서 나오고,
옛 주소(openapi.naver.com)와 옛 헤더(X-Naver-Client-Id)로는 인증이 안 돼요 (401).
"""
from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from vsf.data.http import get_with_retry

URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
_FETCH = 100         # 최대치. 스포츠·연예를 빼고도 여러 날의 기사가 남도록 넉넉히 받아요
_TAG = re.compile(r"<[^>]*>")
_NOT_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


def _sports_or_entertainment(link: str) -> bool:
    """네이버 스포츠·연예 면(m.sports.naver.com 등)이나 스포츠·연예 매체 기사예요."""
    host = urlparse(link).netloc
    return "sports" in host or "entertain" in host


def _spread_by_day(news: list[dict], n: int) -> list[dict]:
    """관련도순을 지키면서 날짜별로 돌아가며 하나씩 골라요.

    같은 사건 기사는 같은 날 몰려서, 그냥 앞에서 n개를 자르면 한 사건만 n번 보여요.
    """
    picked: list[dict] = []
    rest = news
    while rest and len(picked) < n:
        days: set[str] = set()
        later: list[dict] = []
        for item in rest:
            if len(picked) < n and item["date"] not in days:
                days.add(item["date"])
                picked.append(item)
            else:
                later.append(item)
        rest = later
    return picked


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
        """관련 높은 기사 n개를 최신순으로 줘요.

        관련도순으로 받아 스포츠·연예 기사와 글자가 같은 제목을 빼고, 날짜별로 돌아가며 골라요.
        최신순으로 받으면 '기아'·'KT'·'한화'처럼 야구단과 이름이 같은 회사는 경기 기사가 대부분이에요.
        """
        resp = get_with_retry(self._http, URL, headers=self._headers,
                              params={"query": query, "display": _FETCH, "sort": "sim"})
        if resp.status_code in (401, 403):
            raise NaverAuthError(f"네이버 검색 키가 맞지 않아요 (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"네이버 뉴스 검색 오류 {resp.status_code}")
        news: list[dict] = []
        seen: set[str] = set()
        for i in resp.json().get("items", []):
            if _sports_or_entertainment(i.get("link", "")):
                continue
            title = _clean(i.get("title", ""))
            same = _NOT_WORD.sub("", title)
            if same in seen:
                continue
            seen.add(same)
            news.append({"title": title,
                         "url": i.get("originallink") or i.get("link") or "",
                         "date": _date(i.get("pubDate", ""))})
        return sorted(_spread_by_day(news, n), key=lambda x: x["date"], reverse=True)
