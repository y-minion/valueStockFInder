"""사용자의 계산기 xlsx를 한 종목 값으로 채워서 새 파일로 내보내요 (원본은 읽기만 해요).

Numbers는 TEXT()를 못 돌리니, 수식 칸마다 엔진이 계산한 값을 캐시 값으로 같이 써요.
"""
import os
import posixpath
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from lxml import etree

from vsf.model import (FORMULA_CELLS, Criteria, SheetValues, StockInputs, criteria_to_cells,
                       to_cells)

SHEET_NAME = "분석_빈칸"
CRITERIA_SHEET = "기준값"
NUMBERS_GUIDE = ("Numbers에서는 ④ 질문 칸에 '예', '아니오', '모르겠음' 중 하나를, "
                 "나의 판단 칸에 '일시적', '구조적', '모르겠음' 중 하나를 글자 그대로 입력해요.")
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_M = "{%s}" % _NS
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_EPOCH = date(1899, 12, 30)


def safe_sheet_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "", name).strip(" '")[:31].strip(" '") or "분석"
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f" ({n})"
        cand = base[:31 - len(suffix)] + suffix
        if cand not in taken:
            return cand
        n += 1


def safe_file_stem(text: str) -> str:
    return re.sub(r'[/:\\*?"<>|\s]', "_", text)


def _target(base: str, target: str) -> str:
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(
        posixpath.join(posixpath.dirname(base), target))


def _rels_of(z: dict[str, bytes], part: str) -> list[tuple[str, str]]:
    """part의 (관계 종류, 대상 경로) 목록."""
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in z:
        return []
    return [(r.get("Type"), _target(part, r.get("Target"))) for r in etree.fromstring(z[path])]


def _parse(data: bytes):
    return etree.fromstring(data)


def _dump(root, original: bytes) -> bytes:
    if original.lstrip().startswith(b"<?xml"):
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return etree.tostring(root, encoding="UTF-8")


