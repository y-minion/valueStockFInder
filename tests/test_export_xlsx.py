import json
import zipfile
from dataclasses import replace
from datetime import date

import pytest
from engine_cases import CASES
from helpers import D, OTHER_SHEETS, XlsxReader, formulas_eval, load_oracle, sha256
from lxml import etree

from vsf.engine import compute
from vsf.export_xlsx import NUMBERS_GUIDE, export_xlsx, safe_file_stem, safe_sheet_name
from vsf.model import Criteria, StockInputs

KIA = CASES["kia"][0]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@pytest.mark.template
def test_export_kia(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia"); cells = compute(inputs, c)
    before = sha256(template_path); p = export_xlsx(template_path, tmp_path, inputs, cells, c, date(2026, 11, 14))
    assert p.name == "2026-11-14_기아_000270.xlsx" and sha256(template_path) == before
    x = XlsxReader(p)
    assert "기아" in x.sheet_names and "분석_빈칸" not in x.sheet_names
    assert x.cell("기아", "B19") == ("inlineStr", "000270") and x.cell("기아", "F27")[1] == "19382"
    assert x.cell("기아", "B21")[1] == "46335" and x.cell("기아", "D82") == ("str", "통과")
    assert x.cell("기아", "B15")[1] == cells["B15"] and "'기아'!$B$27:$F$27" in x.chart_xml_for("기아")
    assert x.cell("기준값", "B5")[1] == "0.1"
    assert NUMBERS_GUIDE in x.cell("기아", "B23")[1]


@pytest.mark.template
def test_criteria_written(template_path, tmp_path):
    inputs, _, _ = load_oracle("kia"); c = Criteria(required_return=0.09)
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D)
    assert XlsxReader(p).cell("기준값", "B5")[1] == "0.09"


@pytest.mark.template
def test_never_overwrites(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia"); cells = compute(inputs, c)
    a = export_xlsx(template_path, tmp_path, inputs, cells, c, D)
    b = export_xlsx(template_path, tmp_path, inputs, cells, c, D)
    assert a != b and b.name.endswith("_2.xlsx") and a.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([a.name, b.name])   # 임시 파일이 남지 않아요


@pytest.mark.template
def test_unsafe_names_are_sanitized(template_path, tmp_path):
    for name in ("A/B:C*D?[E]", "가" * 40):
        p = export_xlsx(template_path, tmp_path, replace(KIA, name=name),
                        compute(replace(KIA, name=name), Criteria()), Criteria(), D)
        sn = [s for s in XlsxReader(p).sheet_names if s not in OTHER_SHEETS][0]
        assert len(sn) <= 31 and not set(sn) & set('[]:*?/\\') and p.exists()


@pytest.mark.template
@pytest.mark.slow
def test_export_recalculates_same(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia_full_pass"); cells = compute(inputs, c)
    got = formulas_eval(export_xlsx(template_path, tmp_path, inputs, cells, c, D), sheet="기아")
    for a in ("D82", "D90", "D110", "D135", "B105", "B107", "B15"):
        assert got[a] == pytest.approx(cells[a]) if isinstance(cells[a], float) else got[a] == cells[a]


@pytest.mark.template
def test_other_zip_members_untouched(template_path, tmp_path):
    inputs, c, _ = load_oracle("kia")
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D)
    changed = {"xl/worksheets/sheet2.xml", "xl/workbook.xml", "xl/charts/chart1.xml", "xl/worksheets/sheet6.xml"}
    with zipfile.ZipFile(template_path) as a, zipfile.ZipFile(p) as b:
        assert [i.filename for i in a.infolist()] == [i.filename for i in b.infolist()]
        for ia, ib in zip(a.infolist(), b.infolist()):
            assert ia.compress_type == ib.compress_type
            if ia.filename not in changed:
                assert a.read(ia) == b.read(ib), ia.filename
    assert b"fullCalcOnLoad=\"1\"" in zipfile.ZipFile(p).read("xl/workbook.xml")


@pytest.mark.template
def test_none_inputs_and_text_year_and_integral_numbers(template_path, tmp_path):
    # 값이 든 입력 칸 위에 None을 쓰면 값이 지워지고 스타일은 남아요
    inputs = replace(KIA, pbr=None, memo="")
    c = Criteria()
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D)
    x = XlsxReader(p)
    assert x.cell("기아", "B22") == (None, None)
    root = etree.fromstring(x.z.read(x._paths["기아"]))
    b22 = [e for e in root.iterfind(".//m:c", NS) if e.get("r") == "B22"][0]
    assert b22.get("s") == "33" and len(b22) == 0 and b22.get("t") is None
    assert x.cell("기아", "B23")[1] == NUMBERS_GUIDE      # 메모가 비면 앞 공백이 없어요
    assert x.cell("기아", "B26") == ("inlineStr", "2021")  # 연도는 글자
    assert x.cell("기아", "B27") == ("n", "11874")           # 정수는 .0 없이
    assert x.cell("기아", "B28") == ("n", "6.92")
    assert x.cell("기아", "B20") == ("n", "97000")


