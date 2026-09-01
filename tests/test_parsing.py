"""Tests for backend.parsing: upload validation, sheet listing, reading, range extraction."""

from pathlib import Path

import pytest

from backend import config, parsing

FIXTURES = Path(__file__).parent / "fixtures"


def _read_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_validate_upload_accepts_xlsx():
    content = _read_bytes("sample.xlsx")
    parsing.validate_upload("sample.xlsx", content)  # should not raise


def test_validate_upload_rejects_txt_extension():
    with pytest.raises(parsing.ValidationError):
        parsing.validate_upload("notes.txt", b"hello")


def test_validate_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 0)
    with pytest.raises(parsing.PayloadTooLargeError):
        parsing.validate_upload("sample.csv", b"a,b\n1,2\n")


def test_list_sheets_xlsx_returns_both_sheets():
    content = _read_bytes("sample.xlsx")
    sheets = parsing.list_sheets("sample.xlsx", content)
    assert sheets == ["Data1", "Data2"]


def test_list_sheets_csv_returns_single_virtual_sheet():
    content = _read_bytes("sample.csv")
    sheets = parsing.list_sheets("sample.csv", content)
    assert sheets == [parsing.CSV_SHEET_NAME]


def test_store_and_get_upload_roundtrip():
    content = _read_bytes("sample.csv")
    file_id = parsing.store_upload("sample.csv", content)
    filename, stored = parsing.get_upload(file_id)
    assert filename == "sample.csv"
    assert stored == content


def test_get_upload_unknown_file_id_raises():
    with pytest.raises(parsing.ValidationError):
        parsing.get_upload("does-not-exist")


def test_read_sheet_unknown_sheet_raises():
    content = _read_bytes("sample.xlsx")
    with pytest.raises(parsing.ValidationError):
        parsing.read_sheet("sample.xlsx", content, "NoSuchSheet", header_row=1)


def test_read_sheet_returns_expected_columns():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=1)
    assert list(df.columns) == ["Tid", "X1", "X2", "Y"]
    assert len(df) == 12


def test_read_sheet_header_row_zero_raises():
    content = _read_bytes("sample.xlsx")
    with pytest.raises(parsing.ValidationError, match="Excel-radnummer"):
        parsing.read_sheet("sample.xlsx", content, "Data1", header_row=0)


def test_read_sheet_header_row_beyond_sheet_raises():
    content = _read_bytes("sample.xlsx")
    with pytest.raises(parsing.ValidationError, match="finnes ikke i arket"):
        parsing.read_sheet("sample.xlsx", content, "Data1", header_row=999)


def test_read_sheet_with_header_on_excel_row_three():
    content = _read_bytes("sample_header_row3.xlsx")
    df = parsing.read_sheet("sample_header_row3.xlsx", content, "Data1", header_row=3)
    assert list(df.columns) == ["Tid", "X1", "X2", "Y"]
    assert df.iloc[0]["Tid"] == 1
    assert len(df) == 12


def test_extract_range_slices_inclusive_and_labels_excel_row_numbers():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=1)
    # header on Excel row 1 -> first data row is Excel row 2
    sliced = parsing.extract_range(df, header_row=1, start_row=3, end_row=5)
    assert len(sliced) == 3
    assert sliced["Tid"].tolist() == [2, 3, 4]
    assert sliced.index.tolist() == [3, 4, 5]


def test_extract_range_with_header_on_row_three():
    content = _read_bytes("sample_header_row3.xlsx")
    df = parsing.read_sheet("sample_header_row3.xlsx", content, "Data1", header_row=3)
    sliced = parsing.extract_range(df, header_row=3, start_row=5, end_row=6)
    assert sliced.index.tolist() == [5, 6]
    assert sliced["Tid"].tolist() == [2, 3]


def test_select_columns_returns_subset():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=1)
    subset = parsing.select_columns(df, start_col=2, end_col=3)
    assert list(subset.columns) == ["X1", "X2"]


def test_select_columns_start_after_end_raises():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=1)
    with pytest.raises(parsing.ValidationError, match="Startkolonne"):
        parsing.select_columns(df, start_col=3, end_col=2)


def test_read_sheet_semicolon_separator_with_comma_decimal():
    content = b"Tid;Y;X1;X2\n1;1,5;2,5;3,5\n2;2,5;3,5;4,5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=1)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert df["Y"].dtype.kind in "if"
    assert df["Y"].iloc[0] == pytest.approx(1.5)


def test_read_sheet_semicolon_separator_with_point_decimal():
    content = b"Tid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=1)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert df["Y"].dtype.kind in "if"
    assert df["Y"].iloc[0] == pytest.approx(1.5)


def test_read_sheet_comma_separator_still_works():
    content = b"Tid,Y,X1,X2\n1,1.5,2.5,3.5\n2,2.5,3.5,4.5\n"
    df = parsing.read_sheet("comma.csv", content, parsing.CSV_SHEET_NAME, header_row=1)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert df["Y"].dtype.kind in "if"
    assert df["Y"].iloc[0] == pytest.approx(1.5)


def test_read_sheet_tab_separator_detected():
    content = b"Tid\tY\tX1\tX2\n1\t1.5\t2.5\t3.5\n2\t2.5\t3.5\t4.5\n"
    df = parsing.read_sheet("tab.csv", content, parsing.CSV_SHEET_NAME, header_row=1)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]


def test_read_sheet_single_column_with_no_separator_character():
    content = b"OnlyCol\nfoo\nbar\n"
    df = parsing.read_sheet("single.csv", content, parsing.CSV_SHEET_NAME, header_row=1)
    assert list(df.columns) == ["OnlyCol"]
    assert len(df) == 2


def test_read_sheet_header_row_two_on_semicolon_file():
    # A title row precedes the header (a plausible header_row > 1 case);
    # it is itself semicolon-padded, so separator detection (which reads
    # the raw first non-empty line, not the header line) still picks ";".
    content = b"Overskrift;;;\nTid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert len(df) == 2
    assert df["Y"].iloc[0] == pytest.approx(1.5)
