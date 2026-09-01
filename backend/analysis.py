"""PLS regression fitting and diagnostics.

Ported from the reference notebook (Inbox/PLS-regresjon.ipynb, cell 6), with
Spark/Historian/Lakehouse/Fabric-export/MLflow/plotly-export code removed and
print-based logging replaced by returned data structures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict

from backend import config
from backend.parsing import ValidationError


def normalize_data(
    df: pd.DataFrame, exclude_columns: list[str] | str | None = None
) -> pd.DataFrame:
    """Z-score normalize all numeric columns, except those in exclude_columns.

    Columns with zero (or undefined) standard deviation are left unchanged.
    """
    if exclude_columns is None:
        exclude = []
    elif isinstance(exclude_columns, str):
        exclude = [exclude_columns]
    else:
        exclude = list(exclude_columns)

    candidates = list(df.select_dtypes(include=["number"]).columns) + [
        c
        for c in df.select_dtypes(include=["object"]).columns
        if pd.to_numeric(df[c], errors="coerce").notna().all()
    ]
    cols = [c for c in candidates if c not in exclude]

    df_norm = df.copy()
    for col in cols:
        series = pd.to_numeric(df_norm[col], errors="coerce").astype(float)
        mean, std = series.mean(), series.std()
        if std == 0 or pd.isna(std):
            continue
        df_norm[col] = (series - mean) / std

    return df_norm


def identify_outliers(
    diagnostics_df: pd.DataFrame,
    method: str = "y_distance",
    threshold: float | None = None,
) -> list[int]:
    """Identify outlier row indices from a diagnostics DataFrame.

    Args:
        diagnostics_df: DataFrame with columns IsExcluded, RowIndex, and one
            of y_distance / X_distance / T2.
        method: 'y_distance', 'X_distance', or 'T2'.
        threshold: Cutoff value (rows strictly above are outliers). If None,
            uses Q3 + config.OUTLIER_IQR_MULTIPLIER * IQR.

    Returns:
        List of row indices whose diagnostic value exceeds the threshold.
    """
    included_df = diagnostics_df[diagnostics_df["IsExcluded"] == 0]

    if method not in ("y_distance", "X_distance", "T2"):
        raise ValueError(
            f"Ukjent metode: {method}. Bruk 'y_distance', 'X_distance', eller 'T2'."
        )
    values = included_df[method]

    if threshold is None:
        q1 = values.quantile(config.OUTLIER_IQR_QUANTILE_LOW)
        q3 = values.quantile(config.OUTLIER_IQR_QUANTILE_HIGH)
        iqr = q3 - q1
        threshold = q3 + config.OUTLIER_IQR_MULTIPLIER * iqr

    outliers = included_df[values > threshold]
    return outliers["RowIndex"].tolist()


def identify_low_impact_variables(
    coef_df: pd.DataFrame, threshold: float | None = None
) -> list[str]:
    """Identify variable names with low-impact coefficients.

    Args:
        coef_df: DataFrame with columns IsExcluded, VariableName, AbsCoefficient.
        threshold: Absolute-coefficient cutoff. If None, uses
            config.LOW_IMPACT_COEFFICIENT_FRACTION of the max.

    Returns:
        List of variable names whose |coefficient| is below the threshold.
    """
    included_df = coef_df[coef_df["IsExcluded"] == 0]

    if threshold is None:
        max_abs_coef = included_df["AbsCoefficient"].max()
        threshold = config.LOW_IMPACT_COEFFICIENT_FRACTION * max_abs_coef

    low_impact = included_df[included_df["AbsCoefficient"] < threshold]
    return low_impact["VariableName"].tolist()


def _apply_limits(
    df: pd.DataFrame, limits: dict[str, dict[str, float]]
) -> pd.DataFrame:
    """Drop rows where a limited column's value is below low or above high."""
    if not limits:
        return df
    mask = pd.Series(True, index=df.index)
    for col, bounds in limits.items():
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        low = bounds.get("low")
        high = bounds.get("high")
        if low is not None:
            mask &= ~(series < low)
        if high is not None:
            mask &= ~(series > high)
    return df[mask]


