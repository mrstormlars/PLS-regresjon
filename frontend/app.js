// PLS-regresjon frontend: upload -> sheet/range selection -> preview -> configure -> analyze -> results.
// Norwegian text is used for all user-visible strings; identifiers/comments are English.

const state = {
  fileId: null,
  sheets: [],
  columns: [],
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
  const headerRow = parseInt(el("header-row-input").value, 10) || 0;

  setStatus("preview-status", "Henter forhåndsvisning...");
  try {
    const data = await postJson("/api/preview", {
      file_id: state.fileId,
      sheet,
      header_row: headerRow,
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
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = col;
    checkbox.checked = true;
    checkbox.className = "x-col-checkbox";
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(col));
    xContainer.appendChild(label);
  }

  const limitsContainer = el("limits-container");
  limitsContainer.innerHTML = "";
  for (const col of columns) {
    const row = document.createElement("div");
    row.className = "limit-row";

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
}

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
  const headerRow = parseInt(el("header-row-input").value, 10) || 0;
  const startRowRaw = el("start-row-input").value;
  const endRowRaw = el("end-row-input").value;

  const payload = {
    file_id: state.fileId,
    sheet,
    header_row: headerRow,
    start_row: startRowRaw === "" ? null : parseInt(startRowRaw, 10),
    end_row: endRowRaw === "" ? null : parseInt(endRowRaw, 10),
    y_col: el("y-col-select").value,
    excluded_cols: collectExcludedCols(),
    excluded_rows: collectExcludedRows(),
    limits: collectLimits(),
    log_y: el("log-y-checkbox").checked,
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
