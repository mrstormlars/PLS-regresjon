# CLAUDE.md — Read This First

> **The single source of truth for AI coding agents working in this repository. Read it in full before proposing or making any change.**

**Part A** is project rules and context. **Part B** is engineering discipline.

---

# PART A — PROJECT RULES & CONTEXT

## What this project is

A simple web app for **PLS regression analysis** (Partial Least Squares): the user uploads a dataset in Excel (`.xlsx`) or CSV format, selects predictor (X) and response (Y) columns, and gets a fitted PLS model with diagnostics (explained variance, scores/loadings plots, RMSE/R², cross-validation).

- **Backend:** Python (FastAPI) — file parsing (pandas/openpyxl), PLS fitting (scikit-learn `PLSRegression`), JSON API.
- **Frontend:** plain HTML/CSS/JavaScript served by the backend — upload form, column selection, results and plots. No frontend build step, no framework.

## Directory structure

- `backend/` — Python application code: `app.py` (FastAPI app + routes), `analysis.py` (PLS fitting and diagnostics), `parsing.py` (Excel/CSV ingestion and validation).
- `frontend/` — static HTML/CSS/JS, served by the backend.
- `tests/` — pytest tests, with small fixture datasets under `tests/fixtures/`.
- `docs/` — implementation plans and design notes.
- `scripts/` — operational helper scripts, if any.

Keep this section updated as the structure evolves.

## Hard rules

- **Never hardcode secrets** — no tokens, keys, or credentials in code or config. (This app should not need any.)
- **Never push directly to `main`.** See the workflow below.
- **Uploaded user data stays local and transient.** Never commit uploaded datasets, never send them to external services. Test fixtures are small synthetic datasets created for the repo.
- **Tuning parameters live in one place** (e.g. max components, CV folds, upload size limit) — a constants section or config module, not magic numbers scattered through the code.
- **UI text is Norwegian; code is English.** Every string a user of the product sees (labels, buttons, error messages shown in the browser) is Norwegian. Code identifiers, log lines, comments, tests, and repo documents are English.

## Source control & branch/PR workflow (UNBREAKABLE)

Branch protection is **not** enforced automatically, so this workflow is a hard requirement for both humans and agents:

1. **Never push directly to `main`.**
2. Always branch from the latest `main`: `git checkout main && git pull` then `git checkout -b feat/<topic>` (or `fix/…`, `docs/…`, `chore/…`).
3. Make changes on the feature branch and push it.
4. **Open a Pull Request** against `main`. Only after review, approval, and merge are changes adopted.

GitHub auth is Git Credential Manager / `gh` — never a token in an env var or in git config.

## Testing rules

- **All new features ship with pytest tests.** Code is not "done" and must not merge unless its tests pass.
- Run: `pytest tests/` from the repo root. Lint: `ruff check && ruff format --check`.
- Tests use small synthetic fixture datasets — never large files, never network access.
- Resource ceilings: a single test under **5 s**, a test file under **30 s**. Exceeding one must be justified in the PR, never in silence.
- Match the test scope to the change: docs-only diffs need no test run; a code change runs the tests covering it, plus one green full `pytest tests/` before merge.

## Agent workflow

The `.claude` folder defines a role-separated loop; the core principle is **never let one context both plan and grade**:

- `/brainstorm` — explores an idea with the user, then writes an implementation plan into `docs/`.
- `/orchestrator` — writes the contract (what "done" means, machine-checkable) and the plan, delegates implementation to the `worker` subagent, and routes the result to the `evaluator` subagent. Never writes code, never grades its own plan.
- `worker` — implements the plan, reports back with measured evidence.
- `evaluator` — grades the diff against the contract and this document. Verdict only (`PASS`/`FAIL`); never edits, never proposes fixes.

For small direct requests outside this loop, normal interactive work is fine — the loop is for substantial features.

---

# PART B — ENGINEERING DISCIPLINE

Field notes on writing reusable code. Apply these to every change, in addition to the rules above.

## I. Read before you write

Read the files you are about to modify — enough to understand, not just to snip. Copy existing patterns, and verify imports are actually used. Reuse existing dependencies rather than reaching for new tools. If you cannot find a pattern to follow, stop and ask; do not guess.

## II. Think before you code

State your assumptions explicitly before typing: candidate approaches, tradeoffs. If anything is confusing, ask rather than writing plausible-looking code.

## III. Simplicity

Write the minimum code that solves the problem in front of you *now* — no speculative future-proofing. Resist premature abstraction, skip error handling for impossible scenarios, hardcode until configuration is explicitly required.

## IV. Surgical changes

Keep the diff as tiny and localized as the task allows. Never touch code, comments, or formatting you weren't asked to touch; match existing style exactly. If a line was added just because "while I was in there…", revert it.

## V. Verification

Write a failing test first, watch it fail, then fix — that proves you solved the cause, not the symptom. Test behaviour that can actually break. Code that is hard to test is a design flaw, not an excuse to skip verification.

## VI. Goal-driven execution

Define a strict success criterion before writing code. For multi-step work, state the explicit plan up front so it can be audited before building.

## VII. Debugging

Investigate stack traces deeply instead of guessing, and reproduce the problem before changing code. Change one thing at a time; never paste a null-check over an unexpected `None` without finding why it is null. Establish what the system could **see** before diagnosing what it **did**.

## VIII. Dependencies

Treat every dependency as permanent code you do not control. Before adding a package, check whether the standard library or existing utilities can do it; if you add one, justify it in the manifest/PR.

## IX. Communication

Explain what you did and why; don't dump a raw block of code. Flag concerns and express uncertainty with precise language. Do not say "I think this should work."

## X. Common failure modes (catch yourself)

*Kitchen Sink* — rebuilding half the codebase for a minor task. *Optimistic Abstraction* — abstracting before a pattern has been copy-pasted twice. *Banana-Patch Refactor* — a quick fix that cascades errors and swallows 500s. *Runaway Refactor* — a fix that ripples unnecessarily across files.
