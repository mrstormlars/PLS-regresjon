"""End-to-end tests for the FastAPI endpoints: upload, preview, analyze."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend import config
from backend.app import app

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


def _upload(
    filename: str, content: bytes, content_type: str = "application/octet-stream"
):
    return client.post("/api/upload", files={"file": (filename, content, content_type)})


def test_upload_xlsx_returns_file_id_and_sheets():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    response = _upload("sample.xlsx", content)
    assert response.status_code == 200
    body = response.json()
    assert "file_id" in body
    assert body["sheets"] == ["Data1", "Data2"]


def test_upload_csv_returns_single_sheet():
    content = (FIXTURES / "sample.csv").read_bytes()
    response = _upload("sample.csv", content, content_type="text/csv")
    assert response.status_code == 200
    assert response.json()["sheets"] == ["CSV"]


def test_upload_rejects_txt_extension_with_norwegian_message():
    response = _upload("notes.txt", b"hello world")
    assert response.status_code == 400
    assert "filtype" in response.json()["detail"].lower()


def test_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 0)
    content = (FIXTURES / "sample.csv").read_bytes()
    response = _upload("sample.csv", content, content_type="text/csv")
    assert response.status_code == 413


def test_preview_returns_columns_and_rows():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview", json={"file_id": file_id, "sheet": "Data1", "header_row": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["Tid", "X1", "X2", "Y"]
    assert body["n_rows"] == 12
    assert len(body["rows"]) == 12


def test_preview_with_header_on_excel_row_three_returns_correct_first_row():
    content = (FIXTURES / "sample_header_row3.xlsx").read_bytes()
    file_id = _upload("sample_header_row3.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={"file_id": file_id, "sheet": "Data1", "header_row": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["Tid", "X1", "X2", "Y"]
    first_row = body["rows"][0]
    assert first_row["Tid"] == 1
    assert first_row["row_index"] == 4  # first data row is Excel row 4


def test_preview_header_row_zero_returns_400():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={"file_id": file_id, "sheet": "Data1", "header_row": 0},
    )
    assert response.status_code == 400
    assert "Excel-radnummer" in response.json()["detail"]


def test_preview_header_row_beyond_sheet_returns_400():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={"file_id": file_id, "sheet": "Data1", "header_row": 999},
    )
    assert response.status_code == 400
    assert "finnes ikke i arket" in response.json()["detail"]


def test_preview_column_range_returns_subset():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={
            "file_id": file_id,
            "sheet": "Data1",
            "header_row": 1,
            "start_col": 2,
            "end_col": 3,
        },
    )
    assert response.status_code == 200
    assert response.json()["columns"] == ["X1", "X2"]


def test_preview_start_col_after_end_col_returns_400():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={
            "file_id": file_id,
            "sheet": "Data1",
            "header_row": 1,
            "start_col": 3,
            "end_col": 2,
        },
    )
    assert response.status_code == 400
    assert "Startkolonne" in response.json()["detail"]


def test_preview_unknown_sheet_returns_400():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={"file_id": file_id, "sheet": "IkkeEksisterendeArk", "header_row": 1},
    )
    assert response.status_code == 400


def test_analyze_success_returns_expected_fields():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/analyze",
        json={
            "file_id": file_id,
            "sheet": "Data1",
            "header_row": 1,
            "y_col": "Y",
            "excluded_cols": ["Tid"],
            "max_components": 2,
            "cv_folds": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    for key in (
        "rmse_per_component",
        "optimal_components",
        "r2_cal",
        "r2_cv",
        "scores",
        "loadings",
        "coefficients",
        "diagnostics",
    ):
        assert key in body


def test_analyze_excluded_rows_use_excel_row_numbers():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    # Header on Excel row 1 -> data rows are Excel rows 2..13. Exclude row 2
    # (the first data row, Tid=1) and confirm it's absent from diagnostics.
    response = client.post(
        "/api/analyze",
        json={
            "file_id": file_id,
            "sheet": "Data1",
            "header_row": 1,
            "y_col": "Y",
            "excluded_cols": ["Tid"],
            "excluded_rows": [2],
            "max_components": 2,
            "cv_folds": 3,
        },
    )
    assert response.status_code == 200
    row_indices = [d["row_index"] for d in response.json()["diagnostics"]]
    assert 2 not in row_indices
    assert 3 in row_indices


def test_analyze_column_range_excludes_columns_outside_range():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/analyze",
        json={
            "file_id": file_id,
            "sheet": "Data1",
            "header_row": 1,
            "start_col": 2,
            "end_col": 4,
            "y_col": "Y",
            "max_components": 2,
            "cv_folds": 3,
        },
    )
    assert response.status_code == 200
    assert "Tid" not in response.json()["coefficients"]


def test_analyze_log_x_cols_transforms_before_standardization():
    csv_content = b"X1,Y\n" + b"\n".join(f"{10**i},{i}".encode() for i in range(1, 21))
    file_id = _upload("log_x.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/analyze",
        json={
            "file_id": file_id,
            "sheet": "CSV",
            "header_row": 1,
            "y_col": "Y",
            "log_x_cols": ["X1"],
            "max_components": 1,
            "cv_folds": 3,
        },
    )
    assert response.status_code == 200
    # log10(X1) == Y exactly, so a 1-component PLS fit should be near-perfect.
    assert response.json()["r2_cal"] > 0.99


def test_analyze_log_x_cols_all_non_positive_returns_400():
    n = config.MIN_VALID_ROWS
    csv_content = b"X1,Y\n" + b"\n".join(f"-1,{i}".encode() for i in range(1, n + 1))
    file_id = _upload("neg_x.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/analyze",
        json={
            "file_id": file_id,
            "sheet": "CSV",
            "header_row": 1,
            "y_col": "Y",
            "log_x_cols": ["X1"],
        },
    )
    assert response.status_code == 400
    assert "For få gyldige rader" in response.json()["detail"]


def test_analyze_non_numeric_y_returns_400():
    csv_content = b"X1,X2,Y\n" + b"\n".join(
        f"{i},{i * 2},tekst{i}".encode() for i in range(1, 21)
    )
    file_id = _upload("text_y.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/analyze",
        json={"file_id": file_id, "sheet": "CSV", "header_row": 1, "y_col": "Y"},
    )
    assert response.status_code == 400
    assert "ikke numeriske verdier" in response.json()["detail"]


def test_analyze_too_few_rows_returns_400():
    n = config.MIN_VALID_ROWS - 1
    csv_content = b"X1,Y\n" + b"\n".join(
        f"{i},{i * 2.0}".encode() for i in range(1, n + 1)
    )
    file_id = _upload("few_rows.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/analyze",
        json={"file_id": file_id, "sheet": "CSV", "header_row": 1, "y_col": "Y"},
    )
    assert response.status_code == 400
    assert "For få gyldige rader" in response.json()["detail"]
