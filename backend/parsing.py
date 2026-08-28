"""Excel/CSV ingestion, validation, and transient upload storage.

Uploaded files are kept only in memory (never written into the repo or to
disk under version control) and are evicted after config.UPLOAD_TTL_SECONDS.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from io import BytesIO
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


def read_sheet(
    filename: str, content: bytes, sheet: str, header_row: int
) -> pd.DataFrame:
    """Read a sheet (xlsx) or the csv content into a DataFrame.

    Raises ValidationError if the requested sheet does not exist.
    """
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        if sheet != CSV_SHEET_NAME:
            raise ValidationError(f"Ukjent ark: '{sheet}'.")
        return pd.read_csv(BytesIO(content), header=header_row)

    available_sheets = list_sheets(filename, content)
    if sheet not in available_sheets:
        raise ValidationError(f"Ukjent ark: '{sheet}'.")
    return pd.read_excel(BytesIO(content), sheet_name=sheet, header=header_row)


def extract_range(
    df: pd.DataFrame, start_row: int | None, end_row: int | None
) -> pd.DataFrame:
    """Slice a DataFrame to the given row range (0-indexed, inclusive), reset index."""
    start = start_row if start_row is not None else 0
    end = end_row if end_row is not None else len(df) - 1
    return df.iloc[start : end + 1].reset_index(drop=True)
