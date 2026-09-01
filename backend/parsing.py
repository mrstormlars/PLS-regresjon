"""Excel/CSV ingestion, validation, and transient upload storage.

Uploaded files are kept only in memory (never written into the repo or to
disk under version control) and are evicted after config.UPLOAD_TTL_SECONDS.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

from backend import config

CSV_SHEET_NAME = "CSV"


class ValidationError(Exception):
    """Raised for user-facing input errors (HTTP 400). Message is Norwegian."""


class PayloadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured size limit (HTTP 413)."""


@dataclass
class _StoredUpload:
    filename: str
    content: bytes
    created_at: float


_UPLOADS: dict[str, _StoredUpload] = {}


def _evict_expired() -> None:
    now = time.time()
    expired = [
        file_id
        for file_id, upload in _UPLOADS.items()
        if now - upload.created_at > config.UPLOAD_TTL_SECONDS
    ]
    for file_id in expired:
        del _UPLOADS[file_id]


def validate_upload(filename: str, content: bytes) -> None:
    """Validate extension and size of an uploaded file.

    Raises ValidationError (bad extension) or PayloadTooLargeError (too big).
    """
    extension = Path(filename).suffix.lower()
    if extension not in config.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError("Ugyldig filtype. Kun .xlsx og .csv-filer er støttet.")
    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise PayloadTooLargeError(
            f"Filen er for stor. Maksimal størrelse er {config.MAX_UPLOAD_SIZE_MB} MB."
        )


def store_upload(filename: str, content: bytes) -> str:
    """Store an already-validated upload in memory and return its file_id."""
    _evict_expired()
    file_id = str(uuid.uuid4())
    _UPLOADS[file_id] = _StoredUpload(
        filename=filename, content=content, created_at=time.time()
    )
    return file_id


def get_upload(file_id: str) -> tuple[str, bytes]:
    """Return (filename, content) for a stored upload.

    Raises ValidationError if the file_id is unknown or has expired.
    """
    _evict_expired()
    upload = _UPLOADS.get(file_id)
    if upload is None:
        raise ValidationError("Ukjent eller utløpt fil. Last opp filen på nytt.")
    return upload.filename, upload.content


def list_sheets(filename: str, content: bytes) -> list[str]:
    """Return sheet names for an xlsx file, or [CSV_SHEET_NAME] for csv."""
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        return [CSV_SHEET_NAME]
    workbook = pd.ExcelFile(BytesIO(content))
    return list(workbook.sheet_names)


def _sniff_sample(content: bytes) -> str:
    """Decode at most config.CSV_SNIFF_BYTES of content, dropping a
    possibly-truncated trailing line so the sample only contains whole rows.
    """
    raw = content[: config.CSV_SNIFF_BYTES]
    text = raw.decode("utf-8", errors="ignore")
    if len(content) > len(raw) and "\n" in text:
        text = text.rsplit("\n", 1)[0]
    return text


def _separator_consistency_score(sep: str, lines: list[str]) -> tuple[float, int]:
    """Score how consistently `sep` occurs across non-empty lines.

    A real delimiter appears the same number of times on every line (a
    decimal mark does not: it's absent from the header line and varies with
    how many values are non-integer). Returns (score, m) where m is the
    most common non-zero per-line count and score is the fraction of lines
    whose count equals m; (0, -1) if `sep` occurs on no line at all.
    """
    counts = [line.count(sep) for line in lines]
    nonzero_counts = [c for c in counts if c > 0]
    if not nonzero_counts:
        return 0.0, -1
    m = Counter(nonzero_counts).most_common(1)[0][0]
    score = counts.count(m) / len(lines)
    return score, m


def _detect_separator(sample: str) -> str:
    """Pick the candidate separator whose occurrence count is most
    consistent line-to-line (see _separator_consistency_score) - this is
    what distinguishes a real field separator from a decimal mark, which a
    raw occurrence count cannot. Ties break on higher m, then earlier
    position in config.CSV_CANDIDATE_SEPARATORS; falls back to the default
    if no candidate scores above 0.
    """
    lines = [line for line in sample.splitlines() if line.strip()]
    if not lines:
        return config.CSV_DEFAULT_SEPARATOR

    best_sep = None
    best_score = 0.0
    best_m = -1
    for sep in config.CSV_CANDIDATE_SEPARATORS:
        score, m = _separator_consistency_score(sep, lines)
        if score > best_score or (score == best_score and m > best_m):
            best_sep, best_score, best_m = sep, score, m

    return best_sep if best_sep is not None else config.CSV_DEFAULT_SEPARATOR


def _detect_decimal(sample: str, separator: str) -> str:
    """Choose the decimal mark for a `;`-separated sample by parsing the
    sample both ways and keeping whichever yields more numeric-dtype
    columns; ties (and any other separator) resolve to ".".
    """
    if separator != ";":
        return "."
    counts = {}
    for candidate in (",", "."):
        try:
            parsed = pd.read_csv(StringIO(sample), sep=separator, decimal=candidate)
        except (pd.errors.ParserError, ValueError):
            counts[candidate] = -1
            continue
        counts[candidate] = parsed.select_dtypes(include="number").shape[1]
    return "," if counts[","] > counts["."] else "."


