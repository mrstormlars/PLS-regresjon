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
