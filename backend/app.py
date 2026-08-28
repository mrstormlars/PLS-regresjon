"""FastAPI application: file upload, preview, PLS analysis, and static frontend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import analysis, config, parsing
from backend.parsing import PayloadTooLargeError, ValidationError

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="PLS-regresjon")


class PreviewRequest(BaseModel):
    file_id: str
    sheet: str
    header_row: int = 0


class LimitBounds(BaseModel):
    low: float | None = None
    high: float | None = None


class AnalyzeRequest(BaseModel):
    file_id: str
    sheet: str
    header_row: int = 0
    start_row: int | None = None
    end_row: int | None = None
    y_col: str
    excluded_cols: list[str] = []
    excluded_rows: list[int] = []
    limits: dict[str, LimitBounds] = {}
    log_y: bool = False
    max_components: int = config.MAX_COMPONENTS_DEFAULT
    cv_folds: int = config.CV_FOLDS_DEFAULT


def _sanitize_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-safe records (NaN/Inf -> None)."""
    clean = df.replace([np.inf, -np.inf], np.nan)
    return clean.astype(object).where(clean.notna(), None).to_dict(orient="records")


@app.post("/api/upload")
async def upload_file(file: UploadFile):
    content = await file.read()
    try:
        parsing.validate_upload(file.filename, content)
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except PayloadTooLargeError as err:
        raise HTTPException(status_code=413, detail=str(err)) from err

    file_id = parsing.store_upload(file.filename, content)
    sheets = parsing.list_sheets(file.filename, content)
    return {"file_id": file_id, "sheets": sheets}


@app.post("/api/preview")
async def preview_file(request: PreviewRequest):
    try:
        filename, content = parsing.get_upload(request.file_id)
        df = parsing.read_sheet(filename, content, request.sheet, request.header_row)
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    preview_df = df.head(config.PREVIEW_ROW_COUNT)
    return {
        "columns": [str(c) for c in df.columns],
        "n_rows": len(df),
        "rows": _sanitize_records(preview_df),
    }


@app.post("/api/analyze")
async def analyze_file(request: AnalyzeRequest):
    try:
        filename, content = parsing.get_upload(request.file_id)
        df = parsing.read_sheet(filename, content, request.sheet, request.header_row)
        df = parsing.extract_range(df, request.start_row, request.end_row)
        limits = {col: bounds.model_dump() for col, bounds in request.limits.items()}
        result = analysis.run_analysis(
            df,
            y_col=request.y_col,
            excluded_cols=request.excluded_cols,
            excluded_rows=request.excluded_rows,
            limits=limits,
            log_y=request.log_y,
            max_components=request.max_components,
            cv_folds=request.cv_folds,
        )
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return result


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
