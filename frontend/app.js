// PLS-regresjon frontend: upload -> sheet/range selection -> preview -> configure -> analyze -> results.
// Norwegian text is used for all user-visible strings; identifiers/comments are English.

const PLOTLY_CONFIG = { responsive: true, displaylogo: false };
const SELECTION_COLOR = "#e6308a";

const state = {
  fileId: null,
  sheets: [],
  columns: [],
  yCol: null,
  // Domain selections shared across all plots of that domain (rows: scores +
  // predicted-vs-actual; columns: coefficients). Row values are Excel row
  // numbers; column values are X-variable names.
  selectedRows: new Set(),
  selectedCols: new Set(),
  // Per-plot metadata needed to restyle marker colors when the selection
  // changes: customData[traceIndex] maps each point to its row/column
  // identifier, baseColors[traceIndex] is either a single color or a
  // per-point color array.
  plotMeta: {},
  lastAnalyzePayload: null,
  lastAnalyzeResult: null,
  lastOptimizeResult: null,
};

const el = (id) => document.getElementById(id);

function showSection(id) {
  el(id).classList.remove("hidden");
}

function setStatus(id, message, isError = false) {
  const node = el(id);
  node.textContent = message;
  node.classList.toggle("error", isError);
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Ukjent feil fra serveren.");
  }
  return data;
}

// Converts an Excel-style column reference ("A", "b", "AA", or a plain
// number like "3") to a 1-based column index. Returns null for empty input.
function parseColumnInput(raw) {
  const value = raw.trim();
  if (!value) return null;
  if (/^\d+$/.test(value)) {
    return parseInt(value, 10);
  }
  const letters = value.toUpperCase();
  if (!/^[A-Z]+$/.test(letters)) return null;
  let index = 0;
  for (const ch of letters) {
    index = index * 26 + (ch.charCodeAt(0) - "A".charCodeAt(0) + 1);
  }
  return index;
}

el("upload-button").addEventListener("click", async () => {
  const fileInput = el("file-input");
  if (!fileInput.files.length) {
    setStatus("upload-status", "Velg en fil først.", true);
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  setStatus("upload-status", "Laster opp...");
  try {
    const response = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Ukjent feil ved opplasting.");
    }
    state.fileId = data.file_id;
    state.sheets = data.sheets;

    const sheetSelect = el("sheet-select");
    sheetSelect.innerHTML = "";
    for (const sheet of state.sheets) {
      const option = document.createElement("option");
      option.value = sheet;
      option.textContent = sheet;
      sheetSelect.appendChild(option);
    }

    setStatus("upload-status", `Filen ble lastet opp (${state.sheets.length} ark funnet).`);
    showSection("sheet-section");
  } catch (err) {
    setStatus("upload-status", err.message, true);
  }
});

el("preview-button").addEventListener("click", async () => {
  const sheet = el("sheet-select").value;
  const headerRow = parseInt(el("header-row-input").value, 10) || 1;
  const startCol = parseColumnInput(el("start-col-input").value);
  const endCol = parseColumnInput(el("end-col-input").value);

  setStatus("preview-status", "Henter forhåndsvisning...");
  try {
    const data = await postJson("/api/preview", {
      file_id: state.fileId,
      sheet,
      header_row: headerRow,
      start_col: startCol,
      end_col: endCol,
    });
    state.columns = data.columns;
    renderPreviewTable(data.columns, data.rows);
    populateColumnControls(data.columns);
    setStatus("preview-status", `${data.n_rows} rader totalt i valgt ark.`);
    showSection("preview-section");
    showSection("config-section");
  } catch (err) {
    setStatus("preview-status", err.message, true);
  }
});

