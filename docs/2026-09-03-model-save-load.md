# Model save/load — contract and plan (2026-09-03)

Approved by user. Design summary: a saved model is a zip container holding
`model.json` (settings + `run_analysis` result + simulation + metadata) and,
optionally, the original uploaded file bytes under `data/`. No pickle. The
backend stays stateless; the file is downloaded to / uploaded from the user's
disk.

## Contract (what "done" means)

Verification scope: `pytest tests/`, `ruff check`, `ruff format --check`.

C1. `pytest tests/` green; `ruff check` and `ruff format --check` clean.
    Every new test < 5 s; new test file < 30 s.
C2. `backend/config.py` gains `MODEL_SCHEMA_VERSION`, `MODEL_FILENAME_PREFIX`
    (`"pls-modell"`), `MODEL_FILE_EXTENSION` (`".plsmodel"`),
    `MODEL_MANIFEST_NAME` (`"model.json"`), `MODEL_DATA_DIR` (`"data/"`).
    No other module hardcodes these strings.
C3. New module `backend/model_io.py` (stdlib `zipfile`, `json`, `hashlib`,
    `base64` NOT used, `pickle` NOT imported anywhere in `backend/`).
    Functions: `build_model_file(manifest: dict, data: tuple[str, bytes] | None) -> bytes`
    and `read_model_file(content: bytes) -> tuple[dict, tuple[str, bytes] | None]`.
C4. `POST /api/model/save` (JSON body: `settings`, `result`, `simulation`,
    `columns`, `include_data: bool`) returns `application/zip` with
    `Content-Disposition: attachment; filename="<prefix>-<YYYY-MM-DD><ext>"`.
    `settings` carries `file_id`, `file_name`, `sheet`, `header_row`,
    `start_row`, `end_row`, `start_col`, `end_col`, `y_col`, `excluded_cols`,
    `excluded_rows`, `limits`, `log_y`, `log_x_cols`, `max_components`,
    `cv_folds`. Manifest `model.json` contains `schema_version`, `created_at`,
    `source` (`file_name`, `sheet`, `header_row`, `start_row`, `end_row`,
    `start_col`, `end_col`, `data_sha256`, `data_embedded`), `columns`,
    `settings` (all fields above minus `file_id`/`file_name`), `result`,
    `simulation`.
    Negative: `include_data=true` with unknown/expired `file_id` → 400 with
    Norwegian detail. `result` lacking `coefficients` or `diagnostics` → 400.
    `include_data=false` → zip has no `data/` member, `data_embedded` false,
    `data_sha256` still set when `file_id` resolves, else null.
C5. `POST /api/model/load` (multipart `file`) returns JSON `{meta, columns,
    settings, result, simulation, file_id, sheets}`. With embedded data:
    `file_id` is a fresh upload id usable by `/api/preview` and
    `/api/analyze`, `sheets` non-empty, `settings.file_name` = original name.
    Without data: `file_id` null, `sheets` `[]`.
    Negatives (each 400, Norwegian detail): not a zip; zip without
    `model.json`; `model.json` not valid JSON; `schema_version` ≠
    `config.MODEL_SCHEMA_VERSION`; manifest missing `settings`/`result`;
    data member with disallowed extension. Data member whose uncompressed
    size (from zip info, checked BEFORE reading it) exceeds
    `config.MAX_UPLOAD_SIZE_MB` → 413. Model file itself over
    `config.MAX_UPLOAD_SIZE_MB` + manifest allowance → 413 (test via
    monkeypatch of `MAX_UPLOAD_SIZE_MB = 0`).
C6. Round-trip tests in new `tests/test_model_io.py`: (a) upload fixture →
    analyze → save with data → load → `settings`, `result`, `columns`,
    `simulation` equal the input; `/api/analyze` on the returned `file_id`
    with loaded settings reproduces `result["coefficients"]` within 1e-9.
    (b) save without data → load → `file_id` null, `result` equal.
    (c) `data_sha256` in manifest == sha256 of fixture bytes.
C7. Frontend: `index.html` gains `#save-model-button`, `#save-model-menu`
    with `#save-model-with-data-button` and `#save-model-without-data-button`,
    `#load-model-input` (file input, `accept` = extension), `#load-model-button`,
    `#load-model-status`, `#model-status` (all Norwegian labels: "Lagre modell",
    "Med rådata", "Uten rådata", "Åpne modell"). `tests/test_frontend_ids.py`
    still passes. Save buttons disabled until an analysis exists.
C8. Frontend load behaviour (`app.js`): with data → state.fileId/fileName/
    sheets set, sheet select + header/range inputs filled from settings,
    `/api/preview` called, column controls populated then synced to
    `excluded_cols`/`log_x_cols`/`limits`/`y_col`/`excluded_rows`/
    `max_components`/`cv_folds`, `state.lastAnalyzePayload` set,
    all views unlocked, `renderResults` called, simulation inputs restored
    and `runSimulate` invoked. Without data → same minus preview/file state;
    `analyze-button`, `rerun-*`, `optimize-button` disabled and
    `#model-status` shows Norwegian notice that raw data is absent; column
    controls populated from manifest `columns`. Saving uses the report
    download pattern.
C9. `README.md` gets a short Norwegian section on saving/opening models.
C10. Branch `feat/model-save-load`; nothing pushed to `main`. PR opened.

## Plan

1. `git checkout main && git pull && git checkout -b feat/model-save-load`.
2. `config.py`: add constants (C2).
3. `backend/model_io.py`: build/read zip; `read_model_file` validates
   structure and sizes, raises `ValidationError` / `PayloadTooLargeError`
   (import from `parsing`). Reuse `parsing.validate_upload` for the data
   member's extension/size after the zip-info size pre-check.
4. `app.py`: pydantic `ModelSettings` (extend `ReportSettings` with
   `file_id: str | None`, `y_col`), `SaveModelRequest`, save + load routes.
   Load: `read_model_file` → if data present `parsing.validate_upload` +
   `store_upload` + `list_sheets`. Mirror `/api/report` error handling.
5. Tests (C4–C6) in `tests/test_model_io.py`, using `sample.xlsx` fixture
   and `TestClient` like `test_app.py`.
6. Frontend: action-bar buttons; Data view card for open. `app.js`:
   `buildModelSettings()` (report settings + `file_id`, `y_col`),
   `saveModel(includeData)`, `applyLoadedModel(data)`; helper to set limit
   inputs/y-col/excluded-rows from settings. Enable save buttons in
   `renderResults` next to export button.
7. README section. Run scope, commit, push, open PR.
