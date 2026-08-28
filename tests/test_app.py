"""End-to-end tests for the FastAPI endpoints: upload, preview, analyze."""

from pathlib import Path

import numpy as np
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


def _optimize_csv_content():
    rng = np.random.default_rng(42)
    n = 60
    signal = rng.normal(size=n)
    noise_cols = {f"N{i + 1}": rng.normal(size=n) for i in range(4)}
    y = 5.0 * signal + rng.normal(scale=0.05, size=n)
    header = "Signal," + ",".join(noise_cols) + ",Y\n"
    lines = [header]
    for i in range(n):
        row = [signal[i]] + [noise_cols[col][i] for col in noise_cols] + [y[i]]
        lines.append(",".join(str(v) for v in row) + "\n")
    return "".join(lines).encode()


def test_optimize_removes_noise_variables_and_returns_expected_shape():
    content = _optimize_csv_content()
    file_id = _upload("optimize.csv", content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/optimize",
        json={
            "file_id": file_id,
            "sheet": "CSV",
            "header_row": 1,
            "y_col": "Y",
            "max_components": 3,
            "cv_folds": 5,
            "tolerance": 0.0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["final_excluded_cols"]
    assert set(body["final_excluded_cols"]).issubset({"N1", "N2", "N3", "N4"})
    assert body["history"]
    for entry in body["history"]:
        assert set(entry.keys()) == {"iteration", "removed_col", "rmsep"}
    assert "Signal" in body["results"]["coefficients"]
    assert body["stop_reason"] in {"converged", "too_few_variables", "max_iterations"}
    for key in ("rmse_per_component", "optimal_components", "r2_cal", "diagnostics"):
        assert key in body["results"]


def test_optimize_rejects_fewer_than_two_x_variables_returns_400():
    csv_content = b"X1,Y\n" + b"\n".join(
        f"{i},{i * 2.0}".encode() for i in range(1, 21)
    )
    file_id = _upload("one_x.csv", csv_content, content_type="text/csv").json()[
        "file_id"
    ]
    response = client.post(
        "/api/optimize",
        json={"file_id": file_id, "sheet": "CSV", "header_row": 1, "y_col": "Y"},
    )
    assert response.status_code == 400
    assert "minst 2 X-variabler" in response.json()["detail"]


def _diagnostics_payload():
    return [
        {"row_index": 1, "y_distance": 0.1, "X_distance": 0.1, "T2": 1.0},
        {"row_index": 2, "y_distance": 0.2, "X_distance": 0.2, "T2": 1.2},
        {"row_index": 3, "y_distance": 5.0, "X_distance": 0.3, "T2": 0.9},
        {"row_index": 4, "y_distance": 0.15, "X_distance": 6.0, "T2": 1.1},
        {"row_index": 5, "y_distance": 0.1, "X_distance": 0.1, "T2": 8.0},
    ]


def test_suggest_outliers_returns_row_indices_above_threshold():
    response = client.post(
        "/api/suggest-outliers",
        json={
            "diagnostics": _diagnostics_payload(),
            "method": "y_distance",
            "threshold": 1.0,
        },
    )
    assert response.status_code == 200
    assert response.json()["row_indices"] == [3]


def test_suggest_outliers_high_threshold_returns_empty_list():
    response = client.post(
        "/api/suggest-outliers",
        json={
            "diagnostics": _diagnostics_payload(),
            "method": "T2",
            "threshold": 100.0,
        },
    )
    assert response.status_code == 200
    assert response.json()["row_indices"] == []


def test_suggest_outliers_invalid_method_returns_400():
    response = client.post(
        "/api/suggest-outliers",
        json={"diagnostics": _diagnostics_payload(), "method": "bogus"},
    )
    assert response.status_code == 400
    assert "Ukjent metode" in response.json()["detail"]


def test_suggest_outliers_empty_diagnostics_returns_400():
    response = client.post(
        "/api/suggest-outliers", json={"diagnostics": [], "method": "y_distance"}
    )
    assert response.status_code == 400
    assert "tom" in response.json()["detail"].lower()


def _coefficients_payload():
    return [
        {"variable": "X1", "coefficient": 1.0},
        {"variable": "X2", "coefficient": 0.05},
        {"variable": "X3", "coefficient": 0.5},
    ]


def test_suggest_low_impact_returns_columns_below_threshold():
    response = client.post(
        "/api/suggest-low-impact",
        json={"coefficients": _coefficients_payload(), "threshold": 0.1},
    )
    assert response.status_code == 200
    assert response.json()["columns"] == ["X2"]


def test_suggest_low_impact_high_threshold_still_filters_by_value():
    # A threshold above every |coefficient| returns all of them, not an error.
    response = client.post(
        "/api/suggest-low-impact",
        json={"coefficients": _coefficients_payload(), "threshold": 100.0},
    )
    assert response.status_code == 200
    assert set(response.json()["columns"]) == {"X1", "X2", "X3"}
