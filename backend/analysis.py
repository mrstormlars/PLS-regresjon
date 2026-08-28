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

    Pipeline: drop excluded rows/columns -> limit filter -> optional log10(Y)
    and log10(selected X columns) -> coerce numeric, inf -> NaN, drop
    incomplete rows -> standardize (mean/std) -> PLS sweep 1..max_components
    with KFold CV -> pick optimal component count by minimum RMSEP -> fit
    optimal model -> diagnostics.

    Non-positive values in a log10'd column become NaN and are dropped by
    the existing incomplete-row handling; if that pushes the valid row count
    below config.MIN_VALID_ROWS, the existing ValidationError below applies.

    Raises ValidationError (Norwegian message) if Y is not numeric or if
    fewer than config.MIN_VALID_ROWS complete rows remain.
    """
    excluded_cols = excluded_cols or []
    excluded_rows = excluded_rows or []
    limits = limits or {}
    log_x_cols = log_x_cols or []

    if y_col not in df.columns:
        raise ValidationError(f"Kolonnen '{y_col}' finnes ikke i datasettet.")

    working = df.drop(index=[r for r in excluded_rows if r in df.index])
    working = working.drop(columns=[c for c in excluded_cols if c in working.columns])

    working = _apply_limits(working, limits)

    y_numeric = pd.to_numeric(working[y_col], errors="coerce")
    if y_numeric.notna().sum() == 0:
        raise ValidationError(f"Kolonnen '{y_col}' inneholder ikke numeriske verdier.")

    if log_y:
        with np.errstate(divide="ignore", invalid="ignore"):
            y_numeric = np.log10(y_numeric)

    x_cols = [c for c in working.columns if c != y_col]
    X = working[x_cols].apply(pd.to_numeric, errors="coerce")
    if log_x_cols:
        with np.errstate(divide="ignore", invalid="ignore"):
            for col in log_x_cols:
                if col in X.columns:
                    X[col] = np.log10(X[col])
    X = X.replace([np.inf, -np.inf], np.nan)
    y = y_numeric.replace([np.inf, -np.inf], np.nan)

    valid_mask = X.notna().all(axis=1) & y.notna()
    X = X.loc[valid_mask]
    y = y.loc[valid_mask]

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
        "diagnostics": diagnostics,
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
    """Greedy backward elimination of X-variables.

    Ported from the reference notebook's optimize_pls_variables
    (Inbox/PLS-regresjon.ipynb, cell 6), minus Fabric export, plotting, and
    verbose printing.

    Each pass sorts the currently-included variables by ascending
    |coefficient| (from the current best model) and tests excluding each one
    in turn: if the resulting RMSEP (at that fit's optimal component count)
    is no more than `tolerance` above the current best RMSEP, the exclusion
    is kept permanently and the best model/RMSEP are updated. A pass that
    eliminates nothing ends the optimization (stop_reason "converged"). The
    last remaining predictor is never removed; running out of removable
    variables ends the optimization too (stop_reason "too_few_variables").

    The iteration count is bounded by the number of available X-variables
    minus one (you cannot remove more than that), further capped by
    config.MAX_OPTIMIZE_ITERATIONS as a safety net against pathologically
    large variable counts. If that combined cap is reached before either
    natural stopping condition, the optimization still returns its
    best-so-far result, with stop_reason "max_iterations" so callers can
    tell a capped run apart from a converged one (previously this cap was
    hit silently: a 60-pure-noise-variable dataset stopped at exactly 50
    removals - the old fixed MAX_OPTIMIZE_ITERATIONS - indistinguishable in
    the response from genuine convergence).

    Raises ValidationError (Norwegian message) if fewer than 2 X-variables
    are available to start with.

    Returns a dict with:
        - history: list of {iteration, removed_col, rmsep}, one entry per
          variable actually removed (not per candidate tested).
        - final_excluded_cols: the final list of excluded column names.
        - results: the final run_analysis result (same shape as /api/analyze).
        - stop_reason: "converged" | "max_iterations" | "too_few_variables".
    """
    excluded_cols = list(excluded_cols or [])

    if y_col not in df.columns:
        raise ValidationError(f"Kolonnen '{y_col}' finnes ikke i datasettet.")

    all_vars = [c for c in df.columns if c != y_col]
    available_vars = [c for c in all_vars if c not in excluded_cols]
    if len(available_vars) < 2:
        raise ValidationError(
            "Trenger minst 2 X-variabler for å optimalisere variabelutvalg."
        )

    def _run(cols: list[str]) -> dict:
        return run_analysis(
            df,
            y_col=y_col,
            excluded_cols=cols,
            excluded_rows=excluded_rows,
            limits=limits,
            log_y=log_y,
            log_x_cols=log_x_cols,
            max_components=max_components,
            cv_folds=cv_folds,
        )

    best_excluded = list(excluded_cols)
    best_result = _run(best_excluded)
    best_rmsep = _rmsep_at_optimal(best_result)

    history: list[dict] = []
    iteration = 0
    # Natural bound: at most (available - 1) removals, since at least one
    # predictor must remain. config.MAX_OPTIMIZE_ITERATIONS is a secondary
    # safety net for pathologically large variable counts; only report
    # "max_iterations" when *that* safety net (not the natural bound) is
    # what actually cut the run short.
    natural_bound = len(available_vars) - 1
    effective_max_iterations = min(natural_bound, config.MAX_OPTIMIZE_ITERATIONS)
    capped_by_safety_net = effective_max_iterations < natural_bound

    stop_reason = "converged"
    while True:
        included = [c for c in all_vars if c not in best_excluded]
        if len(included) <= 1:
            stop_reason = "too_few_variables"
            break

        candidates = sorted(
            included, key=lambda c: abs(best_result["coefficients"].get(c, 0.0))
        )

        eliminated_in_pass = False
        hit_cap = False
        for var in candidates:
            if var in best_excluded:
                continue  # eliminated earlier in this same pass
            if iteration >= effective_max_iterations:
                hit_cap = True
                break

            trial_excluded = [*best_excluded, var]
            if not [c for c in all_vars if c not in trial_excluded]:
                continue  # would remove the last remaining predictor

            try:
                trial_result = _run(trial_excluded)
                trial_rmsep = _rmsep_at_optimal(trial_result)
            except ValidationError:
                continue

            if trial_rmsep <= best_rmsep + tolerance:
                best_excluded = trial_excluded
                best_rmsep = trial_rmsep
                best_result = trial_result
                eliminated_in_pass = True
                iteration += 1
                history.append(
                    {"iteration": iteration, "removed_col": var, "rmsep": trial_rmsep}
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
        "results": best_result,
        "stop_reason": stop_reason,
    }
