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
        "/api/preview", json={"file_id": file_id, "sheet": "Data1", "header_row": 0}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["Tid", "X1", "X2", "Y"]
    assert body["n_rows"] == 12
    assert len(body["rows"]) == 12


def test_preview_unknown_sheet_returns_400():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    response = client.post(
        "/api/preview",
        json={"file_id": file_id, "sheet": "IkkeEksisterendeArk", "header_row": 0},
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
            "header_row": 0,
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


def test_analyze_non_numeric_y_returns_400():
    csv_content = b"X1,X2,Y\n" + b"\n".join(
        f"{i},{i * 2},tekst{i}".encode() for i in range(1, 21)
    )
    file_id = _upload("text_y.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/analyze",
        json={"file_id": file_id, "sheet": "CSV", "header_row": 0, "y_col": "Y"},
    )
    assert response.status_code == 400


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
        json={"file_id": file_id, "sheet": "CSV", "header_row": 0, "y_col": "Y"},
    )
    assert response.status_code == 400
