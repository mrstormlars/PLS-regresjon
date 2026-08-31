"""Tests for backend.analysis: PLS pipeline, outlier/low-impact detection, normalization."""

import time

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
    with pytest.raises(ValidationError, match="ikke numeriske verdier"):
        analysis.run_analysis(df, y_col="Y")


def test_run_analysis_rejects_too_few_valid_rows():
    n = config.MIN_VALID_ROWS - 1
    df = make_signal_dataset(n_rows=n)
    with pytest.raises(ValidationError, match="For få gyldige rader"):
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


def test_run_analysis_log_x_cols_applies_log10_before_standardization():
    # Y == log10(X1) exactly, so log-transforming X1 should let a single
    # component fit near-perfectly.
    n = 30
    x1 = np.array([10.0**k for k in range(1, n + 1)])
    y = np.arange(1, n + 1, dtype=float)
    df = pd.DataFrame({"X1": x1, "Y": y})
    result = analysis.run_analysis(
        df, y_col="Y", log_x_cols=["X1"], max_components=1, cv_folds=3
    )
    assert result["r2_cal"] > 0.99


def test_run_analysis_log_x_cols_all_non_positive_rejected():
    n = config.MIN_VALID_ROWS
    df = pd.DataFrame({"X1": [-5.0] * n, "Y": list(range(1, n + 1))})
    with pytest.raises(ValidationError, match="For få gyldige rader"):
        analysis.run_analysis(df, y_col="Y", log_x_cols=["X1"])


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


def test_compute_t2_guards_against_zero_variance_component():
    # Second column is constant across rows -> zero sample variance. Without
    # the epsilon guard this divides by zero, producing inf/NaN T2 values.
    T = np.array(
        [
            [1.0, 5.0],
            [2.0, 5.0],
            [3.0, 5.0],
            [-1.0, 5.0],
        ]
    )
    t2 = analysis._compute_t2(T)
    assert np.all(np.isfinite(t2))
    assert np.all(t2 > 0)


