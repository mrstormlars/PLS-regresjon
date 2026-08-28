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

# Minimum number of cross-validation folds; below this, KFold is meaningless.
MIN_CV_FOLDS = 2


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
            uses Q3 + 1.5 * IQR.

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
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        threshold = q3 + 1.5 * iqr

    outliers = included_df[values > threshold]
    return outliers["RowIndex"].tolist()


def identify_low_impact_variables(
    coef_df: pd.DataFrame, threshold: float | None = None
) -> list[str]:
    """Identify variable names with low-impact coefficients.

    Args:
        coef_df: DataFrame with columns IsExcluded, VariableName, AbsCoefficient.
        threshold: Absolute-coefficient cutoff. If None, uses 10% of the max.

    Returns:
        List of variable names whose |coefficient| is below the threshold.
    """
    included_df = coef_df[coef_df["IsExcluded"] == 0]

    if threshold is None:
        max_abs_coef = included_df["AbsCoefficient"].max()
        threshold = 0.1 * max_abs_coef

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


def run_analysis(
    df: pd.DataFrame,
    y_col: str,
    excluded_cols: list[str] | None = None,
    excluded_rows: list[int] | None = None,
    limits: dict[str, dict[str, float]] | None = None,
    log_y: bool = False,
    max_components: int = config.MAX_COMPONENTS_DEFAULT,
    cv_folds: int = config.CV_FOLDS_DEFAULT,
) -> dict:
    """Run the full PLS analysis pipeline on an already range-extracted DataFrame.

    Pipeline: drop excluded rows/columns -> limit filter -> optional log10(Y)
    -> coerce numeric, inf -> NaN, drop incomplete rows -> standardize
    (mean/std) -> PLS sweep 1..max_components with KFold CV -> pick optimal
    component count by minimum RMSEP -> fit optimal model -> diagnostics.

    Raises ValidationError (Norwegian message) if Y is not numeric or if
    fewer than config.MIN_VALID_ROWS complete rows remain.
    """
    excluded_cols = excluded_cols or []
    excluded_rows = excluded_rows or []
    limits = limits or {}

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
    actual_cv = max(MIN_CV_FOLDS, min(cv_folds, n_rows))

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

    component_var = np.var(T, axis=0, ddof=1)
    component_var = np.where(component_var == 0, 1e-10, component_var)
    T2 = np.sum((T**2) / component_var, axis=1)

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