def _col(addr: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", addr)
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return int(m.group(2)), n


def _number(v: float) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def _clear(c) -> None:
    for child in list(c):
        if child.tag in (_M + "v", _M + "is"):
            c.remove(child)


def _set_value(c, v) -> None:
    """입력 칸 하나를 써요 (스타일은 그대로)."""
    _clear(c)
    if v is None:
        c.attrib.pop("t", None)
    elif isinstance(v, str):
        c.set("t", "inlineStr")
        t = etree.SubElement(etree.SubElement(c, _M + "is"), _M + "t")
        t.text = v
        if v != v.strip():
            t.set(_XML_SPACE, "preserve")
    else:
        if isinstance(v, date):
            v = (v - _EPOCH).days
        c.set("t", "n")
        etree.SubElement(c, _M + "v").text = _number(v)


def _set_cached(c, v) -> None:
    """수식 칸의 캐시 값만 바꿔요 (<f>는 그대로)."""
    for child in list(c):
        if child.tag in (_M + "v", _M + "is"):
            c.remove(child)
    v_el = etree.SubElement(c, _M + "v")
    if isinstance(v, str):
        c.set("t", "str"); v_el.text = v
    elif v is None:
        c.set("t", "str"); v_el.text = ""
    else:
        c.set("t", "n"); v_el.text = _number(v)


def _cell(root, addr: str, index: dict):
    if addr in index:
        return index[addr]
    sheet_data = root.find(_M + "sheetData")
    row_no, col_no = _col(addr)
    row = next((r for r in sheet_data if r.get("r") == str(row_no)), None)
    if row is None:
        row = etree.Element(_M + "row", r=str(row_no))
        after = [r for r in sheet_data if int(r.get("r")) < row_no]
        sheet_data.insert(len(after), row)
    c = etree.Element(_M + "c", r=addr)
    pos = 0
    for pos, existing in enumerate(row):
        if _col(existing.get("r"))[1] > col_no:
            row.insert(pos, c)
            break
    else:
        row.append(c)
    index[addr] = c
    return c


def _index(root) -> dict:
    return {c.get("r"): c for c in root.iter(_M + "c")}


def _sheet_paths(z: dict[str, bytes]) -> dict[str, str]:
    wb = _parse(z["xl/workbook.xml"])
    targets = {r.get("Id"): _target("xl/workbook.xml", r.get("Target"))
               for r in _parse(z["xl/_rels/workbook.xml.rels"])}
    return {s.get("name"): targets[s.get("{%s}id" % _RNS)] for s in wb.iter(_M + "sheet")}


def _memo(inputs: StockInputs, extra_note: str, flags: tuple[str, ...] = ()) -> str:
    text = inputs.memo + "".join(f" {f}" for f in flags) + f" {NUMBERS_GUIDE}"
    if extra_note:
        text += f" 업종 비교 항목(엑셀에는 없음): {extra_note}"
    return text.lstrip(" ")


def _free_path(out_dir: Path, stem: str, template: Path) -> Path:
    n = 1
    while True:
        cand = out_dir / (f"{stem}.xlsx" if n == 1 else f"{stem}_{n}.xlsx")
        if cand.resolve() == template.resolve():
            raise ValueError("내보내기 경로가 원본 계산기와 같아요. 원본은 덮어쓰지 않아요.")
        if not cand.exists():
            return cand
        n += 1


def export_xlsx(template: Path, out_dir: Path, inputs: StockInputs, cells: SheetValues,
                criteria: Criteria, today: date, extra_note: str = "",
                flags: tuple[str, ...] = ()) -> Path:
    template, out_dir = Path(template), Path(out_dir)
    stem = f"{today.isoformat()}_{safe_file_stem(inputs.name)}_{inputs.code}"
    _free_path(out_dir, stem, template)   # 원본과 같은 경로면 바로 거절해요
    with zipfile.ZipFile(template) as zf:
        infos = zf.infolist()
        members = {i.filename: zf.read(i) for i in infos}

    paths = _sheet_paths(members)
    sheet_path, crit_path = paths[SHEET_NAME], paths[CRITERIA_SHEET]
    new_name = safe_sheet_name(inputs.name, set(paths) - {SHEET_NAME})
    changed: dict[str, bytes] = {}

    # 분석 시트: 입력 칸과 수식 캐시 값
    root = _parse(members[sheet_path])
    index = _index(root)
    values = to_cells(inputs)
    values["B23"] = _memo(inputs, extra_note, flags)
    for addr, v in values.items():
        _set_value(_cell(root, addr, index), v)
    for addr in FORMULA_CELLS:
        c = index.get(addr)
        if c is None or c.find(_M + "f") is None:
            raise ValueError(f"수식 칸을 찾을 수 없어요: {addr}")
        _set_cached(c, cells[addr])
    changed[sheet_path] = _dump(root, members[sheet_path])

    # 기준값 시트
    root = _parse(members[crit_path])
    index = _index(root)
    for addr, v in criteria_to_cells(criteria).items():
        _set_value(_cell(root, addr, index), v)
    changed[crit_path] = _dump(root, members[crit_path])

    # 시트 이름 (workbook.xml)
    root = _parse(members["xl/workbook.xml"])
    for s in root.iter(_M + "sheet"):
        if s.get("name") == SHEET_NAME:
            s.set("name", new_name)
    changed["xl/workbook.xml"] = _dump(root, members["xl/workbook.xml"])

    # 차트가 가리키는 시트 이름
    ref = "'" + new_name.replace("'", "''") + "'!"
    pattern = re.compile(r"(?:'" + SHEET_NAME + r"'|" + SHEET_NAME + r")!")
    for rtype, drawing in _rels_of(members, sheet_path):
        if not rtype.endswith("/drawing"):
            continue
        for ctype, chart in _rels_of(members, drawing):
            if not ctype.endswith("/chart"):
                continue
            root = _parse(members[chart])
            for el in root.iter():
                if isinstance(el.tag, str) and el.tag.split("}")[-1] == "f" and el.text:
                    el.text = pattern.sub(lambda _: ref, el.text)
            changed[chart] = _dump(root, members[chart])

    out_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=out_dir)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w") as zout:
            for info in infos:
                zout.writestr(info, changed.get(info.filename, members[info.filename]))
        while True:
            dest = _free_path(out_dir, stem, template)
            try:
                os.link(tmp, dest)   # 이미 있으면 실패해요: 기존 내보내기를 덮어쓰지 않아요
            except FileExistsError:
                continue
            except OSError:
                if dest.exists():
                    continue
                os.replace(tmp, dest)
            return dest
    finally:
        tmp.unlink(missing_ok=True)
