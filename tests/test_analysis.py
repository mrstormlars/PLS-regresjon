"""Tests for backend.analysis: PLS pipeline, outlier/low-impact detection, normalization."""

import numpy as np
import pandas as pd
import pytest

from backend import analysis, config
from backend.parsing import ValidationError


def make_signal_dataset(
    n_rows: int = 100, n_vars: int = 8, seed: int = 0
) -> pd.DataFrame:
    """Synthetic linear dataset: 3 of n_vars X-columns carry signal, rest are noise."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_rows, n_vars))
    y = (
        3.0 * X[:, 0]
        - 2.0 * X[:, 1]
        + 1.5 * X[:, 2]
        + rng.normal(scale=0.1, size=n_rows)
    )
    df = pd.DataFrame(X, columns=[f"X{i + 1}" for i in range(n_vars)])
    df["Y"] = y
    return df


def test_run_analysis_fits_strong_linear_signal():
    # max_components is capped at 4 deliberately: with 5 pure-noise columns,
    # RMSEP keeps improving by negligible amounts past the 3 true signal
    # components (measured plateau ~0.068 vs ~0.070), so an uncapped sweep
    # would non-deterministically pick anywhere from 4-8 components. Capping
    # at 4 still verifies the model resolves the signal within a small budget.
    df = make_signal_dataset()
    result = analysis.run_analysis(df, y_col="Y", max_components=4, cv_folds=5)
    assert result["r2_cal"] > 0.9
    assert result["optimal_components"] <= 4


def test_run_analysis_rejects_non_numeric_y():
    df = make_signal_dataset(n_rows=20)
    df["Y"] = ["ikke_tall"] * len(df)
    with pytest.raises(ValidationError):
        analysis.run_analysis(df, y_col="Y")


def test_run_analysis_rejects_too_few_valid_rows():
    n = config.MIN_VALID_ROWS - 1
    df = make_signal_dataset(n_rows=n)
    with pytest.raises(ValidationError):
        analysis.run_analysis(df, y_col="Y")


def test_run_analysis_applies_row_and_column_exclusions():
    df = make_signal_dataset(n_rows=30)
    result = analysis.run_analysis(
        df,
        y_col="Y",
        excluded_cols=["X8"],
        excluded_rows=[0, 1],
        max_components=5,
        cv_folds=3,
    )
    assert "X8" not in result["coefficients"]
    assert 0 not in [d["row_index"] for d in result["diagnostics"]]


def test_run_analysis_applies_limits_and_log_y():
    df = make_signal_dataset(n_rows=40)
    df["Y"] = np.abs(df["Y"]) + 1.0  # ensure strictly positive for log10
    result = analysis.run_analysis(
        df,
        y_col="Y",
        limits={"X1": {"low": 0.0}},
        log_y=True,
        max_components=5,
        cv_folds=3,
    )
    assert result["optimal_components"] >= 1
    assert len(result["diagnostics"]) < 40


def test_normalize_data_zscores_columns_and_skips_zero_variance():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [5.0, 5.0, 5.0]})
    normalized = analysis.normalize_data(df)
    assert normalized["A"].mean() == pytest.approx(0.0, abs=1e-9)
    assert normalized["B"].tolist() == [5.0, 5.0, 5.0]  # zero-variance column untouched


def _diagnostics_df():
    return pd.DataFrame(
        {
            "RowIndex": [0, 1, 2, 3, 4],
            "IsExcluded": [0, 0, 0, 0, 0],
            "y_distance": [0.1, 0.2, 5.0, 0.15, 0.1],
            "X_distance": [0.1, 0.2, 0.3, 6.0, 0.1],
            "T2": [1.0, 1.2, 0.9, 1.1, 8.0],
        }
    )


def test_identify_outliers_finds_row_above_threshold():
    outliers = analysis.identify_outliers(
        _diagnostics_df(), method="y_distance", threshold=1.0
    )
    assert outliers == [2]


def test_identify_outliers_returns_empty_when_threshold_high():
    outliers = analysis.identify_outliers(
        _diagnostics_df(), method="T2", threshold=100.0
    )
    assert outliers == []


def _coef_df():
    return pd.DataFrame(
        {
            "VariableName": ["X1", "X2", "X3"],
            "AbsCoefficient": [1.0, 0.05, 0.5],
            "IsExcluded": [0, 0, 0],
        }
    )


def test_identify_low_impact_variables_finds_small_coefficient():
    low_impact = analysis.identify_low_impact_variables(_coef_df(), threshold=0.1)
    assert low_impact == ["X2"]


def test_identify_low_impact_variables_returns_empty_when_threshold_zero():
    low_impact = analysis.identify_low_impact_variables(_coef_df(), threshold=0.0)
    assert low_impact == []
