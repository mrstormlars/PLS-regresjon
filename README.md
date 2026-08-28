# PLS-regresjon

En enkel webapp for PLS-regresjon (Partial Least Squares): last opp et datasett i Excel- eller CSV-format, velg prediktor- og responskolonner, og få en tilpasset PLS-modell med diagnostikk (forklart varians, score-/loadingplott, RMSE/R², kryssvalidering).

- **Backend:** Python (FastAPI) — filparsing, PLS-tilpasning med scikit-learn.
- **Frontend:** ren HTML/CSS/JavaScript servert av backend.

## Status

Under utvikling — prosjektstruktur og agent-arbeidsflyt er etablert; se `CLAUDE.md` for regler og arkitektur.
