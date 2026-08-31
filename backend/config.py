"""Central configuration for tuning parameters.

All numeric constants used across the backend live here, per CLAUDE.md's
"tuning parameters live in one place" rule.
"""

# PLS analysis defaults
MAX_COMPONENTS_DEFAULT = 10
CV_FOLDS_DEFAULT = 10

# Minimum number of cross-validation folds; below this, KFold is meaningless.
MIN_CV_FOLDS = 2

# Minimum number of complete rows required to run an analysis
MIN_VALID_ROWS = 10

# identify_outliers: default threshold when none is supplied is Q3 + IQR_MULTIPLIER * IQR
OUTLIER_IQR_QUANTILE_LOW = 0.25
OUTLIER_IQR_QUANTILE_HIGH = 0.75
OUTLIER_IQR_MULTIPLIER = 1.5

# identify_low_impact_variables: default threshold when none is supplied is
# this fraction of the largest absolute coefficient
LOW_IMPACT_COEFFICIENT_FRACTION = 0.1

# T2 diagnostic: substituted for a component's variance when that variance is
# exactly zero, to avoid division by zero.
T2_ZERO_VARIANCE_EPSILON = 1e-10

# Upload constraints
MAX_UPLOAD_SIZE_MB = 20
ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".csv"}

# Preview
PREVIEW_ROW_COUNT = 20

# Row/column numbering: header_row/start_row/end_row/start_col/end_col are
# all 1-based Excel-style numbers, matching what users see in Excel.
DEFAULT_HEADER_ROW = 1

# Temp file lifetime (seconds) before an uploaded file is evicted from the
# in-memory/temp store.
UPLOAD_TTL_SECONDS = 3600

# optimize_variables: default absolute RMSEP tolerance allowed when testing
# whether a variable can be permanently excluded (0.0 = no tolerance).
OPTIMIZE_TOLERANCE_DEFAULT = 0.0

# optimize_variables is primarily bounded by the number of available
# X-variables minus one (the natural limit - you cannot remove more). This
# is a secondary safety net only, for pathologically large variable counts;
# hitting it is reported via stop_reason == "max_iterations", never silent.
MAX_OPTIMIZE_ITERATIONS = 50

# POST /api/report: downloaded filename is "<prefix>-<YYYY-MM-DD>.html".
REPORT_FILENAME_PREFIX = "pls-rapport"
