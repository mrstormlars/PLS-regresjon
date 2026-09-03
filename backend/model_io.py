"""Build/read the .plsmodel zip container (a manifest JSON, plus optional
raw data bytes), for POST /api/model/save and /api/model/load.

Stdlib only (zipfile, json, hashlib) - no pickle, per CLAUDE.md.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

from backend import config
from backend.parsing import ValidationError


def build_model_file(manifest: dict, data: tuple[str, bytes] | None) -> bytes:
    """Build the .plsmodel zip bytes: model.json plus an optional data/<name>."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(config.MODEL_MANIFEST_NAME, json.dumps(manifest))
        if data is not None:
            filename, content = data
            zf.writestr(f"{config.MODEL_DATA_DIR}{filename}", content)
    return buffer.getvalue()


def read_model_file(content: bytes) -> tuple[dict, tuple[str, bytes] | None]:
    """Parse a .plsmodel zip: return (manifest, (filename, content) | None).

    Raises ValidationError (Norwegian detail) for any structural problem:
    not a zip, missing/invalid model.json, wrong schema_version, manifest
    missing required keys, or a data member with a disallowed extension.
    The data member's uncompressed size is checked against
    config.MAX_UPLOAD_SIZE_MB from the zip's own info (before reading it),
    raising PayloadTooLargeError if it is exceeded.
    """
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as err:
        raise ValidationError("Filen er ikke en gyldig modellfil.") from err

    with zf:
        try:
            manifest_bytes = zf.read(config.MODEL_MANIFEST_NAME)
        except KeyError as err:
            raise ValidationError(
                "Modellfilen mangler model.json og er ugyldig."
            ) from err

        try:
            manifest = json.loads(manifest_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise ValidationError(
                "model.json i modellfilen er ikke gyldig JSON."
            ) from err

        if manifest.get("schema_version") != config.MODEL_SCHEMA_VERSION:
            raise ValidationError(
                "Modellfilen har en versjon som ikke støttes av denne appen."
            )
        if "settings" not in manifest or "result" not in manifest:
            raise ValidationError(
                "Modellfilen mangler innstillinger eller resultat og er ugyldig."
            )

        data_members = [
            info
            for info in zf.infolist()
            if info.filename.startswith(config.MODEL_DATA_DIR) and not info.is_dir()
        ]
        if not data_members:
            return manifest, None

        # Local import avoids a circular import at module load time
        # (parsing imports nothing from model_io, so this is only to keep
        # the PayloadTooLargeError check colocated with its use).
        from backend.parsing import PayloadTooLargeError, validate_upload

        info = data_members[0]
        data_filename = info.filename[len(config.MODEL_DATA_DIR) :]

        max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if info.file_size > max_bytes:
            raise PayloadTooLargeError(
                f"Rådataene i modellfilen er for store. Maksimal størrelse er "
                f"{config.MAX_UPLOAD_SIZE_MB} MB."
            )

        data_content = zf.read(info)
        validate_upload(data_filename, data_content)

        return manifest, (data_filename, data_content)