def _detect_csv_dialect(content: bytes) -> tuple[str, str]:
    """Detect (separator, decimal) from the file content, per config."""
    sample = _sniff_sample(content)
    separator = _detect_separator(sample)
    decimal = _detect_decimal(sample, separator)
    return separator, decimal


def _count_csv_rows(content: bytes, separator: str, decimal: str) -> int:
    """Count the physical rows of CSV content, for header_row bounds-checking.

    Tries pd.read_csv(header=None) first, so a well-formed file's count
    matches the real parse's row semantics exactly (including a blank line
    counting as a row, via skip_blank_lines=False). A title/preamble row
    above the real header commonly has fewer fields than the data rows
    below it - a shape pd.read_csv(header=None) cannot tokenize without
    raising, even though the real, header-aware parse in read_sheet handles
    it fine (pandas doesn't require rows before an explicit header index to
    match its field count). Since this helper only needs a count, not the
    parsed columns, it falls back to a plain line count in that case rather
    than treating a preamble row as a fatal error.
    """
    try:
        return len(
            pd.read_csv(
                BytesIO(content),
                header=None,
                sep=separator,
                decimal=decimal,
                skip_blank_lines=False,
            )
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        return len(content.decode("utf-8", errors="ignore").splitlines())


def _parse_csv(
    content: bytes, header: int, separator: str, decimal: str
) -> pd.DataFrame:
    """Parse CSV content with the detected separator/decimal.

    Raises ValidationError (Norwegian message) if pandas cannot tokenize
    the content even with the detected separator/decimal (e.g. rows with
    inconsistent field counts) - never lets pandas.errors.ParserError
    surface to the caller as an unhandled 500.
    """
    try:
        return pd.read_csv(
            BytesIO(content),
            header=header,
            sep=separator,
            decimal=decimal,
            skip_blank_lines=False,
        )
    except pd.errors.ParserError as err:
        raise ValidationError(
            "Kunne ikke lese filen som CSV. Sjekk at alle radene har samme "
            "antall kolonner."
        ) from err


def _read_raw(filename: str, content: bytes, sheet: str) -> int:
    """Count the raw rows of a sheet/csv, with no header."""
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        separator, decimal = _detect_csv_dialect(content)
        return _count_csv_rows(content, separator, decimal)
    return len(pd.read_excel(BytesIO(content), sheet_name=sheet, header=None))


def read_sheet(
    filename: str, content: bytes, sheet: str, header_row: int
) -> pd.DataFrame:
    """Read a sheet (xlsx) or the csv content into a DataFrame.

    header_row is a 1-based Excel row number (row 1 is the first row of the
    sheet), matching what users see in Excel.

    Raises ValidationError if the requested sheet does not exist, or if
    header_row is not a valid row number within the sheet.
    """
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        if sheet != CSV_SHEET_NAME:
            raise ValidationError(f"Ukjent ark: '{sheet}'.")
    else:
        available_sheets = list_sheets(filename, content)
        if sheet not in available_sheets:
            raise ValidationError(f"Ukjent ark: '{sheet}'.")

    if header_row < 1:
        raise ValidationError("Header-rad må være et Excel-radnummer (1 eller høyere).")

    total_rows = _read_raw(filename, content, sheet)
    if header_row > total_rows:
        raise ValidationError(
            f"Header-rad {header_row} finnes ikke i arket (arket har kun "
            f"{total_rows} rader)."
        )

    pandas_header = header_row - 1
    if extension == ".csv":
        separator, decimal = _detect_csv_dialect(content)
        return _parse_csv(content, pandas_header, separator, decimal)
    return pd.read_excel(BytesIO(content), sheet_name=sheet, header=pandas_header)


def select_columns(
    df: pd.DataFrame, start_col: int | None, end_col: int | None
) -> pd.DataFrame:
    """Select a 1-based, inclusive column range (Excel-style: A=1, B=2, ...).

    Raises ValidationError if start_col is after end_col.
    """
    if start_col is None and end_col is None:
        return df
    n_cols = df.shape[1]
    start = start_col if start_col is not None else 1
    end = end_col if end_col is not None else n_cols
    if start > end:
        raise ValidationError("Startkolonne kan ikke være etter sluttkolonne.")
    start = max(start, 1)
    end = min(end, n_cols)
    return df.iloc[:, start - 1 : end]


def extract_range(
    df: pd.DataFrame, header_row: int, start_row: int | None, end_row: int | None
) -> pd.DataFrame:
    """Slice a DataFrame to the given row range.

    start_row/end_row are 1-based, inclusive Excel row numbers (matching
    header_row's numbering). The returned DataFrame's index is relabeled to
    the corresponding Excel row numbers, so downstream row_index values and
    excluded_rows stay in the same numbering the user sees in Excel.
    """
    first_data_row = header_row + 1
    last_data_row = header_row + len(df)

    start = max(start_row if start_row is not None else first_data_row, first_data_row)
    end = min(end_row if end_row is not None else last_data_row, last_data_row)

    if end < start:
        sliced = df.iloc[0:0].copy()
        sliced.index = range(0)
        return sliced

    position_start = start - first_data_row
    position_end = end - first_data_row
    sliced = df.iloc[position_start : position_end + 1].copy()
    sliced.index = range(start, start + len(sliced))
    return sliced