@pytest.mark.template
def test_extra_note_and_memo(template_path, tmp_path):
    inputs = replace(KIA, memo="내 메모")
    c = Criteria()
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D, extra_note="업종 PER 낮음")
    assert XlsxReader(p).cell("기아", "B23")[1] == f"내 메모 {NUMBERS_GUIDE} 업종 비교 항목(엑셀에는 없음): 업종 PER 낮음"


@pytest.mark.template
def test_flags_follow_the_memo_before_the_guide(template_path, tmp_path):
    inputs = replace(KIA, memo="내 메모")
    c = Criteria()
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D, extra_note="업종 PER 낮음",
                    flags=("표시 하나", "표시 둘"))
    assert XlsxReader(p).cell("기아", "B23")[1] == (
        f"내 메모 표시 하나 표시 둘 {NUMBERS_GUIDE} 업종 비교 항목(엑셀에는 없음): 업종 PER 낮음")


@pytest.mark.template
def test_memo_order_with_financial_note(template_path, tmp_path):
    inputs = replace(KIA, memo="내 메모")
    c = Criteria()
    p = export_xlsx(template_path, tmp_path, inputs, compute(inputs, c), c, D, extra_note="업종 PER 낮음",
                    flags=("표시 하나",), financial_note="금융 메모")
    assert XlsxReader(p).cell("기아", "B23")[1] == (
        f"내 메모 표시 하나 금융 메모 {NUMBERS_GUIDE} 업종 비교 항목(엑셀에는 없음): 업종 PER 낮음")


def test_refuses_template_path(tmp_path):
    fake = tmp_path / "2026-11-14_기아_000270.xlsx"
    fake.write_bytes(b"not a real workbook")
    c = Criteria()
    with pytest.raises(ValueError):
        export_xlsx(fake, tmp_path, KIA, compute(KIA, c), c, D)
    assert fake.read_bytes() == b"not a real workbook"


def test_safe_names():
    assert safe_sheet_name("A/B:C*D?[E]", set()) == "ABCDE"
    assert safe_sheet_name("[]", set()) == "분석"
    assert safe_sheet_name("  'x'  ", set()) == "x"
    assert safe_sheet_name("기아", {"기아"}) == "기아 (2)"
    assert safe_sheet_name("기아", {"기아", "기아 (2)"}) == "기아 (3)"
    long = safe_sheet_name("가" * 40, {"가" * 31})
    assert len(long) <= 31 and long.endswith(" (2)")
    assert safe_file_stem('a b/c:d*e?f"g<h>i|j\\k') == "a_b_c_d_e_f_g_h_i_j_k"


def test_numbers_check_print_script(tmp_path, capsys):
    from tools.numbers_check import main
    exp = tmp_path / "e.json"
    exp.write_text(json.dumps({"cells": {"D82": "통과", "B105": 92951.47}}, ensure_ascii=False), encoding="utf-8")
    assert main([str(tmp_path / 'a"b.xlsx'), str(exp), "--sheet", '기"아', "--print-script"]) == 0
    out = capsys.readouterr().out
    assert 'tell application "Numbers"' in out and "D82" in out and "B105" in out and "D135" in out
    assert 'a\\"b.xlsx' in out and '기\\"아' in out and "close d saving no" in out


def test_numbers_check_compare():
    from tools.numbers_check import compare
    rows = compare({"A1": "통과", "A2": 100.0, "A3": 1.0, "A4": "x"}, {"A1": "통과", "A2": 100.00001, "A3": 1.1})
    assert [r[3] for r in rows] == [True, True, False, False]
