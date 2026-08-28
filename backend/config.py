"""Central configuration for tuning parameters.

All numeric constants used across the backend live here, per CLAUDE.md's
"tuning parameters live in one place" rule.
"""

# PLS analysis defaults
MAX_COMPONENTS_DEFAULT = 10
CV_FOLDS_DEFAULT = 10

# Minimum number of complete rows required to run an analysis
MIN_VALID_ROWS = 10

# Upload constraints
MAX_UPLOAD_SIZE_MB = 20
ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".csv"}

# Preview
PREVIEW_ROW_COUNT = 20

# Temp file lifetime (seconds) before an uploaded file is evicted from the
# in-memory/temp store.
UPLOAD_TTL_SECONDS = 3600
