"""FastAPI application: file upload, preview, PLS analysis, and static frontend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import analysis, config, parsing, report
from backend.parsing import PayloadTooLargeError, ValidationError

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="PLS-regresjon")


class PreviewRequest(BaseModel):
    file_id: str
    sheet: str
    header_row: int = config.DEFAULT_HEADER_ROW
    start_col: int | None = None
    end_col: int | None = None


class LimitBounds(BaseModel):
    low: float | None = None
    high: float | None = None


class AnalyzeRequest(BaseModel):
    file_id: str
    sheet: str
    header_row: int = config.DEFAULT_HEADER_ROW
    start_row: int | None = None
    end_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    y_col: str
    excluded_cols: list[str] = []
    excluded_rows: list[int] = []
    limits: dict[str, LimitBounds] = {}
    log_y: bool = False
    log_x_cols: list[str] = []
    max_components: int = config.MAX_COMPONENTS_DEFAULT
    cv_folds: int = config.CV_FOLDS_DEFAULT


class OptimizeRequest(AnalyzeRequest):
    tolerance: float = config.OPTIMIZE_TOLERANCE_DEFAULT


class DiagnosticEntry(BaseModel):
    row_index: int
    y_distance: float | None = None
    X_distance: float | None = None
    T2: float | None = None


class SuggestOutliersRequest(BaseModel):
    diagnostics: list[DiagnosticEntry]
    method: str = "y_distance"
    threshold: float | None = None


class CoefficientEntry(BaseModel):
    variable: str
    coefficient: float


class SuggestLowImpactRequest(BaseModel):
    coefficients: list[CoefficientEntry]
    threshold: float | None = None


class ReportSettings(BaseModel):
    file_name: str
    sheet: str
    header_row: int = config.DEFAULT_HEADER_ROW
    start_row: int | None = None
    end_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    limits: dict[str, LimitBounds] = {}
    log_y: bool = False
    log_x_cols: list[str] = []
    excluded_rows: list[int] = []
    excluded_cols: list[str] = []
    cv_folds: int = config.CV_FOLDS_DEFAULT
    max_components: int = config.MAX_COMPONENTS_DEFAULT


class ReportRequest(BaseModel):
    result: dict
    settings: ReportSettings


class SimulateChangeEntry(BaseModel):
    mode: str
    value: float


class SimulateRequest(BaseModel):
    intercept: float
    coefficients_raw: dict[str, float]
    x_means_raw: dict[str, float]
    log_y: bool = False
    log_x_cols: list[str] = []
    changes: dict[str, SimulateChangeEntry] = {}


def _sanitize_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-safe records (NaN/Inf -> None)."""
    clean = df.replace([np.inf, -np.inf], np.nan)
    return clean.astype(object).where(clean.notna(), None).to_dict(orient="records")


def _load_and_prepare(request: AnalyzeRequest) -> pd.DataFrame:
    """Load an uploaded file and apply sheet/column-range/row-range selection.

    Shared by /api/analyze and /api/optimize, which take the same file/range
    fields (OptimizeRequest extends AnalyzeRequest).
    """
    filename, content = parsing.get_upload(request.file_id)
    df = parsing.read_sheet(filename, content, request.sheet, request.header_row)
    df = parsing.select_columns(df, request.start_col, request.end_col)
    return parsing.extract_range(
        df, request.header_row, request.start_row, request.end_row
    )


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
        df = parsing.select_columns(df, request.start_col, request.end_col)
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    preview_df = df.head(config.PREVIEW_ROW_COUNT)
    first_excel_row = request.header_row + 1
    rows = _sanitize_records(preview_df)
    for position, row in enumerate(rows):
        row["row_index"] = first_excel_row + position

    return {
        "columns": [str(c) for c in df.columns],
        "n_rows": len(df),
        "rows": rows,
    }


@app.post("/api/analyze")
async def analyze_file(request: AnalyzeRequest):
    try:
        df = _load_and_prepare(request)
        limits = {col: bounds.model_dump() for col, bounds in request.limits.items()}
        result = analysis.run_analysis(
            df,
            y_col=request.y_col,
            excluded_cols=request.excluded_cols,
            excluded_rows=request.excluded_rows,
            limits=limits,
            log_y=request.log_y,
            log_x_cols=request.log_x_cols,
            max_components=request.max_components,
            cv_folds=request.cv_folds,
        )
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return result


@app.post("/api/optimize")
async def optimize_file(request: OptimizeRequest):
    try:
        df = _load_and_prepare(request)
        limits = {col: bounds.model_dump() for col, bounds in request.limits.items()}
        result = analysis.optimize_variables(
            df,
            y_col=request.y_col,
            excluded_cols=request.excluded_cols,
            excluded_rows=request.excluded_rows,
            limits=limits,
            log_y=request.log_y,
            log_x_cols=request.log_x_cols,
            max_components=request.max_components,
            cv_folds=request.cv_folds,
            tolerance=request.tolerance,
        )
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return result


@app.post("/api/suggest-outliers")
async def suggest_outliers(request: SuggestOutliersRequest):
    if not request.diagnostics:
        raise HTTPException(status_code=400, detail="Diagnostikklisten er tom.")

    records = [entry.model_dump() for entry in request.diagnostics]
    diagnostics_df = pd.DataFrame(records).rename(columns={"row_index": "RowIndex"})
    diagnostics_df["IsExcluded"] = 0

    try:
        row_indices = analysis.identify_outliers(
            diagnostics_df, method=request.method, threshold=request.threshold
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return {"row_indices": row_indices}


@app.post("/api/suggest-low-impact")
async def suggest_low_impact(request: SuggestLowImpactRequest):
    coef_df = pd.DataFrame(
        [
            {
                "VariableName": entry.variable,
                "Coefficient": entry.coefficient,
                "AbsCoefficient": abs(entry.coefficient),
            }
            for entry in request.coefficients
        ],
        columns=["VariableName", "Coefficient", "AbsCoefficient"],
    )
    coef_df["IsExcluded"] = 0

    columns = analysis.identify_low_impact_variables(
        coef_df, threshold=request.threshold
    )
    return {"columns": columns}


@app.post("/api/simulate")
async def simulate(request: SimulateRequest):
    changes = {var: change.model_dump() for var, change in request.changes.items()}
    try:
        result = analysis.simulate_change(
            intercept=request.intercept,
            coefficients_raw=request.coefficients_raw,
            x_means_raw=request.x_means_raw,
            log_y=request.log_y,
            log_x_cols=request.log_x_cols,
            changes=changes,
        )
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return result


@app.post("/api/report")
async def generate_report(request: ReportRequest):
    if (
        not request.result
        or "coefficients" not in request.result
        or "diagnostics" not in request.result
    ):
        raise HTTPException(
            status_code=400, detail="Analyseresultatet mangler eller er ufullstendig."
        )

    html_report = report.build_report_html(
        request.result, request.settings.model_dump()
    )
    filename = report.report_filename()
    return Response(
        content=html_report,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