def make_optimize_dataset(
    n_rows: int = 60, n_noise: int = 4, seed: int = 42
) -> pd.DataFrame:
    """One strongly informative column plus several pure-noise columns."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n_rows)
    y = 5.0 * signal + rng.normal(scale=0.05, size=n_rows)
    df = pd.DataFrame({"Signal": signal})
    for i in range(n_noise):
        df[f"N{i + 1}"] = rng.normal(size=n_rows)
    df["Y"] = y
    return df


def test_optimize_variables_removes_noise_and_improves_or_matches_rmsep():
    df = make_optimize_dataset()
    start = time.perf_counter()
    initial = analysis.run_analysis(df, y_col="Y", max_components=3, cv_folds=5)
    result = analysis.optimize_variables(
        df, y_col="Y", max_components=3, cv_folds=5, tolerance=0.0
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0

    initial_best_rmsep = analysis._rmsep_at_optimal(initial)
    final_best_rmsep = analysis._rmsep_at_optimal(result["results"])

    assert result["final_excluded_cols"]  # at least one noise var removed
    assert set(result["final_excluded_cols"]).issubset({"N1", "N2", "N3", "N4"})
    assert final_best_rmsep <= initial_best_rmsep + 0.0
    assert result["history"]
    for i, entry in enumerate(result["history"], start=1):
        assert entry["iteration"] == i
        assert entry["removed_col"] in {"N1", "N2", "N3", "N4"}
    assert result["results"]["coefficients"]  # Signal (and maybe some N's) remain
    assert "Signal" in result["results"]["coefficients"]
    assert result["stop_reason"] in {"converged", "too_few_variables"}


def test_optimize_variables_rejects_fewer_than_two_x_variables():
    df = pd.DataFrame({"X1": list(range(1, 21)), "Y": list(range(1, 21))})
    with pytest.raises(ValidationError, match="minst 2 X-variabler"):
        analysis.optimize_variables(df, y_col="Y")


def make_two_signal_dataset(
    n_rows: int = 60, n_noise: int = 14, seed: int = 0
) -> pd.DataFrame:
    """Two informative columns plus many pure-noise columns.

    Unlike make_optimize_dataset (one signal column), this leaves >=2
    variables standing after all noise is removed, so optimization can end
    via a genuine "tested and kept both" pass (stop_reason "converged")
    rather than running out of variables ("too_few_variables").
    """
    rng = np.random.default_rng(seed)
    signal1 = rng.normal(size=n_rows)
    signal2 = rng.normal(size=n_rows)
    y = 4.0 * signal1 - 3.0 * signal2 + rng.normal(scale=0.02, size=n_rows)
    df = pd.DataFrame({"Signal1": signal1, "Signal2": signal2})
    for i in range(n_noise):
        df[f"N{i + 1}"] = rng.normal(size=n_rows)
    df["Y"] = y
    return df


def test_optimize_variables_removes_all_noise_and_converges():
    # Root-cause regression test: previously, hitting
    # config.MAX_OPTIMIZE_ITERATIONS (a fixed 50) silently truncated the
    # run with no way to tell it apart from genuine convergence. This
    # dataset has 14 removable noise variables (> the old fixed cap would
    # ever have been a problem for, but well above the "converged" test's
    # historical scope of a handful) to prove removal isn't arbitrarily
    # capped and stop_reason correctly reports "converged".
    df = make_two_signal_dataset(n_noise=14)
    start = time.perf_counter()
    result = analysis.optimize_variables(
        df, y_col="Y", max_components=2, cv_folds=5, tolerance=0.0
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0

    assert len(result["history"]) >= 12
    assert set(result["final_excluded_cols"]) == {f"N{i + 1}" for i in range(14)}
    assert result["stop_reason"] == "converged"
    assert set(result["results"]["coefficients"]) == {"Signal1", "Signal2"}


def test_optimize_variables_reports_max_iterations_when_safety_net_hit(monkeypatch):
    # With the safety net set below the natural bound (14 removable noise
    # vars), the run must stop exactly at the cap and say so via
    # stop_reason, rather than silently returning a partial result that
    # looks identical to a converged one.
    monkeypatch.setattr(config, "MAX_OPTIMIZE_ITERATIONS", 3)
    df = make_two_signal_dataset(n_noise=14)
    result = analysis.optimize_variables(
        df, y_col="Y", max_components=2, cv_folds=5, tolerance=0.0
    )
    assert len(result["history"]) == 3
    assert result["stop_reason"] == "max_iterations"


def test_optimize_variables_reports_too_few_variables_when_natural_bound_hit():
    # A huge tolerance makes every candidate pass the RMSEP check, so a
    # single pass removes variables until only one predictor is left - the
    # *natural* bound (available_vars - 1), reached inside the pass via the
    # hit_cap path, distinct from the config.MAX_OPTIMIZE_ITERATIONS safety
    # net (which is untouched here at its default of 50). This must be
    # classified as "too_few_variables", not "max_iterations".
    rng = np.random.default_rng(5)
    n_rows = 15
    df = pd.DataFrame({f"X{i + 1}": rng.normal(size=n_rows) for i in range(5)})
    df["Y"] = rng.normal(size=n_rows)

    result = analysis.optimize_variables(
        df, y_col="Y", max_components=1, cv_folds=3, tolerance=1e6
    )
    assert len(result["history"]) == 4  # 5 available vars - 1 remaining
    assert result["stop_reason"] == "too_few_variables"


def test_run_analysis_raw_coefficients_recover_true_linear_betas():
    rng = np.random.default_rng(0)
    n = 50
    x1 = rng.normal(loc=10, scale=3, size=n)
    x2 = rng.normal(loc=-5, scale=2, size=n)
    true_intercept, true_b1, true_b2 = 7.0, 2.5, -1.3
    y = true_intercept + true_b1 * x1 + true_b2 * x2 + rng.normal(scale=0.01, size=n)
    df = pd.DataFrame({"X1": x1, "X2": x2, "Y": y})

    result = analysis.run_analysis(df, y_col="Y", max_components=2, cv_folds=5)

    assert result["coefficients_raw"]["X1"] == pytest.approx(true_b1, abs=0.05)
    assert result["coefficients_raw"]["X2"] == pytest.approx(true_b2, abs=0.05)
    assert result["intercept"] == pytest.approx(true_intercept, abs=0.05)


def _raw_coefficient_equivalence_max_error(
    df: pd.DataFrame, result: dict, x_cols: list[str], y_series: pd.Series
) -> float:
    """Recomputes the raw-scale calibration prediction two ways and returns
    the largest discrepancy across all rows: once from the standardized
    y_pred_cal reported in diagnostics (converted back to the y_series'
    raw/post-log10 scale using the same mean/std normalize_data would use),
    and once from intercept + sum(coefficients_raw[j] * raw_x_j).
    """
    y_std = y_series.std()
    y_mean = y_series.mean()
    max_error = 0.0
    for i, (_, row) in enumerate(df.reset_index(drop=True).iterrows()):
        diag = result["diagnostics"][i]
        expected = diag["y_pred_cal"] * y_std + y_mean
        actual = result["intercept"] + sum(
            result["coefficients_raw"][c] * row[c] for c in x_cols
        )
        max_error = max(max_error, abs(actual - expected))
    return max_error


def test_run_analysis_raw_coefficients_equivalent_to_calibration_prediction():
    df = make_signal_dataset(n_rows=40)
    result = analysis.run_analysis(df, y_col="Y", max_components=3, cv_folds=5)
    x_cols = [c for c in df.columns if c != "Y"]
    max_error = _raw_coefficient_equivalence_max_error(df, result, x_cols, df["Y"])
    assert max_error < 1e-8


def test_run_analysis_raw_coefficients_equivalent_on_log_y_scale():
    df = make_signal_dataset(n_rows=40)
    df["Y"] = np.abs(df["Y"]) + 1.0  # strictly positive for log10
    result = analysis.run_analysis(
        df, y_col="Y", log_y=True, max_components=3, cv_folds=5
    )
    x_cols = [c for c in df.columns if c != "Y"]
    log_y = np.log10(df["Y"])
    max_error = _raw_coefficient_equivalence_max_error(df, result, x_cols, log_y)
    assert max_error < 1e-8