def _standardization_params(series: pd.Series) -> tuple[float, float]:
    """Mean/std that normalize_data would use to z-score this column.

    normalize_data leaves a zero-(or undefined-)variance column completely
    unscaled (not even mean-centered), which is equivalent to using mean=0,
    std=1 in the standardization formula.
    """
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return 0.0, 1.0
    return float(mean), float(std)


def _compute_raw_coefficients(
    X: pd.DataFrame, y: pd.Series, coefficients: dict[str, float]
) -> tuple[dict[str, float], float]:
    """Back-scale standardized-model coefficients to the raw variable scale.

    "Raw" here means post-log10 (for log-selected columns) but
    pre-standardization - the values the user actually sees after any log
    transform, before the z-score step.

    Derivation: with x_norm_j = (x_raw_j - mean_x_j) / std_x_j and
    y_norm = (y_raw - mean_y) / std_y, the standardized-space model is
    y_norm_pred = sum_j(b_std_j * x_norm_j) - with NO intercept term, since
    the final model is fit on X_norm/y_norm which are both exactly
    mean-centered over the same rows used to fit it, so the fitted
    hyperplane passes through the origin. Substituting and rearranging
    into y_raw_pred = intercept + sum_j(b_raw_j * x_raw_j) gives:
        b_raw_j = b_std_j * std_y / std_x_j
        intercept = mean_y - sum_j(b_raw_j * mean_x_j)
    """
    y_mean, y_std = _standardization_params(y)
    coefficients_raw: dict[str, float] = {}
    x_means: dict[str, float] = {}
    for col, b_std in coefficients.items():
        x_mean, x_std = _standardization_params(X[col])
        coefficients_raw[col] = b_std * y_std / x_std
        x_means[col] = x_mean
    intercept = y_mean - sum(
        coefficients_raw[col] * x_means[col] for col in coefficients_raw
    )
    return coefficients_raw, float(intercept)


def _base_name_from_model_var(model_var: str) -> str:
    """Recover the base column name from a log10-derived model variable name
    (inverts config.LOG_COLUMN_NAME_FORMAT, e.g. "log10(X1)" -> "X1").

    Returns model_var unchanged if it doesn't match that format (a linear
    term's model_var already IS the base name).
    """
    prefix, _, suffix = config.LOG_COLUMN_NAME_FORMAT.partition("{col}")
    if (
        model_var.startswith(prefix)
        and model_var.endswith(suffix)
        and len(model_var) >= len(prefix) + len(suffix)
    ):
        return model_var[len(prefix) : len(model_var) - len(suffix)]
    return model_var


def build_model_variables(
    all_cols: list[str],
    y_col: str,
    excluded_cols: list[str],
    log_x_cols: list[str],
) -> list[tuple[str, str, bool]]:
    """Compose the ordered list of model variables from base columns.

    Each base column (iterated in original frame order, skipping y_col)
    independently contributes a linear term if it is not excluded, and/or a
    log10 term if it is log-selected - so a column can produce a linear
    term, a log term, both, or neither. Returns (model_name, base_name,
    is_log) tuples; a log term's model_name is
    config.LOG_COLUMN_NAME_FORMAT.format(col=base_name).

    Raises ValidationError (Norwegian message) if a derived log10 model name
    collides with an existing column in all_cols.
    """
    excluded = set(excluded_cols)
    log_selected = set(log_x_cols)
    existing = set(all_cols)
    model_vars: list[tuple[str, str, bool]] = []
    for col in all_cols:
        if col == y_col:
            continue
        if col not in excluded:
            model_vars.append((col, col, False))
        if col in log_selected:
            log_name = config.LOG_COLUMN_NAME_FORMAT.format(col=col)
            if log_name in existing:
                raise ValidationError(
                    f"Variabelnavnet '{log_name}' er i konflikt med en "
                    f"eksisterende kolonne i datasettet."
                )
            model_vars.append((log_name, col, True))
    return model_vars


