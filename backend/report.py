"""Standalone, self-contained HTML report generation for a PLS analysis result.

No template-engine dependency: the document is built from plain Python
f-strings/string joins (stdlib only), per CLAUDE.md's dependency discipline.
The vendored Plotly bundle is embedded inline so the report has zero
external http(s):// resource references and works fully offline.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path

from backend import config

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "frontend" / "vendor"
_plotly_js_cache: str | None = None


def _plotly_js() -> str:
    """Read the vendored plotly.min.js once and cache it for reuse."""
    global _plotly_js_cache
    if _plotly_js_cache is None:
        _plotly_js_cache = (_VENDOR_DIR / "plotly.min.js").read_text(encoding="utf-8")
    return _plotly_js_cache


def report_filename() -> str:
    """Download filename: "<prefix>-<YYYY-MM-DD>.html"."""
    return (
        f"{config.REPORT_FILENAME_PREFIX}-{datetime.now(UTC).date().isoformat()}.html"
    )


def _esc(value: object) -> str:
    """HTML-escape a value for safe embedding as document text."""
    return html.escape(str(value))


def _fmt(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def _json_for_script(value: object) -> str:
    """JSON-encode a value for embedding inside a <script> tag.

    Escapes "</" so no data value can accidentally close the script tag
    early (e.g. a column or file name containing "</script>").
    """
    return json.dumps(value).replace("</", "<\\/")


def _metric_at_optimal(result: dict, key: str) -> float | None:
    optimal = result.get("optimal_components")
    for entry in result.get("rmse_per_component", []):
        if entry["components"] == optimal:
            return entry[key]
    return None


def _list_or_none(items: list, none_text: str) -> str:
    if not items:
        return none_text
    return ", ".join(_esc(item) for item in items)


def _raw_data_section(result: dict, settings: dict) -> str:
    n_rows = len(result.get("diagnostics", []))
    n_cols = len(result.get("coefficients", {}))
    return f"""
    <h2>Rådata</h2>
    <ul>
      <li>Filnavn: {_esc(settings.get("file_name", "-"))}</li>
      <li>Ark: {_esc(settings.get("sheet", "-"))}</li>
      <li>Antall rader brukt i modellen: {n_rows}</li>
      <li>Antall X-variabler i modellen: {n_cols}</li>
    </ul>
    """


def _preprocessing_section(settings: dict) -> str:
    start_row = settings.get("start_row")
    end_row = settings.get("end_row")
    start_col = settings.get("start_col")
    end_col = settings.get("end_col")
    row_range = (
        f"rad {start_row} til {end_row}" if start_row or end_row else "alle datarader"
    )
    col_range = (
        f"kolonne {start_col} til {end_col}"
        if start_col or end_col
        else "alle kolonner"
    )

    limits = settings.get("limits") or {}
    if limits:
        limit_items = "".join(
            f"<li>{_esc(col)}: min={_esc(bounds.get('low', '-'))}, "
            f"maks={_esc(bounds.get('high', '-'))}</li>"
            for col, bounds in limits.items()
        )
        limits_html = f"<ul>{limit_items}</ul>"
    else:
        limits_html = "<p>Ingen grenseverdier satt.</p>"

    log_y = "Ja" if settings.get("log_y") else "Nei"
    log_x_cols = _list_or_none(settings.get("log_x_cols") or [], "Ingen")

    return f"""
    <h2>Forbehandling</h2>
    <ul>
      <li>Dataområde: header-rad {_esc(settings.get("header_row", "-"))}, {row_range}, {col_range}</li>
      <li>Log10 av Y: {log_y}</li>
      <li>Log10 av X-variabler: {log_x_cols}</li>
      <li>Standardisering: Z-score-normalisering (gjennomsnitt/standardavvik) av alle numeriske kolonner.</li>
    </ul>
    <h3>Grenseverdier</h3>
    {limits_html}
    """


def _removed_rows_section(settings: dict) -> str:
    excluded_rows = settings.get("excluded_rows") or []
    rows_text = (
        ", ".join(str(r) for r in sorted(excluded_rows))
        if excluded_rows
        else "Ingen rader fjernet."
    )
    return f"""
    <h2>Fjernede rader (uteliggere)</h2>
    <p>{_esc(rows_text)}</p>
    """


def _removed_variables_section(settings: dict) -> str:
    excluded_cols = settings.get("excluded_cols") or []
    cols_text = _list_or_none(excluded_cols, "Ingen variabler fjernet.")
    return f"""
    <h2>Fjernede variabler</h2>
    <p>{cols_text}</p>
    """


def _coefficients_section(result: dict, settings: dict) -> str:
    coefficients = result.get("coefficients", {})
    coefficients_raw = result.get("coefficients_raw", {})
    intercept = result.get("intercept")
    log_x_cols = set(settings.get("log_x_cols") or [])

    rows = "".join(
        f"<tr><td>{_esc(col)}</td><td>{_fmt(coefficients.get(col))}</td>"
        f"<td>{_fmt(coefficients_raw.get(col))}</td>"
        f"<td>{'log10' if col in log_x_cols else '-'}</td></tr>"
        for col in coefficients
    )

    return f"""
    <h2>Koeffisienter</h2>
    <table border="1" cellpadding="4" cellspacing="0">
      <thead>
        <tr><th>Variabel</th><th>Normalisert koeffisient</th><th>Rå koeffisient</th><th>Skala</th></tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
    <p>Intercept (rå skala): {_fmt(intercept)}</p>
    <p>
      Merk: koeffisienter for log10-transformerte variabler gjelder log10-verdien
      av variabelen, ikke den opprinnelige verdien.
    </p>
    <div id="coef-plot" style="width:700px;height:400px;"></div>
    """


def _predicted_vs_measured_section(result: dict) -> str:
    rmsec = _metric_at_optimal(result, "rmsec")
    rmsep = _metric_at_optimal(result, "rmsep")
    r2_cal = result.get("r2_cal")
    return f"""
    <h2>Predikert vs. målt</h2>
    <div id="pred-plot" style="width:700px;height:450px;"></div>
    <p>RMSEC: {_fmt(rmsec)} | RMSEP: {_fmt(rmsep)} | R²: {_fmt(r2_cal)}</p>
    """


def _plot_script(result: dict) -> str:
    coefficients = result.get("coefficients", {})
    cols = list(coefficients.keys())
    values = [coefficients[c] for c in cols]
    bar_colors = ["#d62728" if v < 0 else "#1f77b4" for v in values]

    diagnostics = result.get("diagnostics", [])
    y_actual = [d["y_actual"] for d in diagnostics]
    y_pred_cal = [d["y_pred_cal"] for d in diagnostics]
    y_pred_cv = [d["y_pred_cv"] for d in diagnostics]

    rmsec = _metric_at_optimal(result, "rmsec")
    rmsep = _metric_at_optimal(result, "rmsep")
    r2_cal = result.get("r2_cal")
    corner_text = f"RMSEC: {_fmt(rmsec)}<br>RMSEP: {_fmt(rmsep)}<br>R²: {_fmt(r2_cal)}"

    all_y = y_actual + y_pred_cal + y_pred_cv
    y_min = min(all_y) if all_y else 0
    y_max = max(all_y) if all_y else 1

    return f"""
    <script>
      Plotly.newPlot('coef-plot', [{{
        x: {_json_for_script(cols)},
        y: {_json_for_script(values)},
        type: 'bar',
        marker: {{ color: {_json_for_script(bar_colors)} }}
      }}], {{
        title: 'Koeffisienter (normalisert)',
        xaxis: {{ title: 'Variabel' }},
        yaxis: {{ title: 'Koeffisientverdi' }}
      }}, {{ displaylogo: false }});

      Plotly.newPlot('pred-plot', [
        {{
          x: {_json_for_script(y_actual)},
          y: {_json_for_script(y_pred_cal)},
          mode: 'markers',
          type: 'scatter',
          name: 'Kalibrering',
          marker: {{ color: '#1f77b4' }}
        }},
        {{
          x: {_json_for_script(y_actual)},
          y: {_json_for_script(y_pred_cv)},
          mode: 'markers',
          type: 'scatter',
          name: 'Kryssvalidering',
          marker: {{ color: '#ff7f0e' }}
        }},
        {{
          x: {_json_for_script([y_min, y_max])},
          y: {_json_for_script([y_min, y_max])},
          mode: 'lines',
          type: 'scatter',
          line: {{ color: 'black', dash: 'dash' }},
          showlegend: false,
          hoverinfo: 'skip'
        }}
      ], {{
        title: 'Faktisk vs. predikert Y',
        xaxis: {{ title: 'Faktisk Y' }},
        yaxis: {{ title: 'Predikert Y' }},
        annotations: [{{
          xref: 'paper', yref: 'paper',
          x: 0.02, y: 0.98,
          xanchor: 'left', yanchor: 'top',
          showarrow: false,
          bgcolor: 'rgba(255,255,255,0.85)',
          bordercolor: '#333',
          borderwidth: 1,
          text: {_json_for_script(corner_text)}
        }}]
      }}, {{ displaylogo: false }});
    </script>
    """


def build_report_html(result: dict, settings: dict) -> str:
    """Build a standalone HTML report string for a completed analysis.

    `result` is an /api/analyze-shaped dict (coefficients, coefficients_raw,
    intercept, diagnostics, rmse_per_component, optimal_components, r2_cal,
    ...). `settings` carries the run's metadata (file/sheet/range, limits,
    log transforms, exclusions, cv_folds, max_components) needed for the
    "Rådata"/"Forbehandling"/"Fjernede ..." sections, none of which is
    derivable from `result` alone.
    """
    body_sections = "".join(
        [
            _raw_data_section(result, settings),
            _preprocessing_section(settings),
            _removed_rows_section(settings),
            _removed_variables_section(settings),
            _coefficients_section(result, settings),
            _predicted_vs_measured_section(result),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="utf-8">
<title>PLS-regresjonsrapport</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; max-width: 900px; margin: 0 auto; padding: 1rem; }}
  table {{ border-collapse: collapse; }}
  th, td {{ padding: 0.3rem 0.6rem; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
</style>
<script>{_plotly_js()}</script>
</head>
<body>
  <h1>PLS-regresjonsrapport</h1>
  <p>Generert: {_esc(datetime.now(UTC).date().isoformat())}</p>
  {body_sections}
  {_plot_script(result)}
</body>
</html>
"""
