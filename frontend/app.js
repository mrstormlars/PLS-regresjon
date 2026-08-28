// PLS-regresjon frontend: upload -> sheet/range selection -> preview -> configure -> analyze -> results.
// Norwegian text is used for all user-visible strings; identifiers/comments are English.

const state = {
  fileId: null,
  sheets: [],
  columns: [],
  yCol: null,
  charts: {},
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

el("analyze-button").addEventListener("click", async () => {
  const sheet = el("sheet-select").value;
  const headerRow = parseInt(el("header-row-input").value, 10) || 1;
  const startRowRaw = el("start-row-input").value;
  const endRowRaw = el("end-row-input").value;
  const startCol = parseColumnInput(el("start-col-input").value);
  const endCol = parseColumnInput(el("end-col-input").value);

  const payload = {
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

  setStatus("analyze-status", "Kjører analyse...");
  try {
    const result = await postJson("/api/analyze", payload);
    renderResults(result);
    setStatus("analyze-status", "Analyse fullført.");
    showSection("results-section");
  } catch (err) {
    setStatus("analyze-status", err.message, true);
  }
});

function destroyChart(name) {
  if (state.charts[name]) {
    state.charts[name].destroy();
    delete state.charts[name];
  }
}

function renderResults(result) {
  renderKeyFigures(result);
  renderRmseChart(result);
  renderPredictedActualChart(result);
  renderScoresChart(result);
  renderCoefficientsChart(result);
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
  destroyChart("rmse");
  const ctx = el("rmse-chart").getContext("2d");
  state.charts.rmse = new Chart(ctx, {
    type: "line",
    data: {
      labels: result.rmse_per_component.map((r) => r.components),
      datasets: [
        {
          label: "RMSEP",
          data: result.rmse_per_component.map((r) => r.rmsep),
          borderColor: "#1f77b4",
          fill: false,
        },
        {
          label: "RMSEC",
          data: result.rmse_per_component.map((r) => r.rmsec),
          borderColor: "#ff7f0e",
          fill: false,
        },
      ],
    },
    options: {
      scales: {
        x: { title: { display: true, text: "Antall komponenter" } },
        y: { title: { display: true, text: "RMSE" } },
      },
    },
  });
}

function renderPredictedActualChart(result) {
  destroyChart("predictedActual");
  const ctx = el("predicted-actual-chart").getContext("2d");
  const rowIndexByPosition = result.diagnostics.map((d) => d.row_index);
  state.charts.predictedActual = new Chart(ctx, {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "Kalibrering",
          data: result.diagnostics.map((d) => ({ x: d.y_actual, y: d.y_pred_cal })),
          backgroundColor: "#1f77b4",
        },
        {
          label: "Kryssvalidering",
          data: result.diagnostics.map((d) => ({ x: d.y_actual, y: d.y_pred_cv })),
          backgroundColor: "#ff7f0e",
        },
      ],
    },
    options: {
      scales: {
        x: { title: { display: true, text: "Faktisk Y" } },
        y: { title: { display: true, text: "Predikert Y" } },
      },
      onClick: (_evt, elements) => showSelectedRow(elements, rowIndexByPosition),
    },
  });
}

function renderScoresChart(result) {
  destroyChart("scores");
  const ctx = el("scores-chart").getContext("2d");
  const rowIndexByPosition = result.scores.map((s) => s.row_index);
  state.charts.scores = new Chart(ctx, {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "Scores",
          data: result.scores.map((s) => ({
            x: s.components[0] ?? 0,
            y: s.components[1] ?? 0,
          })),
          backgroundColor: "#2ca02c",
        },
      ],
    },
    options: {
      scales: {
        x: { title: { display: true, text: "PC1" } },
        y: { title: { display: true, text: "PC2" } },
      },
      onClick: (_evt, elements) => showSelectedRow(elements, rowIndexByPosition),
    },
  });
}

function renderCoefficientsChart(result) {
  destroyChart("coefficients");
  const ctx = el("coefficients-chart").getContext("2d");
  const entries = Object.entries(result.coefficients);
  state.charts.coefficients = new Chart(ctx, {
    type: "bar",
    data: {
      labels: entries.map(([name]) => name),
      datasets: [
        {
          label: "Koeffisient",
          data: entries.map(([, value]) => value),
          backgroundColor: entries.map(([, value]) => (value < 0 ? "#d62728" : "#1f77b4")),
        },
      ],
    },
    options: {
      indexAxis: "y",
    },
  });
}

function showSelectedRow(elements, rowIndexByPosition) {
  if (!elements.length) return;
  const rowIndex = rowIndexByPosition[elements[0].index];
  setStatus("selected-row-info", `Valgt punkt: radindeks ${rowIndex}`);
}
