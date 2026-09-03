"""FastAPI application: file upload, preview, PLS analysis, and static frontend."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import analysis, config, model_io, parsing, report
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


class SimulateChangeEntry(BaseModel):
    mode: str
    value: float


class SimulationPayload(BaseModel):
    """The last /api/simulate state, as held by the frontend at export time."""

    changes: dict[str, SimulateChangeEntry] = {}
    y_base: float
    y_new: float
    delta: float
    delta_percent: float


class ReportRequest(BaseModel):
    result: dict
    settings: ReportSettings
    simulation: SimulationPayload | None = None


class ModelSettings(BaseModel):
    """The full run settings needed to save/restore an analysis. Extends
    ReportSettings' range/preprocessing fields with the identifiers
    (file_id, file_name) and y_col needed to reproduce the run."""

    file_id: str | None = None
    file_name: str
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


class SaveModelRequest(BaseModel):
    settings: ModelSettings
    result: dict
    simulation: SimulationPayload | None = None
    columns: list[str] = []
    include_data: bool = False


class SimulateRequest(BaseModel):
    intercept: float
    coefficients_raw: dict[str, float]
    x_means_raw: dict[str, float]
    log_y: bool = False
    x_var_bases: dict[str, str] = {}
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
            x_var_bases=request.x_var_bases,
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

    simulation = request.simulation.model_dump() if request.simulation else None
    html_report = report.build_report_html(
        request.result, request.settings.model_dump(), simulation
    )
    filename = report.report_filename()
    return Response(
        content=html_report,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/model/save")
async def save_model(request: SaveModelRequest):
    if (
        not request.result
        or "coefficients" not in request.result
        or "diagnostics" not in request.result
    ):
        raise HTTPException(
            status_code=400, detail="Analyseresultatet mangler eller er ufullstendig."
        )

    settings = request.settings
    data_sha256 = None
    data_tuple = None

    if settings.file_id:
        try:
            filename, content = parsing.get_upload(settings.file_id)
        except ValidationError as err:
            if request.include_data:
                raise HTTPException(status_code=400, detail=str(err)) from err
        else:
            data_sha256 = hashlib.sha256(content).hexdigest()
            if request.include_data:
                data_tuple = (filename, content)
    elif request.include_data:
        raise HTTPException(
            status_code=400,
            detail="Ingen fil er lastet opp; kan ikke lagre modellen med rådata.",
        )

    settings_dict = settings.model_dump(exclude={"file_id", "file_name"})
    manifest = {
        "schema_version": config.MODEL_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source": {
            "file_name": settings.file_name,
            "sheet": settings.sheet,
            "header_row": settings.header_row,
            "start_row": settings.start_row,
            "end_row": settings.end_row,
            "start_col": settings.start_col,
            "end_col": settings.end_col,
            "data_sha256": data_sha256,
            "data_embedded": data_tuple is not None,
        },
        "columns": request.columns,
        "settings": settings_dict,
        "result": request.result,
        "simulation": request.simulation.model_dump() if request.simulation else None,
    }

    model_bytes = model_io.build_model_file(manifest, data_tuple)
    filename = (
        f"{config.MODEL_FILENAME_PREFIX}-{datetime.now(UTC).date().isoformat()}"
        f"{config.MODEL_FILE_EXTENSION}"
    )
    return Response(
        content=model_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/model/load")
async def load_model(file: UploadFile):
    content = await file.read()
    max_total_bytes = (
        (config.MAX_UPLOAD_SIZE_MB + config.MODEL_MANIFEST_ALLOWANCE_MB) * 1024 * 1024
    )
    if len(content) > max_total_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Modellfilen er for stor. Maksimal størrelse er "
            f"{config.MAX_UPLOAD_SIZE_MB + config.MODEL_MANIFEST_ALLOWANCE_MB} MB.",
        )

    try:
        manifest, data = model_io.read_model_file(content)
    except ValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except PayloadTooLargeError as err:
        raise HTTPException(status_code=413, detail=str(err)) from err

    file_id = None
    sheets: list[str] = []
    if data is not None:
        data_filename, data_content = data
        file_id = parsing.store_upload(data_filename, data_content)
        sheets = parsing.list_sheets(data_filename, data_content)

    settings = dict(manifest.get("settings") or {})
    settings["file_id"] = file_id
    settings["file_name"] = (manifest.get("source") or {}).get("file_name")

    return {
        "meta": {
            "schema_version": manifest.get("schema_version"),
            "created_at": manifest.get("created_at"),
            "source": manifest.get("source"),
        },
        "columns": manifest.get("columns", []),
        "settings": settings,
        "result": manifest.get("result"),
        "simulation": manifest.get("simulation"),
        "file_id": file_id,
        "sheets": sheets,
    }


class RevalidatingStaticFiles(StaticFiles):
    """StaticFiles that forces revalidation instead of heuristic caching.

    Without an explicit Cache-Control, browsers may reuse a stored copy of
    a frontend file (app.js, vendor bundles) without checking the server
    first, so a deployed change can appear "missing". "no-cache" (not
    "no-store") keeps the ETag/304 path intact, so the 4.5 MB vendored
    frontend/vendor/plotly.min.js is still not re-downloaded on every load.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "no-cache"
        return response


app.mount(
    "/", RevalidatingStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend"
)