function renderPreviewTable(columns, rows) {
  const container = el("preview-table-container");
  const table = document.createElement("table");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const radTh = document.createElement("th");
  radTh.textContent = "Rad";
  headRow.appendChild(radTh);
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    const radTd = document.createElement("td");
    radTd.textContent = row.row_index;
    tr.appendChild(radTd);
    for (const col of columns) {
      const td = document.createElement("td");
      const value = row[col];
      td.textContent = value === null || value === undefined ? "" : value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  container.innerHTML = "";
  container.appendChild(table);
}

// Finds a row element for a given column among elements carrying the given
// class, matched via the data-column attribute (avoids CSS-selector escaping
// issues for column names with special characters).
function findColumnRow(className, column) {
  const rows = document.querySelectorAll(`.${className}`);
  for (const row of rows) {
    if (row.dataset.column === column) return row;
  }
  return null;
}

function setColumnRowHidden(className, column, hidden) {
  const row = findColumnRow(className, column);
  if (row) row.classList.toggle("hidden-row", hidden);
}

function populateColumnControls(columns) {
  const ySelect = el("y-col-select");
  ySelect.innerHTML = "";
  for (const col of columns) {
    const option = document.createElement("option");
    option.value = col;
    option.textContent = col;
    ySelect.appendChild(option);
  }

  const xContainer = el("x-cols-container");
  xContainer.innerHTML = "";
  for (const col of columns) {
    const row = document.createElement("div");
    row.className = "x-col-row";
    row.dataset.column = col;

    const checkboxLabel = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = col;
    checkbox.checked = true;
    checkbox.className = "x-col-checkbox";
    checkbox.addEventListener("change", () => {
      setColumnRowHidden("limit-row", col, !checkbox.checked);
    });
    checkboxLabel.appendChild(checkbox);
    checkboxLabel.appendChild(document.createTextNode(col));

    const logLabel = document.createElement("label");
    const logCheckbox = document.createElement("input");
    logCheckbox.type = "checkbox";
    logCheckbox.className = "log-x-checkbox";
    logCheckbox.dataset.column = col;
    logLabel.appendChild(logCheckbox);
    logLabel.appendChild(document.createTextNode("log10"));

    row.appendChild(checkboxLabel);
    row.appendChild(logLabel);
    xContainer.appendChild(row);
  }

  const limitsContainer = el("limits-container");
  limitsContainer.innerHTML = "";
  for (const col of columns) {
    const row = document.createElement("div");
    row.className = "limit-row";
    row.dataset.column = col;

    const label = document.createElement("label");
    label.textContent = col;

    const lowInput = document.createElement("input");
    lowInput.type = "number";
    lowInput.placeholder = "min";
    lowInput.className = "limit-low";
    lowInput.dataset.column = col;

    const highInput = document.createElement("input");
    highInput.type = "number";
    highInput.placeholder = "maks";
    highInput.className = "limit-high";
    highInput.dataset.column = col;

    row.appendChild(label);
    row.appendChild(lowInput);
    row.appendChild(highInput);
    limitsContainer.appendChild(row);
  }

  // The first column defaults as Y; hide it from the X list/limits from the start.
  state.yCol = columns.length ? columns[0] : null;
  if (state.yCol) {
    setColumnRowHidden("x-col-row", state.yCol, true);
    setColumnRowHidden("limit-row", state.yCol, true);
  }
}

// Selecting a new Y column restores the previous Y column to the X list and
// hides the newly selected one. Unaffected columns' checked/limit state is
// untouched (rows are hidden via CSS, never removed/recreated).
el("y-col-select").addEventListener("change", () => {
  const newY = el("y-col-select").value;
  const oldY = state.yCol;
  if (oldY && oldY !== newY) {
    setColumnRowHidden("x-col-row", oldY, false);
    setColumnRowHidden("limit-row", oldY, false);
  }
  setColumnRowHidden("x-col-row", newY, true);
  setColumnRowHidden("limit-row", newY, true);
  state.yCol = newY;
});

function collectExcludedCols() {
  const yCol = el("y-col-select").value;
  const checkboxes = document.querySelectorAll(".x-col-checkbox");
  const excluded = [];
  for (const checkbox of checkboxes) {
    if (!checkbox.checked && checkbox.value !== yCol) {
      excluded.push(checkbox.value);
    }
  }
  return excluded;
}

function collectLogXCols() {
  const yCol = el("y-col-select").value;
  const checkboxes = document.querySelectorAll(".log-x-checkbox");
  const logCols = [];
  for (const checkbox of checkboxes) {
    if (checkbox.checked && checkbox.dataset.column !== yCol) {
      logCols.push(checkbox.dataset.column);
    }
  }
  return logCols;
}

function collectLimits() {
  const limits = {};
  const lowInputs = document.querySelectorAll(".limit-low");
  const highInputs = document.querySelectorAll(".limit-high");
  for (const input of lowInputs) {
    if (input.value !== "") {
      limits[input.dataset.column] = limits[input.dataset.column] || {};
      limits[input.dataset.column].low = parseFloat(input.value);
    }
  }
  for (const input of highInputs) {
    if (input.value !== "") {
      limits[input.dataset.column] = limits[input.dataset.column] || {};
      limits[input.dataset.column].high = parseFloat(input.value);
    }
  }
  return limits;
}

function collectExcludedRows() {
  const raw = el("excluded-rows-input").value.trim();
  if (!raw) return [];
  return raw
    .split(",")
    .map((part) => parseInt(part.trim(), 10))
    .filter((n) => !Number.isNaN(n));
}

function buildAnalyzePayload() {
  const sheet = el("sheet-select").value;
  const headerRow = parseInt(el("header-row-input").value, 10) || 1;
  const startRowRaw = el("start-row-input").value;
  const endRowRaw = el("end-row-input").value;
  const startCol = parseColumnInput(el("start-col-input").value);
  const endCol = parseColumnInput(el("end-col-input").value);

  return {
    file_id: state.fileId,
    sheet,
    header_row: headerRow,
    start_row: startRowRaw === "" ? null : parseInt(startRowRaw, 10),
    end_row: endRowRaw === "" ? null : parseInt(endRowRaw, 10),
    start_col: startCol,
    end_col: endCol,
    y_col: el("y-col-select").value,
    excluded_cols: collectExcludedCols(),
    excluded_rows: collectExcludedRows(),
    limits: collectLimits(),
    log_y: el("log-y-checkbox").checked,
    log_x_cols: collectLogXCols(),
    max_components: parseInt(el("max-components-input").value, 10),
    cv_folds: parseInt(el("cv-folds-input").value, 10),
  };
}

el("analyze-button").addEventListener("click", async () => {
  const payload = buildAnalyzePayload();
  setStatus("analyze-status", "Kjører analyse...");
  try {
    const result = await postJson("/api/analyze", payload);
    state.lastAnalyzePayload = payload;
    renderResults(result);
    setStatus("analyze-status", "Analyse fullført.");
    showSection("results-section");
  } catch (err) {
    setStatus("analyze-status", err.message, true);
  }
});

// ---------------------------------------------------------------------------
// Linked selection: clicking/box-selecting a point in one plot of a domain
// (rows or columns) highlights the same points in every plot of that domain.
// ---------------------------------------------------------------------------

function toggleOrSetSelection(selectionSet, value, domEvent) {
  const isMultiSelect = domEvent && (domEvent.ctrlKey || domEvent.metaKey);
  if (isMultiSelect) {
    if (selectionSet.has(value)) {
      selectionSet.delete(value);
    } else {
      selectionSet.add(value);
    }
  } else {
    selectionSet.clear();
    selectionSet.add(value);
  }
}

function applySelectionStyling(plotId, selectionSet) {
  const meta = state.plotMeta[plotId];
  if (!meta) return;
  // Target only the traces listed in meta (e.g. skips a non-selectable
  // reference line trace) so restyle never sends a mismatched-length color
  // array to a trace it doesn't describe.
  const traceIndices = meta.customData.map((_, i) => i);

  if (meta.useOutline) {
    // Fill color already conveys a continuous value (e.g. T2 on the outlier
    // map), so selection is shown as a marker outline instead of replacing
    // the fill color.
    const lineColors = meta.customData.map((customArray) =>
      customArray.map((value) => (selectionSet.has(value) ? SELECTION_COLOR : "rgba(0,0,0,0)"))
    );
    const lineWidths = meta.customData.map((customArray) =>
      customArray.map((value) => (selectionSet.has(value) ? 3 : 0))
    );
    Plotly.restyle(
      plotId,
      { "marker.line.color": lineColors, "marker.line.width": lineWidths },
      traceIndices
    );
    return;
  }

  const colorsPerTrace = meta.customData.map((customArray, traceIndex) => {
    const base = meta.baseColors[traceIndex];
    return customArray.map((value, i) =>
      selectionSet.has(value) ? SELECTION_COLOR : Array.isArray(base) ? base[i] : base
    );
  });
  Plotly.restyle(plotId, { "marker.color": colorsPerTrace }, traceIndices);
}

function updateSelectionSummary() {
  const rows = [...state.selectedRows].sort((a, b) => a - b);
  const cols = [...state.selectedCols];
  el("row-selection-summary").textContent = rows.length
    ? `Markerte rader (Excel-radnumre): ${rows.join(", ")}`
    : "Ingen rader markert.";
  el("col-selection-summary").textContent = cols.length
    ? `Markerte kolonner: ${cols.join(", ")}`
    : "Ingen kolonner markert.";

  const hasSelection = rows.length > 0 || cols.length > 0;
  el("rerun-without-selected-button").disabled = !hasSelection;
  el("rerun-only-selected-button").disabled = !hasSelection;
}

function refreshRowSelection() {
  applySelectionStyling("predicted-actual-chart", state.selectedRows);
  applySelectionStyling("scores-chart", state.selectedRows);
  applySelectionStyling("outlier-map-chart", state.selectedRows);
  updateSelectionSummary();
}

function refreshColSelection() {
  applySelectionStyling("coefficients-chart", state.selectedCols);
  updateSelectionSummary();
}

function handleRowPointClick(eventData) {
  if (!eventData.points || !eventData.points.length) return;
  const rowIndex = eventData.points[0].customdata;
  if (rowIndex === undefined || rowIndex === null) return; // e.g. the reference line
  toggleOrSetSelection(state.selectedRows, rowIndex, eventData.event);
  refreshRowSelection();
}

function handleRowBoxSelect(eventData) {
  state.selectedRows.clear();
  if (eventData && eventData.points) {
    for (const point of eventData.points) {
      if (point.customdata !== undefined && point.customdata !== null) {
        state.selectedRows.add(point.customdata);
      }
    }
  }
  refreshRowSelection();
}

function handleColPointClick(eventData) {
  if (!eventData.points || !eventData.points.length) return;
  const col = eventData.points[0].x;
  toggleOrSetSelection(state.selectedCols, col, eventData.event);
  refreshColSelection();
}

function handleColBoxSelect(eventData) {
  state.selectedCols.clear();
  if (eventData && eventData.points) {
    for (const point of eventData.points) {
      state.selectedCols.add(point.x);
    }
  }
  refreshColSelection();
}

function bindRowSelectionEvents(plotId) {
  const gd = el(plotId);
  gd.on("plotly_click", handleRowPointClick);
  gd.on("plotly_selected", handleRowBoxSelect);
}

function bindColSelectionEvents(plotId) {
  const gd = el(plotId);
  gd.on("plotly_click", handleColPointClick);
  gd.on("plotly_selected", handleColBoxSelect);
}

el("clear-selection-button").addEventListener("click", () => {
  state.selectedRows.clear();
  state.selectedCols.clear();
  refreshRowSelection();
  refreshColSelection();
});

// ---------------------------------------------------------------------------
// Re-run with/without the current selection, preserving all other settings.
// ---------------------------------------------------------------------------

function getAllRowIndices() {
  if (!state.lastAnalyzeResult) return [];
  return state.lastAnalyzeResult.diagnostics.map((d) => d.row_index);
}

function getAllXCols() {
  if (!state.lastAnalyzeResult) return [];
  return Object.keys(state.lastAnalyzeResult.coefficients);
}

async function rerunAnalysis(mode) {
  if (!state.lastAnalyzePayload) return;
  const payload = { ...state.lastAnalyzePayload };
  const excludedRows = new Set(payload.excluded_rows || []);
  const excludedCols = new Set(payload.excluded_cols || []);
  const selectedRows = [...state.selectedRows];
  const selectedCols = [...state.selectedCols];

  if (mode === "without-selected") {
    for (const row of selectedRows) excludedRows.add(row);
    for (const col of selectedCols) excludedCols.add(col);
  } else if (mode === "only-selected") {
    if (selectedRows.length) {
      const keep = new Set(selectedRows);
      for (const row of getAllRowIndices()) {
        if (!keep.has(row)) excludedRows.add(row);
      }
    }
    if (selectedCols.length) {
      const keep = new Set(selectedCols);
      for (const col of getAllXCols()) {
        if (!keep.has(col)) excludedCols.add(col);
      }
    }
  }

  payload.excluded_rows = [...excludedRows];
  payload.excluded_cols = [...excludedCols];

  setStatus("analyze-status", "Kjører analyse på nytt...");
  try {
    const result = await postJson("/api/analyze", payload);
    state.lastAnalyzePayload = payload;
    el("excluded-rows-input").value = payload.excluded_rows.join(", ");
    for (const checkbox of document.querySelectorAll(".x-col-checkbox")) {
      if (payload.excluded_cols.includes(checkbox.value)) {
        checkbox.checked = false;
        setColumnRowHidden("limit-row", checkbox.value, true);
      }
    }
    renderResults(result);
    setStatus("analyze-status", "Analyse fullført.");
  } catch (err) {
    setStatus("analyze-status", err.message, true);
  }
}

el("rerun-without-selected-button").addEventListener("click", () => rerunAnalysis("without-selected"));
el("rerun-only-selected-button").addEventListener("click", () => rerunAnalysis("only-selected"));

// ---------------------------------------------------------------------------
// Outlier / low-impact-variable suggestions: pre-select the returned
// rows/columns so the re-run buttons above can act on them.
// ---------------------------------------------------------------------------

el("suggest-outliers-button").addEventListener("click", async () => {
  if (!state.lastAnalyzeResult) {
    setStatus("suggestion-status", "Kjør en analyse først.", true);
    return;
  }
  const method = el("suggest-outlier-method-select").value;
  const thresholdRaw = el("suggest-outlier-threshold-input").value;
  const threshold = thresholdRaw === "" ? null : parseFloat(thresholdRaw);

  setStatus("suggestion-status", "Henter forslag...");
  try {
    const data = await postJson("/api/suggest-outliers", {
      diagnostics: state.lastAnalyzeResult.diagnostics,
      method,
      threshold,
    });
    state.selectedRows.clear();
    for (const rowIndex of data.row_indices) state.selectedRows.add(rowIndex);
    refreshRowSelection();
    setStatus(
      "suggestion-status",
      `${data.row_indices.length} rad(er) foreslått som uteliggere og markert.`
    );
  } catch (err) {
    setStatus("suggestion-status", err.message, true);
  }
});

el("suggest-low-impact-button").addEventListener("click", async () => {
  if (!state.lastAnalyzeResult) {
    setStatus("suggestion-status", "Kjør en analyse først.", true);
    return;
  }
  const thresholdRaw = el("suggest-low-impact-threshold-input").value;
  const threshold = thresholdRaw === "" ? null : parseFloat(thresholdRaw);
  const coefficients = Object.entries(state.lastAnalyzeResult.coefficients).map(
    ([variable, coefficient]) => ({ variable, coefficient })
  );

  setStatus("suggestion-status", "Henter forslag...");
  try {
    const data = await postJson("/api/suggest-low-impact", { coefficients, threshold });
    state.selectedCols.clear();
    for (const col of data.columns) state.selectedCols.add(col);
    refreshColSelection();
    setStatus(
      "suggestion-status",
      `${data.columns.length} variabel/variabler med lav påvirkning foreslått og markert.`
    );
  } catch (err) {
    setStatus("suggestion-status", err.message, true);
  }
});

// ---------------------------------------------------------------------------
// Automatic variable optimization.
// ---------------------------------------------------------------------------

// Machine-readable stop_reason -> Norwegian explanation shown in the UI.
const STOP_REASON_LABELS = {
  converged: "ingen forbedring i en hel runde",
  max_iterations: "nådde det maksimale antallet iterasjoner",
  too_few_variables: "for få variabler igjen til å fortsette",
};

el("optimize-button").addEventListener("click", async () => {
  if (!state.lastAnalyzePayload) {
    setStatus("optimize-status", "Kjør en analyse først.", true);
    return;
  }
  const toleranceRaw = el("optimize-tolerance-input").value;
  const tolerance = toleranceRaw === "" ? 0 : parseFloat(toleranceRaw);
  const payload = { ...state.lastAnalyzePayload, tolerance };

  const button = el("optimize-button");
  button.disabled = true;
  setStatus("optimize-status", "Optimaliserer variabler ...");
  try {
    const data = await postJson("/api/optimize", payload);
    state.lastOptimizeResult = data;
    renderOptimizeHistory(data);
    renderOptimizeSummary(data);

    // Pre-select the removed variables in the COLUMN selection domain, via
    // the same mechanism as suggest-low-impact - no special-casing. This
    // only highlights them; it does not change any settings automatically.
    state.selectedCols.clear();
    for (const entry of data.history) state.selectedCols.add(entry.removed_col);
    refreshColSelection();

    const stopLabel = STOP_REASON_LABELS[data.stop_reason] || data.stop_reason;
    if (data.final_excluded_cols.length) {
      setStatus(
        "optimize-status",
        `Optimalisering fullført: ${data.final_excluded_cols.length} variabel/variabler kan fjernes. Stoppet: ${stopLabel}.`
      );
      el("apply-optimized-button").classList.remove("hidden");
    } else {
      setStatus(
        "optimize-status",
        `Optimalisering fullført: ingen variabler kunne fjernes innenfor toleransen. Stoppet: ${stopLabel}.`
      );
      el("apply-optimized-button").classList.add("hidden");
    }
  } catch (err) {
    setStatus("optimize-status", err.message, true);
  } finally {
    button.disabled = false;
  }
});

function renderOptimizeHistory(data) {
  const container = el("optimize-history-chart");
  if (!data.history.length) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");
  Plotly.newPlot(
    container,
    [
      {
        x: data.history.map((h) => h.iteration),
        y: data.history.map((h) => h.rmsep),
        mode: "lines+markers",
        type: "scatter",
        text: data.history.map((h) => h.removed_col),
        hovertemplate: "Iterasjon %{x}<br>Fjernet: %{text}<br>RMSEP: %{y:.4f}<extra></extra>",
      },
    ],
    {
      title: "RMSEP per iterasjon (variabeloptimalisering)",
      xaxis: { title: "Iterasjon", dtick: 1 },
      yaxis: { title: "RMSEP" },
    },
    PLOTLY_CONFIG
  );
}

// Norwegian summary: removed variables in removal order (with RMSEP after
// each removal) and the variables that were kept.
function renderOptimizeSummary(data) {
  const container = el("optimize-summary");
  container.innerHTML = "";

  const removedHeading = document.createElement("p");
  removedHeading.innerHTML = "<strong>Fjernede variabler (i rekkefølge):</strong>";
  container.appendChild(removedHeading);

  if (data.history.length) {
    const list = document.createElement("ol");
    for (const entry of data.history) {
      const item = document.createElement("li");
      item.textContent = `${entry.removed_col} (RMSEP etter fjerning: ${entry.rmsep.toFixed(4)})`;
      list.appendChild(item);
    }
    container.appendChild(list);
  } else {
    const none = document.createElement("p");
    none.textContent = "Ingen variabler ble fjernet.";
    container.appendChild(none);
  }

  const keptCols = Object.keys(data.results.coefficients);
  const keptHeading = document.createElement("p");
  keptHeading.innerHTML = `<strong>Beholdte variabler:</strong> ${keptCols.join(", ") || "ingen"}`;
  container.appendChild(keptHeading);
}

el("apply-optimized-button").addEventListener("click", () => {
  if (!state.lastOptimizeResult) return;
  const finalExcluded = state.lastOptimizeResult.final_excluded_cols;

  for (const checkbox of document.querySelectorAll(".x-col-checkbox")) {
    if (finalExcluded.includes(checkbox.value)) {
      checkbox.checked = false;
      setColumnRowHidden("limit-row", checkbox.value, true);
    }
  }

  state.lastAnalyzePayload = { ...state.lastAnalyzePayload, excluded_cols: finalExcluded };
  renderResults(state.lastOptimizeResult.results);
  setStatus("optimize-status", "Optimalisert utvalg er brukt på resultatene.");
});

// ---------------------------------------------------------------------------
// Result rendering (Plotly).
// ---------------------------------------------------------------------------

function renderResults(result) {
  state.lastAnalyzeResult = result;
  state.selectedRows.clear();
  state.selectedCols.clear();

  renderKeyFigures(result);
  renderRmseChart(result);
  renderPredictedActualChart(result);
  renderScoresChart(result);
  renderCoefficientsChart(result);
  renderOutlierMapChart(result);
  updateOutlierMapGuide();

  refreshRowSelection();
  refreshColSelection();
  el("optimize-history-chart").classList.add("hidden");
  el("apply-optimized-button").classList.add("hidden");
}

function renderKeyFigures(result) {
  const optimal = result.rmse_per_component.find(
    (r) => r.components === result.optimal_components
  );
  const container = el("key-figures");
  container.innerHTML = "";
  const figures = [
    ["Optimalt antall komponenter", result.optimal_components],
    ["RMSEP (optimal)", optimal ? optimal.rmsep.toFixed(4) : "-"],
    ["RMSEC (optimal)", optimal ? optimal.rmsec.toFixed(4) : "-"],
    ["R² kalibrering", result.r2_cal.toFixed(4)],
    ["R² kryssvalidering", result.r2_cv.toFixed(4)],
  ];
  for (const [label, value] of figures) {
    const div = document.createElement("div");
    div.innerHTML = `<strong>${label}</strong><br>${value}`;
    container.appendChild(div);
  }
}

function renderRmseChart(result) {
  const components = result.rmse_per_component.map((r) => r.components);
  Plotly.newPlot(
    "rmse-chart",
    [
      {
        x: components,
        y: result.rmse_per_component.map((r) => r.rmsep),
        mode: "lines+markers",
        type: "scatter",
        name: "RMSEP",
        line: { color: "#1f77b4" },
      },
      {
        x: components,
        y: result.rmse_per_component.map((r) => r.rmsec),
        mode: "lines+markers",
        type: "scatter",
        name: "RMSEC",
        line: { color: "#ff7f0e", dash: "dash" },
      },
    ],
    {
      title: "RMSEP og RMSEC vs. antall komponenter",
      xaxis: { title: "Antall komponenter", dtick: 1 },
      yaxis: { title: "RMSE" },
      shapes: [
        {
          type: "line",
          x0: result.optimal_components,
          x1: result.optimal_components,
          y0: 0,
          y1: 1,
          yref: "paper",
          line: { color: "red", dash: "dot" },
        },
      ],
    },
    PLOTLY_CONFIG
  );
}

function renderPredictedActualChart(result) {
  const rowIndex = result.diagnostics.map((d) => d.row_index);
  const calColor = "#1f77b4";
  const cvColor = "#ff7f0e";
  const labels = rowIndex.map((r) => `Rad ${r}`);

  const traceCal = {
    x: result.diagnostics.map((d) => d.y_actual),
    y: result.diagnostics.map((d) => d.y_pred_cal),
    customdata: rowIndex,
    mode: "markers",
    type: "scatter",
    name: "Kalibrering",
    marker: { color: calColor },
    text: labels,
    hovertemplate: "%{text}<br>Faktisk: %{x}<br>Predikert: %{y}<extra></extra>",
  };
  const traceCv = {
    x: result.diagnostics.map((d) => d.y_actual),
    y: result.diagnostics.map((d) => d.y_pred_cv),
    customdata: rowIndex,
    mode: "markers",
    type: "scatter",
    name: "Kryssvalidering",
    marker: { color: cvColor },
    text: labels,
    hovertemplate: "%{text}<br>Faktisk: %{x}<br>Predikert: %{y}<extra></extra>",
  };
  const allValues = result.diagnostics.flatMap((d) => [d.y_actual, d.y_pred_cal, d.y_pred_cv]);
  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const traceRef = {
    x: [minV, maxV],
    y: [minV, maxV],
    mode: "lines",
    type: "scatter",
    line: { color: "black", dash: "dash" },
    showlegend: false,
    hoverinfo: "skip",
  };

  Plotly.newPlot(
    "predicted-actual-chart",
    [traceCal, traceCv, traceRef],
    {
      title: "Faktisk vs. predikert Y",
      xaxis: { title: "Faktisk Y" },
      yaxis: { title: "Predikert Y" },
      dragmode: "select",
    },
    PLOTLY_CONFIG
  );

  state.plotMeta["predicted-actual-chart"] = {
    customData: [rowIndex, rowIndex],
    baseColors: [calColor, cvColor],
  };
  bindRowSelectionEvents("predicted-actual-chart");
}

function renderScoresChart(result) {
  const rowIndex = result.scores.map((s) => s.row_index);
  const baseColor = "#2ca02c";

  Plotly.newPlot(
    "scores-chart",
    [
      {
        x: result.scores.map((s) => s.components[0] ?? 0),
        y: result.scores.map((s) => s.components[1] ?? 0),
        customdata: rowIndex,
        mode: "markers",
        type: "scatter",
        name: "Scores",
        marker: { color: baseColor },
        text: rowIndex.map((r) => `Rad ${r}`),
        hovertemplate: "%{text}<br>PC1: %{x}<br>PC2: %{y}<extra></extra>",
      },
    ],
    {
      title: "Scores (PC1 vs. PC2)",
      xaxis: { title: "PC1" },
      yaxis: { title: "PC2" },
      dragmode: "select",
      showlegend: false,
    },
    PLOTLY_CONFIG
  );

  state.plotMeta["scores-chart"] = { customData: [rowIndex], baseColors: [baseColor] };
  bindRowSelectionEvents("scores-chart");
}

function renderOutlierMapChart(result) {
  const rowIndex = result.diagnostics.map((d) => d.row_index);
  const xValues = result.diagnostics.map((d) => d.X_distance);
  const yValues = result.diagnostics.map((d) => d.y_distance);
  const t2Values = result.diagnostics.map((d) => d.T2);

  Plotly.newPlot(
    "outlier-map-chart",
    [
      {
        x: xValues,
        y: yValues,
        customdata: rowIndex,
        mode: "markers",
        type: "scatter",
        name: "Uteliggerkart",
        marker: {
          color: t2Values,
          colorscale: "Viridis",
          showscale: true,
          colorbar: { title: "T²" },
          line: { width: 0 },
        },
        text: rowIndex.map((r, i) => `Rad ${r}, T²=${t2Values[i].toFixed(4)}`),
        hovertemplate: "%{text}<br>X-avstand: %{x}<br>y-avstand: %{y}<extra></extra>",
      },
    ],
    {
      title: "Uteliggerkart",
      xaxis: { title: "X-avstand" },
      yaxis: { title: "y-avstand" },
      dragmode: "select",
      showlegend: false,
    },
    PLOTLY_CONFIG
  );

  state.plotMeta["outlier-map-chart"] = { customData: [rowIndex], useOutline: true };
  bindRowSelectionEvents("outlier-map-chart");
}

// Draws a threshold guide line on the outlier map matching the current
// suggestion controls: horizontal for y_distance, vertical for X_distance,
// none for T2 (already conveyed by marker color). Called on every
// method/threshold change and whenever the map is (re)rendered.
function updateOutlierMapGuide() {
  const gd = el("outlier-map-chart");
  if (!gd || !gd.data) return; // not rendered yet

  const method = el("suggest-outlier-method-select").value;
  const thresholdRaw = el("suggest-outlier-threshold-input").value;
  const threshold = thresholdRaw === "" ? null : parseFloat(thresholdRaw);

  let shapes = [];
  if (threshold !== null && !Number.isNaN(threshold)) {
    if (method === "y_distance") {
      shapes = [
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: "y",
          y0: threshold,
          y1: threshold,
          line: { color: "red", dash: "dot" },
        },
      ];
    } else if (method === "X_distance") {
      shapes = [
        {
          type: "line",
          yref: "paper",
          y0: 0,
          y1: 1,
          xref: "x",
          x0: threshold,
          x1: threshold,
          line: { color: "red", dash: "dot" },
        },
      ];
    }
    // T2: no guide line - color already conveys it.
  }
  Plotly.relayout(gd, { shapes });
}

el("suggest-outlier-method-select").addEventListener("change", updateOutlierMapGuide);
el("suggest-outlier-threshold-input").addEventListener("input", updateOutlierMapGuide);

function renderCoefficientsChart(result) {
  const entries = Object.entries(result.coefficients);
  const cols = entries.map(([name]) => name);
  const values = entries.map(([, value]) => value);
  const baseColors = values.map((value) => (value < 0 ? "#d62728" : "#1f77b4"));

  Plotly.newPlot(
    "coefficients-chart",
    [
      {
        x: cols,
        y: values,
        type: "bar",
        marker: { color: baseColors },
      },
    ],
    {
      title: "Koeffisienter",
      xaxis: { title: "Variabel" },
      yaxis: { title: "Koeffisientverdi" },
      dragmode: "select",
    },
    PLOTLY_CONFIG
  );

  state.plotMeta["coefficients-chart"] = { customData: [cols], baseColors: [baseColors] };
  bindColSelectionEvents("coefficients-chart");
}
