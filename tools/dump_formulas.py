"""계산기 '분석_빈칸' 시트에서 수식이 든 칸을 뽑아요 (읽기만 해요)."""
import html
import re
import sys
import zipfile
from pathlib import Path

SHEET_NAME = "분석_빈칸"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _sheet_xml_path(z: zipfile.ZipFile, name: str) -> str:
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rid = None
    for m in re.finditer(r"<sheet\b[^>]*>", wb):
        tag = m.group(0)
        n = re.search(r'\bname="([^"]*)"', tag)
        if n and html.unescape(n.group(1)) == name:
            r = re.search(r'\br:id="([^"]*)"', tag) or re.search(rf'\b\w+:id="([^"]*)"', tag)
            rid = r.group(1)
            break
    if rid is None:
        raise KeyError(f"시트를 찾을 수 없어요: {name}")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    for m in re.finditer(r"<Relationship\b[^>]*>", rels):
        tag = m.group(0)
        if re.search(rf'\bId="{re.escape(rid)}"', tag):
            target = re.search(r'\bTarget="([^"]*)"', tag).group(1)
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    raise KeyError(f"관계를 찾을 수 없어요: {rid}")


def _col_key(addr: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", addr)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


def formulas_by_address(path: Path, sheet: str = SHEET_NAME) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read(_sheet_xml_path(z, sheet)).decode("utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", xml, re.S):
        attrs, body = m.group(1), m.group(2) or ""
        f = re.search(r"<f\b[^>]*?(?:/>|>(.*?)</f>)", body, re.S)
        if f is None:
            continue
        addr = re.search(r'\br="([A-Z]+\d+)"', attrs).group(1)
        out[addr] = html.unescape(f.group(1) or "")
    return dict(sorted(out.items(), key=lambda kv: _col_key(kv[0])))


def formula_addresses(path: Path) -> list[str]:
    return list(formulas_by_address(path))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        template = Path(sys.argv[1])
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from vsf.config import load_settings
        template = load_settings(Path(__file__).resolve().parents[1] / "settings.toml").calculator_path
    for a, f in formulas_by_address(template).items():
        print(f"{a}\t{f}")
