# PLS-regresjon

En enkel webapp for PLS-regresjon (Partial Least Squares): last opp et datasett i Excel- eller CSV-format, velg prediktor- og responskolonner, og få en tilpasset PLS-modell med diagnostikk (forklart varians, score-/loadingplott, RMSE/R², kryssvalidering).

- **Backend:** Python (FastAPI) — filparsing, PLS-tilpasning med scikit-learn.
- **Frontend:** ren HTML/CSS/JavaScript servert av backend.

## Status

Under utvikling — prosjektstruktur og agent-arbeidsflyt er etablert; se `CLAUDE.md` for regler og arkitektur.

## Getting started

**Windows:** double-click `scripts\start.bat` (or run it from a terminal). It creates/reuses
a `.venv` virtual environment, installs `requirements.txt` if needed, then runs the server
directly in that same window and opens `http://127.0.0.1:8000` in your browser once it
responds. No separate server window is opened: press Ctrl+C in that window, or close it, to
stop the server.

**Manual (any OS):**

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 in your browser.
