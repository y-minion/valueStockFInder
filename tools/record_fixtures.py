"""실제 API 응답을 tests/fixtures/{dart,krx}/recorded/ 에 녹화해요.

사용법: uv run python tools/record_fixtures.py dart
keys.toml이 있어야 해요. 저장하는 파일에서 API 키는 지워요.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import httpx
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vsf.config import ConfigError, load_keys  # noqa: E402
from vsf.data.dart import BASE as DART_BASE  # noqa: E402

COMPANIES = {"기아": "000270", "제일기획": "030000"}


class RecorderError(Exception):
    """요청 실패. 메시지에는 엔드포인트 이름과 상태 코드만 담아요 (URL·키 없음)."""


def fetch(http: httpx.Client, endpoint: str, key: str, **params) -> httpx.Response:
    """GET 한 번. 실패해도 예외·출력에 URL(=API 키)이 남지 않게 해요."""
    failure: str | None = None
    resp = None
    try:
        resp = http.get(DART_BASE + endpoint, params={"crtfc_key": key, **params})
        if resp.status_code >= 400:
            failure = f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        failure = f"연결 오류 ({type(e).__name__})"
    if failure is not None:  # except 블록 밖에서 던져서 원본 예외가 연결되지 않아요
        raise RecorderError(f"{endpoint} 요청이 실패했어요: {failure}")
    return resp


def _scrub(text: str, key: str) -> str:
    return re.sub(r"crtfc_key=[^&\"'\s]*", "crtfc_key=REMOVED", text.replace(key, "REMOVED"))


def record_dart(key: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(timeout=60)
    written: list[str] = []

    def get(endpoint: str, **params) -> httpx.Response:
        return fetch(http, endpoint, key, **params)

    def save_json(name: str, resp: httpx.Response, truncate: int | None = None) -> None:
        data = resp.json()
        if truncate and "list" in data:
            data["list"] = data["list"][:truncate]
        (out / name).write_text(
            _scrub(json.dumps(data, ensure_ascii=False, indent=2), key) + "\n", encoding="utf-8")
        written.append(name)
        if data.get("status") != "000":
            print(f"경고: {name} status={data.get('status')}", file=sys.stderr)

    # corpCode: 두 회사만 남긴 작은 zip
    raw = get("corpCode.xml").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root = etree.fromstring(z.read("CORPCODE.xml"))
    stocks = set(COMPANIES.values())
    corp_of: dict[str, str] = {}
    for item in list(root.iter("list")):
        sc = (item.findtext("stock_code") or "").strip()
        if sc in stocks:
            corp_of[sc] = item.findtext("corp_code", "").strip()
        else:
            item.getparent().remove(item)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("CORPCODE.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    (out / "corpcode.zip").write_bytes(buf.getvalue())
    written.append("corpcode.zip")

    for sc in COMPANIES.values():
        corp = corp_of[sc]
        save_json(f"company_{sc}.json", get("company.json", corp_code=corp))
        for year in (2025, 2023):
            save_json(f"fin_{sc}_{year}_cfs.json", get(
                "fnlttSinglAcntAll.json", corp_code=corp, bsns_year=year,
                reprt_code="11011", fs_div="CFS"))
        for year in (2025, 2023, 2021, 2019, 2017):
            save_json(f"div_{sc}_{year}.json", get(
                "alotMatter.json", corp_code=corp, bsns_year=year, reprt_code="11011"))
    save_json("filings_202603_A001.json", get(
        "list.json", bgn_de="20260301", end_de="20260331", pblntf_detail_ty="A001",
        page_no=1, page_count=100), truncate=5)

    print("\n".join(sorted(written)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dart", help="OpenDART 응답 녹화")
    # krx 하위 명령은 Task 7에서 추가해요.
    args = ap.parse_args(argv)
    try:
        keys = load_keys(ROOT / "keys.toml")
    except ConfigError as e:
        print(e, file=sys.stderr)
        print("keys.toml이 준비되면 다시 실행해 주세요.", file=sys.stderr)
        return 2
    if args.cmd == "dart":
        try:
            return record_dart(keys.dart, ROOT / "tests" / "fixtures" / "dart" / "recorded")
        except RecorderError as e:
            print(f"녹화를 멈췄어요. {e}", file=sys.stderr)
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