def _model_input(var: str, x_raw: float, log_model_cols: set[str]) -> float:
    """Convert a raw (original-units) x value to what the raw-scale model
    coefficients expect: log10(x) for a log-derived model variable, x
    unchanged otherwise.

    Raises ValidationError (Norwegian message), naming the BASE variable
    (not the derived model-variable name - that is the name the user typed
    into the simulation table), if a log-derived variable's value is not
    strictly positive.
    """
    if var in log_model_cols:
        if x_raw <= 0:
            base = _base_name_from_model_var(var)
            raise ValidationError(
                f"Verdien for '{base}' må være positiv når logaritmisk skala er "
                f"valgt (fikk {x_raw:.4g})."
            )
        return float(np.log10(x_raw))
    return float(x_raw)


def _predict_raw(
    intercept: float,
    coefficients_raw: dict[str, float],
    x_values_raw: dict[str, float],
    log_model_cols: set[str],
    log_y: bool,
) -> float:
    """Predict y in original units from x values in original (pre-log10) units."""
    y_model_scale = intercept
    for var, coef in coefficients_raw.items():
        y_model_scale += coef * _model_input(var, x_values_raw[var], log_model_cols)
    return float(10**y_model_scale) if log_y else float(y_model_scale)


def _compute_t2(T: np.ndarray) -> np.ndarray:
    """Compute Hotelling's T2 statistic per row from a PLS score matrix.

    A component with zero (sample) variance across rows would otherwise cause
    a division by zero; such components are guarded by substituting
    config.T2_ZERO_VARIANCE_EPSILON for their variance.
    """
    component_var = np.var(T, axis=0, ddof=1)
    component_var = np.where(
        component_var == 0, config.T2_ZERO_VARIANCE_EPSILON, component_var
    )
    return np.sum((T**2) / component_var, axis=1)


