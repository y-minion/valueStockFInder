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
from vsf.data.krx import BASE as KRX_BASE  # noqa: E402
from vsf.data.krx import BASE_FIELDS, DAILY_FIELDS  # noqa: E402

COMPANIES = {"기아": "000270", "제일기획": "030000"}
RAW_FIRST_ROWS = "_raw_first_rows.json"


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


def fetch_krx(http: httpx.Client, service: str, key: str, day: str) -> dict:
    """KRX GET 한 번. 키는 헤더로만 보내고, 실패 메시지에는 서비스 이름과 상태 코드만 담아요."""
    failure: str | None = None
    resp = None
    try:
        resp = http.get(KRX_BASE + service, params={"basDd": day}, headers={"AUTH_KEY": key})
        if resp.status_code >= 400:
            failure = f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        failure = f"연결 오류 ({type(e).__name__})"
    if failure is not None:
        raise RecorderError(f"{service} 요청이 실패했어요: {failure}")
    return resp.json()


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


def first_rows_json(bodies: dict[str, dict], key: str) -> str:
    """응답마다 OutBlock_1의 첫 줄을 거르지 않고 그대로 모은 JSON 글이에요. 키 글자는 지워요.

    DAILY_FIELDS·BASE_FIELDS의 필드 이름이 실제 응답과 다르면 여기서 바로 보여요.
    """
    first: dict[str, dict | None] = {}
    for name, body in bodies.items():
        rows = body.get("OutBlock_1") if isinstance(body, dict) else None
        first[name] = rows[0] if isinstance(rows, list) and rows else None
    return json.dumps(first, ensure_ascii=False, indent=2).replace(key, "REMOVED") + "\n"


def record_krx(key: str, out: Path, http: httpx.Client | None = None) -> int:
    """일별매매정보 2일, 종목기본정보 1일을 받아 여섯 종목 안팎으로 줄여 저장해요.

    응답마다 거르지 않은 첫 줄도 _raw_first_rows.json에 따로 남겨요.
    """
    out.mkdir(parents=True, exist_ok=True)
    http = http or httpx.Client(timeout=60)
    base_day = "20261113"
    raw: dict[str, dict] = {}

    def get(service: str, day: str) -> list[dict]:
        body = fetch_krx(http, service, key, day)
        raw[f"{service}_{day}"] = body
        return body.get("OutBlock_1", [])

    base: dict[str, list[dict]] = {}
    for prefix in ("stk", "ksq"):
        service = f"{prefix}_isu_base_info"
        base[service] = get(service, base_day)

    c = BASE_FIELDS
    every = [r for rows in base.values() for r in rows]

    def first(pred) -> str | None:
        return next((r[c["code"]] for r in every if pred(r)), None)

    picks = {
        "000270", "030000",
        first(lambda r: "우선주" in r.get(c["kind"], "")),
        first(lambda r: r.get(c["group"]) == "부동산투자회사"),
        first(lambda r: "스팩" in r.get(c["name"], "")),
        first(lambda r: r.get(c["group"]) == "주권" and r.get(c["kind"]) == "보통주"
              and r[c["code"]] not in ("000270", "030000")),
    } - {None}

    written: list[str] = []

    def save(name: str, rows: list[dict], code_field: str) -> None:
        kept = [r for r in rows if r.get(code_field) in picks]
        text = json.dumps({"OutBlock_1": kept}, ensure_ascii=False, indent=2)
        (out / name).write_text(text.replace(key, "REMOVED") + "\n", encoding="utf-8")
        written.append(f"{name} ({len(kept)}행)")

    for service, rows in base.items():
        save(f"{service}_{base_day}.json", rows, c["code"])
    for day in ("20251230", "20261113"):
        for prefix in ("stk", "ksq"):
            service = f"{prefix}_bydd_trd"
            rows = get(service, day)
            save(f"{service}_{day}.json", rows, DAILY_FIELDS["code"])
    (out / RAW_FIRST_ROWS).write_text(first_rows_json(raw, key), encoding="utf-8")
    written.append(RAW_FIRST_ROWS)
    print("\n".join(sorted(written)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dart", help="OpenDART 응답 녹화")
    sub.add_parser("krx", help="KRX OPEN API 응답 녹화")
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
    if args.cmd == "krx":
        try:
            return record_krx(keys.krx, ROOT / "tests" / "fixtures" / "krx" / "recorded")
        except RecorderError as e:
            print(f"녹화를 멈췄어요. {e}", file=sys.stderr)
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
