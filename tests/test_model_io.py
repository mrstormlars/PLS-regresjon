"""Round-trip and negative-case tests for POST /api/model/save and
POST /api/model/load, and the underlying backend/model_io.py."""

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from backend import config
from backend.app import app

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


def _upload(filename: str, content: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/upload", files={"file": (filename, content, content_type)})


def _analyze(file_id: str):
    return client.post(
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


def _base_settings(file_id: str) -> dict:
    return {
        "file_id": file_id,
        "file_name": "sample.xlsx",
        "sheet": "Data1",
        "header_row": 1,
        "y_col": "Y",
        "excluded_cols": ["Tid"],
        "max_components": 2,
        "cv_folds": 3,
    }


def test_round_trip_with_data():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    result = _analyze(file_id).json()

    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings(file_id),
            "result": result,
            "columns": ["Tid", "X1", "X2", "Y"],
            "include_data": True,
        },
    )
    assert save_response.status_code == 200
    assert save_response.headers["content-type"] == "application/zip"

    load_response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", save_response.content, "application/zip")},
    )
    assert load_response.status_code == 200
    body = load_response.json()

    assert body["settings"]["sheet"] == "Data1"
    assert body["settings"]["y_col"] == "Y"
    assert body["settings"]["file_name"] == "sample.xlsx"
    assert body["result"]["coefficients"] == result["coefficients"]
    assert body["columns"] == ["Tid", "X1", "X2", "Y"]
    assert body["simulation"] is None
    assert body["file_id"]
    assert body["sheets"] == ["Data1", "Data2"]

    # /api/analyze on the returned file_id with the loaded settings
    # reproduces the original coefficients within 1e-9.
    reanalyze = client.post(
        "/api/analyze",
        json={
            "file_id": body["file_id"],
            "sheet": body["settings"]["sheet"],
            "header_row": body["settings"]["header_row"],
            "y_col": body["settings"]["y_col"],
            "excluded_cols": body["settings"]["excluded_cols"],
            "max_components": body["settings"]["max_components"],
            "cv_folds": body["settings"]["cv_folds"],
        },
    )
    assert reanalyze.status_code == 200
    reanalyzed_coefficients = reanalyze.json()["coefficients"]
    for key, value in result["coefficients"].items():
        assert abs(reanalyzed_coefficients[key] - value) < 1e-9


def test_round_trip_without_data():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    result = _analyze(file_id).json()

    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings(file_id),
            "result": result,
            "columns": ["Tid", "X1", "X2", "Y"],
            "include_data": False,
        },
    )
    assert save_response.status_code == 200

    load_response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", save_response.content, "application/zip")},
    )
    assert load_response.status_code == 200
    body = load_response.json()
    assert body["file_id"] is None
    assert body["sheets"] == []
    assert body["result"]["coefficients"] == result["coefficients"]


def test_data_sha256_matches_fixture_bytes():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    result = _analyze(file_id).json()

    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings(file_id),
            "result": result,
            "columns": ["Tid", "X1", "X2", "Y"],
            "include_data": False,
        },
    )
    assert save_response.status_code == 200

    load_response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", save_response.content, "application/zip")},
    )
    manifest_sha256 = load_response.json()["meta"]["source"]["data_sha256"]
    assert manifest_sha256 == hashlib.sha256(content).hexdigest()


def test_save_without_data_has_no_data_member_and_data_embedded_false():
    content = (FIXTURES / "sample.xlsx").read_bytes()
    file_id = _upload("sample.xlsx", content).json()["file_id"]
    result = _analyze(file_id).json()

    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings(file_id),
            "result": result,
            "columns": ["Tid", "X1", "X2", "Y"],
            "include_data": False,
        },
    )
    assert save_response.status_code == 200

    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(save_response.content)) as zf:
        assert not any(name.startswith("data/") for name in zf.namelist())

    load_response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", save_response.content, "application/zip")},
    )
    assert load_response.json()["meta"]["source"]["data_embedded"] is False


def test_save_with_data_and_unknown_file_id_returns_400():
    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings("unknown-file-id"),
            "result": {"coefficients": {"X1": 1.0}, "diagnostics": []},
            "columns": ["X1"],
            "include_data": True,
        },
    )
    assert save_response.status_code == 400
    assert "Ukjent eller utløpt fil" in save_response.json()["detail"]


def test_save_without_coefficients_returns_400():
    save_response = client.post(
        "/api/model/save",
        json={
            "settings": _base_settings("some-file-id"),
            "result": {"diagnostics": []},
            "columns": [],
            "include_data": False,
        },
    )
    assert save_response.status_code == 400


def test_load_not_a_zip_returns_400():
    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", b"not a zip file", "application/zip")},
    )
    assert response.status_code == 400
    assert "gyldig modellfil" in response.json()["detail"]


def test_load_zip_without_manifest_returns_400():
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("other.txt", "hello")

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "model.json" in response.json()["detail"]


def test_load_invalid_json_manifest_returns_400():
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(config.MODEL_MANIFEST_NAME, "{not valid json")

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "JSON" in response.json()["detail"]


def test_load_wrong_schema_version_returns_400():
    import json
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            config.MODEL_MANIFEST_NAME,
            json.dumps({"schema_version": 999, "settings": {}, "result": {}}),
        )

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "versjon" in response.json()["detail"]


def test_load_manifest_missing_settings_returns_400():
    import json
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            config.MODEL_MANIFEST_NAME,
            json.dumps({"schema_version": config.MODEL_SCHEMA_VERSION, "result": {}}),
        )

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "innstillinger" in response.json()["detail"]


def test_load_data_member_with_disallowed_extension_returns_400():
    import json
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            config.MODEL_MANIFEST_NAME,
            json.dumps(
                {
                    "schema_version": config.MODEL_SCHEMA_VERSION,
                    "settings": {},
                    "result": {},
                }
            ),
        )
        zf.writestr(f"{config.MODEL_DATA_DIR}data.txt", "not allowed")

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "filtype" in response.json()["detail"].lower()


def test_load_data_member_oversized_returns_413(monkeypatch):
    import json
    import zipfile
    from io import BytesIO

    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 0)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            config.MODEL_MANIFEST_NAME,
            json.dumps(
                {
                    "schema_version": config.MODEL_SCHEMA_VERSION,
                    "settings": {},
                    "result": {},
                }
            ),
        )
        zf.writestr(f"{config.MODEL_DATA_DIR}data.csv", "a,b\n1,2\n")

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 413


def test_load_whole_model_file_oversized_returns_413(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 0)

    response = client.post(
        "/api/model/load",
        files={"file": ("model.plsmodel", b"x" * 2_000_000, "application/zip")},
    )
    assert response.status_code == 413
