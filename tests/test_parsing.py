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
    # it is itself semicolon-padded, so separator detection - which now
    # tallies occurrences across all non-empty lines of the sample, not
    # just the first one - still picks ";".
    content = b"Overskrift;;;\nTid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert len(df) == 2
    assert df["Y"].iloc[0] == pytest.approx(1.5)


def test_read_sheet_separator_free_title_line_above_semicolon_header():
    # This is the primary real-world case (Excel sheets with a title row
    # above the header): a title line with none of the candidate
    # separators must not outvote the semicolons in the header/data lines
    # below it.
    content = b"Rapport 2026\nTid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]


def test_read_sheet_separator_free_title_line_above_tab_header():
    content = b"Rapport 2026\nTid\tY\tX1\tX2\n1\t1.5\t2.5\t3.5\n2\t2.5\t3.5\t4.5\n"
    df = parsing.read_sheet("tab.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]


def test_read_sheet_separator_free_title_line_above_comma_header():
    # Regression guard: a separator-free title line must not make the
    # total-occurrence rule pick something other than "," for an otherwise
    # ordinary comma file.
    content = b"Rapport 2026\nTid,Y,X1,X2\n1,1.5,2.5,3.5\n2,2.5,3.5,4.5\n"
    df = parsing.read_sheet("comma.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]


def test_read_sheet_malformed_csv_raises_validation_error_not_parser_error():
    # Header declares 3 fields, a data row has 4 - a genuine tokenizing
    # failure, unrelated to separator/decimal ambiguity, that pandas would
    # otherwise raise as an unhandled pandas.errors.ParserError.
    content = b"A;B;C\n1;2;3\n4;5;6;7\n"
    with pytest.raises(parsing.ValidationError, match="CSV"):
        parsing.read_sheet("bad.csv", content, parsing.CSV_SHEET_NAME, header_row=1)


def test_read_sheet_blank_line_above_comma_header_keeps_row_numbering():
    content = b"\nTid,Y,X1,X2\n1,1.5,2.5,3.5\n2,2.5,3.5,4.5\n"
    df = parsing.read_sheet("comma.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert df["Tid"].tolist() == [1, 2]


def test_read_sheet_blank_line_above_semicolon_header_keeps_row_numbering():
    content = b"\nTid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    df = parsing.read_sheet("semi.csv", content, parsing.CSV_SHEET_NAME, header_row=2)
    assert list(df.columns) == ["Tid", "Y", "X1", "X2"]
    assert df["Tid"].tolist() == [1, 2]


def test_detect_separator_semicolon_wins_when_every_column_has_decimal_commas():
    # Regression pin: a raw per-line occurrence TOTAL would wrongly pick ","
    # here, because a semicolon row with C columns has C-1 separators but
    # up to C decimal commas - if every column carries a decimal value, the
    # comma total (C per row) can outnumber the semicolon total (C-1 per
    # row) once summed over enough rows. Detection must instead use
    # per-line CONSISTENCY: ";" occurs exactly twice on every line
    # (including the header, which has no decimals), "," occurs 0 times on
    # the header and 3 times on every data row - so ";" scores 1.0 and ","
    # scores less than 1.0.
    n = 20
    lines = ["X1;X2;Y"]
    for i in range(1, n + 1):
        lines.append(f"{i},0;{i * 2},0;{i * 3},0")
    content = ("\n".join(lines) + "\n").encode()

    sample = parsing._sniff_sample(content)
    assert parsing._detect_separator(sample) == ";"

    df = parsing.read_sheet(
        "counterexample.csv", content, parsing.CSV_SHEET_NAME, header_row=1
    )
    assert list(df.columns) == ["X1", "X2", "Y"]
    assert df["Y"].dtype.kind in "if"
    assert df["Y"].iloc[0] == pytest.approx(3.0)


def test_read_raw_title_row_fallback_row_count_matches_physical_lines():
    # Pins the _count_csv_rows fallback: when the header=None counting
    # attempt can't tokenize a ragged preamble row, it must fall back to a
    # plain physical-line count, not raise or silently miscount.
    content = b"Rapport 2026\nTid;Y;X1;X2\n1;1.5;2.5;3.5\n2;2.5;3.5;4.5\n"
    physical_line_count = len(content.decode("utf-8").splitlines())
    assert parsing._read_raw("semi.csv", content, parsing.CSV_SHEET_NAME) == (
        physical_line_count
    )
