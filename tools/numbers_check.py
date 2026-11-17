"""내보낸 xlsx를 Numbers로 열어서 칸 값이 기대값과 같은지 확인해요 (macOS 전용, 손으로 돌려요).

사용: uv run python tools/numbers_check.py <xlsx> <expected.json> [--sheet 이름] [--print-script]
expected.json: {"cells": {"D82": "통과", "B105": 92951.47}}
처음 돌릴 때 macOS가 '자동화' 권한을 물어봐요. pytest에서는 돌리지 않아요.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REL_TOL = 1e-6
# 다시 계산 확인: 관문 ④ 칸을 채우면 D135가 "통과"가 돼야 해요
RECALC_INPUTS = (("B129", "테스트"), ("B130", "예"), ("B131", "예"), ("B132", "예"), ("B133", "일시적"))
RECALC_CELL, RECALC_WANT = "D135", "통과"


def q(s: str) -> str:
    """AppleScript 글자 값으로 안전하게 감싸요."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_script(xlsx: str, sheet: str | None, addrs: list[str]) -> str:
    sheet_ref = f"sheet {q(sheet)}" if sheet else "sheet 2"
    lines = [
        "on fmt(v)",
        "  if v is missing value then return \"e:\"",
        "  if class of v is text then return \"s:\" & v",
        "  return \"n:\" & (v as real as text)",
        "end fmt",
        'tell application "Numbers"',
        f"  set d to open POSIX file {q(xlsx)}",
        "  set outText to \"\"",
        "  try",
        f"    set t to table 1 of {sheet_ref} of d",
    ]
    for a in addrs:
        lines.append(f'    set outText to outText & {q(a)} & tab & (my fmt(value of cell {q(a)} of t)) & linefeed')
    for a, v in RECALC_INPUTS:
        lines.append(f"    set value of cell {q(a)} of t to {q(v)}")
    lines += ["    delay 1",
              f'    set outText to outText & "RECALC" & tab & (my fmt(value of cell {q(RECALC_CELL)} of t)) & linefeed',
              "  on error m",
              "    close d saving no",
              "    error m",
              "  end try",
              "  close d saving no",
              "end tell",
              "return outText"]
    return "\n".join(lines)


def parse_output(text: str) -> dict[str, float | str | None]:
    out: dict[str, float | str | None] = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        addr, raw = line.split("\t", 1)
        kind, _, val = raw.partition(":")
        out[addr] = float(val) if kind == "n" else (val if kind == "s" else None)
    return out


def _same(want, got) -> bool:
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(want - got) <= REL_TOL * max(abs(want), abs(got), 1e-300) or want == got
    return want == got or (want in (None, "") and got in (None, ""))


def compare(expected: dict, actual: dict) -> list[tuple[str, object, object, bool]]:
    return [(a, w, actual.get(a), _same(w, actual.get(a))) for a, w in expected.items()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("xlsx")
    ap.add_argument("expected")
    ap.add_argument("--sheet")
    ap.add_argument("--print-script", action="store_true", help="Numbers를 열지 않고 AppleScript만 출력해요")
    args = ap.parse_args(argv)
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))["cells"]
    script = build_script(str(Path(args.xlsx).resolve()) if not args.print_script else args.xlsx,
                          args.sheet, list(expected))
    if args.print_script:
        print(script)
        return 0
    run = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True)
    if run.returncode != 0:
        print(f"Numbers 실행 실패: {run.stderr.strip()}")
        return 1
    actual = parse_output(run.stdout)
    rows = compare(expected, actual)
    rows.append((f"{RECALC_CELL} (다시 계산)", RECALC_WANT, actual.get("RECALC"),
                 actual.get("RECALC") == RECALC_WANT))
    print(f"{'칸':<16}{'기대값':<24}{'Numbers 값':<24}결과")
    for a, w, g, ok in rows:
        print(f"{a:<16}{w!s:<24}{g!s:<24}{'통과' if ok else '탈락'}")
    bad = [r for r in rows if not r[3]]
    print(f"\n{len(rows) - len(bad)}/{len(rows)}칸 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