def run_analysis(
    df: pd.DataFrame,
    y_col: str,
    excluded_cols: list[str] | None = None,
    excluded_rows: list[int] | None = None,
    limits: dict[str, dict[str, float]] | None = None,
    log_y: bool = False,
    log_x_cols: list[str] | None = None,
    max_components: int = config.MAX_COMPONENTS_DEFAULT,
    cv_folds: int = config.CV_FOLDS_DEFAULT,
) -> dict:
    """Run the full PLS analysis pipeline on an already range-extracted DataFrame.

    Pipeline: drop excluded rows -> compose model variables (see
    build_model_variables: each base column independently contributes a
    linear term if included and/or a log10 term if log-selected) -> drop
    base columns that contribute neither -> limit filter (on base columns)
    -> optional log10(Y) and log10(selected model variables) -> coerce
    numeric, inf -> NaN, drop incomplete rows -> standardize (mean/std) ->
    PLS sweep 1..max_components with KFold CV -> pick optimal component
    count by minimum RMSEP -> fit optimal model -> diagnostics.

    Non-positive values in a log10'd column become NaN and are dropped by
    the existing incomplete-row handling; if that pushes the valid row count
    below config.MIN_VALID_ROWS, the existing ValidationError below applies.

    Raises ValidationError (Norwegian message) if Y is not numeric, if a
    derived log10 variable name collides with an existing column, or if
    fewer than config.MIN_VALID_ROWS complete rows remain.
    """
    excluded_cols = excluded_cols or []
    excluded_rows = excluded_rows or []
    limits = limits or {}
    log_x_cols = log_x_cols or []

    if y_col not in df.columns:
        raise ValidationError(f"Kolonnen '{y_col}' finnes ikke i datasettet.")

    working = df.drop(index=[r for r in excluded_rows if r in df.index])

    model_vars = build_model_variables(
        list(working.columns), y_col, excluded_cols, log_x_cols
    )
    base_cols_needed = {base for _, base, _ in model_vars}
    working = working[
        [c for c in working.columns if c in base_cols_needed or c == y_col]
    ]

    working = _apply_limits(working, limits)

    y_numeric = pd.to_numeric(working[y_col], errors="coerce")
    if y_numeric.notna().sum() == 0:
        raise ValidationError(f"Kolonnen '{y_col}' inneholder ikke numeriske verdier.")

    if log_y:
        with np.errstate(divide="ignore", invalid="ignore"):
            y_numeric = np.log10(y_numeric)

    base_frame = working[list(base_cols_needed)].apply(pd.to_numeric, errors="coerce")

    x_cols = [name for name, _, _ in model_vars]  # model-variable order
    log_model_cols = {name for name, _, is_log in model_vars if is_log}
    X = pd.DataFrame(index=working.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        for name, base, is_log in model_vars:
            X[name] = np.log10(base_frame[base]) if is_log else base_frame[base]
    X = X.replace([np.inf, -np.inf], np.nan)
    y = y_numeric.replace([np.inf, -np.inf], np.nan)

    valid_mask = X.notna().all(axis=1) & y.notna()

    # Missing/invalid-value visibility: counted among the rows that entered
    # this complete-case filter, i.e. before it drops anything. A cell is
    # "invalid" here if it's NaN after numeric coercion, inf, or NaN from a
    # failed log10 (non-positive value in a log-derived model variable). A
    # failed log10 shows up under the derived model-variable name.
    n_rows_dropped_missing = int((~valid_mask).sum())
    missing_by_column: dict[str, int] = {}
    for col in x_cols:
        count = int(X[col].isna().sum())
        if count > 0:
            missing_by_column[col] = count
    y_missing_count = int(y.isna().sum())
    if y_missing_count > 0:
        missing_by_column[y_col] = y_missing_count

    X = X.loc[valid_mask]
    y = y.loc[valid_mask]
    base_frame = base_frame.loc[valid_mask]

    if len(y) < config.MIN_VALID_ROWS:
        raise ValidationError(
            f"For få gyldige rader etter filtrering (minimum {config.MIN_VALID_ROWS})."
        )

    n_rows, n_vars = X.shape
    max_components = max(1, min(max_components, n_vars, n_rows - 1))
    actual_cv = max(config.MIN_CV_FOLDS, min(cv_folds, n_rows))

    combined = X.copy()
    combined[y_col] = y
    combined_norm = normalize_data(combined)
    X_norm = combined_norm[x_cols]
    y_norm = combined_norm[y_col]

    components = list(range(1, max_components + 1))
    rmsep_values: list[float] = []
    rmsec_values: list[float] = []
    cv_predictions: list[np.ndarray] = []

    kfold = KFold(n_splits=actual_cv)
    for n_comp in components:
        model = PLSRegression(n_components=n_comp)
        y_cv_pred = cross_val_predict(model, X_norm, y_norm, cv=kfold)
        rmsep = float(np.sqrt(mean_squared_error(y_norm, y_cv_pred)))

        model.fit(X_norm, y_norm)
        y_cal_pred = model.predict(X_norm).ravel()
        rmsec = float(np.sqrt(mean_squared_error(y_norm, y_cal_pred)))

        rmsep_values.append(rmsep)
        rmsec_values.append(rmsec)
        cv_predictions.append(y_cv_pred)

    optimal_idx = int(np.argmin(rmsep_values))
    optimal_components = components[optimal_idx]

    opt_model = PLSRegression(n_components=optimal_components)
    opt_model.fit(X_norm, y_norm)
    y_cal_pred = opt_model.predict(X_norm).ravel()
    y_cv_pred = cv_predictions[optimal_idx]

    T = opt_model.x_scores_
    P = opt_model.x_loadings_
    X_hat = T @ P.T
    X_distance = np.linalg.norm(X_norm.to_numpy() - X_hat, axis=1)
    y_distance = np.abs(y_norm.to_numpy() - y_cal_pred)

    T2 = _compute_t2(T)

    coef = np.asarray(opt_model.coef_).ravel()

    diagnostics = [
        {
            "row_index": int(idx),
            "y_actual": float(y_norm.iloc[i]),
            "y_pred_cal": float(y_cal_pred[i]),
            "y_pred_cv": float(y_cv_pred[i]),
            "T2": float(T2[i]),
            "X_distance": float(X_distance[i]),
            "y_distance": float(y_distance[i]),
        }
        for i, idx in enumerate(X_norm.index)
    ]

    scores = [
        {
            "row_index": int(idx),
            "components": [float(T[i, j]) for j in range(optimal_components)],
        }
        for i, idx in enumerate(X_norm.index)
    ]

    loadings = {
        col: [float(P[i, j]) for j in range(optimal_components)]
        for i, col in enumerate(x_cols)
    }

    coefficients = {col: float(coef[i]) for i, col in enumerate(x_cols)}
    coefficients_raw, intercept = _compute_raw_coefficients(X, y, coefficients)

    # Keyed by model-variable name; value = mean of the BASE column in
    # original (pre-log10) units, so a linear and a log term sharing a base
    # column carry the same baseline (see _predict_raw's raw-scale contract).
    x_means_raw = {name: float(base_frame[base].mean()) for name, base, _ in model_vars}
    x_var_bases = {name: base for name, base, _ in model_vars}
    y_baseline_raw = _predict_raw(
        intercept, coefficients_raw, x_means_raw, log_model_cols, log_y
    )

    return {
        "rmse_per_component": [
            {"components": c, "rmsep": rmsep_values[i], "rmsec": rmsec_values[i]}
            for i, c in enumerate(components)
        ],
        "optimal_components": optimal_components,
        "r2_cal": float(r2_score(y_norm, y_cal_pred)),
        "r2_cv": float(r2_score(y_norm, y_cv_pred)),
        "scores": scores,
        "loadings": loadings,
        "coefficients": coefficients,
        "coefficients_raw": coefficients_raw,
        "intercept": intercept,
        "diagnostics": diagnostics,
        "n_rows_dropped_missing": n_rows_dropped_missing,
        "missing_by_column": missing_by_column,
        "x_means_raw": x_means_raw,
        "y_baseline_raw": y_baseline_raw,
        "x_var_bases": x_var_bases,
    }


def _rmsep_at_optimal(result: dict) -> float:
    """Extract the RMSEP value at a run_analysis result's optimal component count."""
    optimal = result["optimal_components"]
    for entry in result["rmse_per_component"]:
        if entry["components"] == optimal:
            return entry["rmsep"]
    raise ValueError(
        "Fant ikke RMSEP for optimalt antall komponenter."
    )  # pragma: no cover


def optimize_variables(
    df: pd.DataFrame,
    y_col: str,
    excluded_cols: list[str] | None = None,
    excluded_rows: list[int] | None = None,
    limits: dict[str, dict[str, float]] | None = None,
    log_y: bool = False,
    log_x_cols: list[str] | None = None,
    max_components: int = config.MAX_COMPONENTS_DEFAULT,
    cv_folds: int = config.CV_FOLDS_DEFAULT,
    tolerance: float = config.OPTIMIZE_TOLERANCE_DEFAULT,
) -> dict:
    """Greedy backward elimination of X model variables.

    Ported from the reference notebook's optimize_pls_variables
    (Inbox/PLS-regresjon.ipynb, cell 6), minus Fabric export, plotting, and
    verbose printing.

    Operates in model-variable space (see build_model_variables): a base
    column's linear term and log10 term are independent removal candidates.
    Removing a linear term adds its base to excluded_cols; removing a log
    term drops its base from log_x_cols - the other term for that base (if
    any) is unaffected.

    Each pass sorts the currently-active model variables by ascending
    |coefficient| (from the current best model) and tests removing each one
    in turn: if the resulting RMSEP (at that fit's optimal component count)
    is no more than `tolerance` above the current best RMSEP, the removal is
    kept permanently and the best model/RMSEP are updated. A pass that
    eliminates nothing ends the optimization (stop_reason "converged"). The
    last remaining model variable is never removed; running out of
    removable variables ends the optimization too (stop_reason
    "too_few_variables").

    The iteration count is bounded by the number of model variables minus
    one (you cannot remove more than that), further capped by
    config.MAX_OPTIMIZE_ITERATIONS as a safety net against pathologically
    large variable counts. If that combined cap is reached before either
    natural stopping condition, the optimization still returns its
    best-so-far result, with stop_reason "max_iterations" so callers can
    tell a capped run apart from a converged one (previously this cap was
    hit silently: a 60-pure-noise-variable dataset stopped at exactly 50
    removals - the old fixed MAX_OPTIMIZE_ITERATIONS - indistinguishable in
    the response from genuine convergence).

    Raises ValidationError (Norwegian message) if fewer than 2 model
    variables are available to start with.

    Returns a dict with:
        - history: list of {iteration, removed_col, rmsep}, one entry per
          model variable actually removed (not per candidate tested);
          removed_col is the model-variable name (e.g. "log10(X1)").
        - final_excluded_cols: the final list of excluded BASE column names.
        - final_log_x_cols: the final list of log-selected BASE column names.
        - results: the final run_analysis result (same shape as /api/analyze).
        - stop_reason: "converged" | "max_iterations" | "too_few_variables".
    """
    excluded_cols = list(excluded_cols or [])
    log_x_cols = list(log_x_cols or [])

    if y_col not in df.columns:
        raise ValidationError(f"Kolonnen '{y_col}' finnes ikke i datasettet.")

    all_base_cols = [c for c in df.columns if c != y_col]
    model_vars = build_model_variables(all_base_cols, y_col, excluded_cols, log_x_cols)
    if len(model_vars) < 2:
        raise ValidationError(
            "Trenger minst 2 X-variabler for å optimalisere variabelutvalg."
        )

    def _run(excluded: list[str], log_cols: list[str]) -> dict:
        return run_analysis(
            df,
            y_col=y_col,
            excluded_cols=excluded,
            excluded_rows=excluded_rows,
            limits=limits,
            log_y=log_y,
            log_x_cols=log_cols,
            max_components=max_components,
            cv_folds=cv_folds,
        )

    best_excluded = list(excluded_cols)
    best_log = list(log_x_cols)
    best_result = _run(best_excluded, best_log)
    best_rmsep = _rmsep_at_optimal(best_result)

    history: list[dict] = []
    iteration = 0
    # Natural bound: at most (available - 1) removals, since at least one
    # model variable must remain. config.MAX_OPTIMIZE_ITERATIONS is a
    # secondary safety net for pathologically large variable counts; only
    # report "max_iterations" when *that* safety net (not the natural
    # bound) is what actually cut the run short.
    natural_bound = len(model_vars) - 1
    effective_max_iterations = min(natural_bound, config.MAX_OPTIMIZE_ITERATIONS)
    capped_by_safety_net = effective_max_iterations < natural_bound

    stop_reason = "converged"
    while True:
        current_model_vars = build_model_variables(
            all_base_cols, y_col, best_excluded, best_log
        )
        if len(current_model_vars) <= 1:
            stop_reason = "too_few_variables"
            break

        candidates = sorted(
            current_model_vars,
            key=lambda mv: abs(best_result["coefficients"].get(mv[0], 0.0)),
        )

        eliminated_in_pass = False
        hit_cap = False
        removed_this_pass: set[str] = set()
        for model_name, base_name, is_log in candidates:
            if model_name in removed_this_pass:
                continue  # eliminated earlier in this same pass
            if iteration >= effective_max_iterations:
                hit_cap = True
                break

            if is_log:
                trial_excluded = best_excluded
                trial_log = [c for c in best_log if c != base_name]
            else:
                trial_excluded = [*best_excluded, base_name]
                trial_log = best_log

            if not build_model_variables(
                all_base_cols, y_col, trial_excluded, trial_log
            ):
                continue  # would remove the last remaining predictor

            try:
                trial_result = _run(trial_excluded, trial_log)
                trial_rmsep = _rmsep_at_optimal(trial_result)
            except ValidationError:
                continue

            if trial_rmsep <= best_rmsep + tolerance:
                best_excluded = trial_excluded
                best_log = trial_log
                best_rmsep = trial_rmsep
                best_result = trial_result
                eliminated_in_pass = True
                removed_this_pass.add(model_name)
                iteration += 1
                history.append(
                    {
                        "iteration": iteration,
                        "removed_col": model_name,
                        "rmsep": trial_rmsep,
                    }
                )
                if iteration >= effective_max_iterations:
                    hit_cap = True
                    break

        if hit_cap:
            stop_reason = (
                "max_iterations" if capped_by_safety_net else "too_few_variables"
            )
            break
        if not eliminated_in_pass:
            stop_reason = "converged"
            break

    return {
        "history": history,
        "final_excluded_cols": best_excluded,
        "final_log_x_cols": best_log,
        "results": best_result,
        "stop_reason": stop_reason,
    }


def simulate_change(
    intercept: float,
    coefficients_raw: dict[str, float],
    x_means_raw: dict[str, float],
    log_y: bool,
    x_var_bases: dict[str, str],
    changes: dict[str, dict],
) -> dict:
    """What-if simulation: change one or more X-variables (by BASE name)
    from their baseline means (both given and returned in original raw
    units) and predict the resulting Y.

    x_var_bases maps each model variable (a coefficients_raw/x_means_raw
    key) to its base variable name (see build_model_variables); model_var
    != base_var marks a log10-derived term. A base with both a linear and a
    log10 term contributes twice to y (once per term, using the same
    changed base value); `contributions[base]` is their sum.

    changes: {base: {"mode": "absolute"|"percent", "value": float}}.
    "absolute" adds `value` to the baseline; "percent" scales it by
    (1 + value/100). log10 is applied internally to log-derived terms when
    computing the model-scale prediction; `contributions` is reported on
    that model scale (additive - unlike the raw-scale `delta`, which is not
    simply the sum of contributions when log_y makes the back-transform
    nonlinear).

    Raises ValidationError (Norwegian message) for: an unknown base
    variable name, an unrecognized change mode, or a change that drives a
    log-derived term's base value to a non-positive value.
    """
    x_var_bases = x_var_bases or {}
    changes = changes or {}
    log_model_cols = {mv for mv, bv in x_var_bases.items() if mv != bv}
    base_names = set(x_var_bases.values())

    for base in changes:
        if base not in base_names:
            raise ValidationError(f"Ukjent variabel: '{base}'.")

    y_base_model = intercept
    y_new_model = intercept
    contributions: dict[str, float] = {}

    for var, coef in coefficients_raw.items():
        base = x_var_bases.get(var, var)
        x_base = x_means_raw[var]
        base_input = _model_input(var, x_base, log_model_cols)
        y_base_model += coef * base_input

        x_new = x_base
        if base in changes:
            mode = changes[base].get("mode")
            value = changes[base].get("value", 0.0)
            if mode == "percent":
                x_new = x_base * (1 + value / 100.0)
            elif mode == "absolute":
                x_new = x_base + value
            else:
                raise ValidationError(
                    f"Ukjent modus '{mode}' for '{base}'. Bruk 'absolute' eller 'percent'."
                )

        new_input = _model_input(var, x_new, log_model_cols)
        y_new_model += coef * new_input

        if base in changes:
            contributions[base] = contributions.get(base, 0.0) + float(
                coef * (new_input - base_input)
            )

    if log_y:
        y_base = float(10**y_base_model)
        y_new = float(10**y_new_model)
    else:
        y_base = float(y_base_model)
        y_new = float(y_new_model)

    delta = float(y_new - y_base)
    delta_percent = float(delta / y_base * 100.0) if y_base != 0 else 0.0

    return {
        "y_base": y_base,
        "y_new": y_new,
        "delta": delta,
        "delta_percent": delta_percent,
        "contributions": contributions,
    }
