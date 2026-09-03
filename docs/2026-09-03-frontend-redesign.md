# Frontend redesign — contract and plan (2026-09-03)

Approved by user. Design language borrowed from the Kunnskapsbanken frontend
(palette, shell, components) — **no company/brand names or logos** in this app.

## Contract (what "done" means)

Verification scope: `pytest tests/`, `ruff check`, `ruff format --check`,
`git grep -i -e nikkelverk -e glencore -- frontend README.md docs` (must be empty).

C1. `pytest tests/` green; `ruff check` and `ruff format --check` clean.
C2. New pytest test: every string-literal id referenced in `frontend/app.js` via
    `el("…")`, `getElementById("…")`, or `Plotly.newPlot("…")` exists as
    `id="…"` in `frontend/index.html`. Test also asserts the extractor found
    at least 30 ids (guards a silently-empty regex). Negative case covered by a
    second test that feeds a synthetic app.js/index.html pair with one missing
    id and asserts the checker reports it.
C3. Brand grep above returns nothing. `frontend/favicon.svg` exists, is linked
    from index.html, and contains no letter glyph/wordmark.
C4. index.html contains exactly four view containers with ids `view-data`,
    `view-model`, `view-results`, `view-simulation`; hashes `#data`, `#modell`,
    `#resultater`, `#simulering` select them; a left nav with one link per view.
    Nav links for model/results/simulation carry a `locked` class until their
    prerequisite (preview done / analysis done / analysis done) is met.
C5. A sticky element `#action-bar` outside all views contains, as descendants:
    `analyze-button`, `export-report-button`, `clear-selection-button`,
    `rerun-without-selected-button`, `rerun-only-selected-button`, plus
    `file-chip`, `selection-chip`, `analyze-status`.
C6. `#preview-table-container` CSS has `overflow: auto` and a `max-height`;
    its `thead th` is `position: sticky`.
C7. Model view: one `.x-col-row` per column containing `.x-col-checkbox`,
    `.log-x-checkbox`, `.limit-low`, `.limit-high` (limits merged into the row;
    `#limits-container`/`.limit-row` removed). Functions `collectExcludedCols`,
    `collectLogXCols`, `collectLimits`, `buildAnalyzePayload`, `rerunAnalysis`,
    `splitModelVarSelection`, `syncColumnCheckboxes`, `runSimulate`, and the
    report-export handler are byte-identical to `main` (diff shows no hunks
    inside them). `updateLimitRowVisibility`/`setColumnRowHidden` may change.
C8. `SELECTION_COLOR === "#E8743B"`. A single shared Plotly layout template
    object is spread into every `Plotly.newPlot` layout. `Plotly.Plots.resize`
    is invoked for every `.plot` in a view when that view becomes visible.
C9. index.html has no `http://`/`https://` in any `<link>`/`<script>` src/href.
C10. `git diff main -- backend/` is empty.
C11. README section "Slik bruker du appen" no longer says "fem nummererte
    steg" and describes the four views and the action bar.
C12. Work on branch `feat/frontend-redesign`; nothing pushed to `main`.

## Plan

1. `git checkout main && git pull && git checkout -b feat/frontend-redesign`.
2. `frontend/style.css`: rewrite. CSS custom properties for palette
   (navy #16216E, navy-dark #0F1A57, sky #1E9FE3, sky-light #7FC9EE,
   sky-pale #D6ECF9, orange #E8743B, purple #8B1A8C, bg #EDF0F4, ink-900
   #16216E, ink-700 #2A3550, ink-500 #5B6678, ink-400 #8A93A3, red #D24B3E,
   green #2E9E5B, mint gradient header). Font stack Inter, Segoe UI,
   system-ui. Shell: header 64px sticky w/ gradient; 68px nav rail expanding
   to 240px on hover; content padding; `.card` (white, 16px radius, shadow);
   `.btn`, `.btn-primary`, `.btn-accent`, `.btn-outline`; `.input`; `.chip`;
   `.stat-tile`; table styles (sky-pale th); `.view.hidden`; `.locked` nav;
   segmented control for coef view; two-column grids; preview container
   scroll (C6); `@media (max-width: 900px)` collapse to one column.
3. `frontend/index.html`: rewrite. Header: generic inline-SVG mark (abstract
   scatter/regression glyph, no letters) + "PLS-regresjon". Nav rail: four
   links with inline SVG icons (upload, sliders, bar-chart, flask) and
   Norwegian labels Data / Modell / Resultater / Simulering. Action bar (C5).
   Four `.view` sections (C4) each with page title + subtitle. Move existing
   elements into views; keep every existing id. Preview card. Model view:
   variable table (thead: Variabel, X, log10, Min, Maks; tbody
   `#x-cols-container`) + settings card. Results: stat tiles container,
   2-col plot grid, coef segmented control, outlier map + suggestions
   side-by-side card, optimisation card. Simulation view: table + reset.
   Add `<link rel="icon" href="favicon.svg">`.
4. `frontend/favicon.svg`: 32x32 rounded navy square with a sky abstract
   glyph (e.g. three dots + line). No letters.
5. `frontend/app.js`, surgical edits only:
   - `SELECTION_COLOR = "#E8743B"`; `PLOT_LAYOUT` template (font, colours,
     paper/plot bg transparent, gridcolor, margin); spread into each layout.
     Trace colours: cal/RMSEP navy, cv/RMSEC sky, scores navy, coef positive
     navy / negative sky, optimiser line navy, guide/optimal lines orange.
   - View router: `VIEWS` map hash→view id; `showView(name)` toggles
     `.hidden`, sets nav `active`, calls `Plotly.Plots.resize` on the view's
     rendered plots; `hashchange` + initial load; `setViewLocked(name, bool)`.
     Replace `showSection(...)` calls: preview success → unlock model +
     `showView("modell")`; analyze success → unlock results+simulation +
     `showView("resultater")` **before** `renderResults`.
   - `populateColumnControls`: build `<tr class="x-col-row">` rows holding
     checkbox, log checkbox, min, max inputs (same classes/data-column).
     Drop `limits-container` loop. `updateLimitRowVisibility` becomes
     enable/disable of the row's limit inputs (disabled when neither X nor
     log checked). Y column row hidden as today.
   - `renderKeyFigures`: stat tiles. `updateSelectionSummary`: also writes
     `#selection-chip` text. File chip set on upload success and sheet change.
   - Do not touch functions listed in C7.
6. Test `tests/test_frontend_ids.py`: helper `missing_ids(app_js, html)`,
   tests per C2. Keep < 1 s.
7. README "Slik bruker du appen": rewrite to four views + action bar (C11).
8. Run scope commands; commit in logical commits; push branch; report with
   command output.

## Contract amendment (after round 1 browser verification)

C13. `frontend/app.js` contains no call to an undefined function; specifically
    `showSection` is either defined or not referenced. Orchestrator browser
    smoke test: upload → Forhåndsvis navigates to `#modell` with no error in
    `preview-status`; Kjør analyse navigates to `#resultater` with 5 plots.
C14. Design conformance: header uses the light mint sheen gradient
    (#ffffff → #eef6f5 → #d7ebe7 → #c6e4df) with navy text and mark; nav rail
    is white with grey icons/labels, active item a navy pill with white text;
    `#action-bar` is `position: sticky` directly below the header (not fixed
    at the bottom), white, with a bottom border; Plotly `title` removed from
    every layout (card `h3` is the title); `.x-col-table` th/td left-aligned
    for the Variabel column and centred otherwise.
