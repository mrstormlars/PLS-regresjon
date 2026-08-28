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
        parsing.read_sheet("sample.xlsx", content, "NoSuchSheet", header_row=0)


def test_read_sheet_returns_expected_columns():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=0)
    assert list(df.columns) == ["Tid", "X1", "X2", "Y"]
    assert len(df) == 12


def test_extract_range_slices_inclusive():
    content = _read_bytes("sample.xlsx")
    df = parsing.read_sheet("sample.xlsx", content, "Data1", header_row=0)
    sliced = parsing.extract_range(df, start_row=2, end_row=4)
    assert len(sliced) == 3
    assert sliced["Tid"].tolist() == [3, 4, 5]
