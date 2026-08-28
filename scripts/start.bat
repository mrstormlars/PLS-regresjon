@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem PLS-regresjon startup script (Windows)
rem
rem Double-click this file from Explorer, or run it from any
rem working directory - it moves to the repo root itself. It
rem creates/reuses a local virtual environment, then runs the
rem FastAPI server in the FOREGROUND of this console window: no
rem separate server window is opened, so Ctrl+C here (or closing
rem this window) stops the server. A small detached helper opens
rem the browser once the server responds.
rem ============================================================

rem --- Configuration: change host/port here only ---
set "HOST=127.0.0.1"
set "PORT=8000"

rem --- Move to the repo root (this script lives in <repo>\scripts) ---
cd /d "%~dp0.."

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [start.bat] No virtual environment found. Creating .venv ...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [start.bat] "py -3" is not available, trying "python" ...
        python -m venv .venv
    )
    if not exist "%VENV_PY%" (
        echo [start.bat] ERROR: Could not create a virtual environment. Install Python 3 and try again.
        exit /b 1
    )
    echo [start.bat] Installing dependencies ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -r requirements.txt
) else (
    rem Existing venv: fast path. Only (re)install if uvicorn is missing.
    "%VENV_PY%" -c "import uvicorn" >nul 2>&1
    if errorlevel 1 (
        echo [start.bat] Dependencies look incomplete. Installing ...
        "%VENV_PY%" -m pip install -r requirements.txt
    )
)

rem --- Detached helper: waits for the server to respond (~30s timeout,
rem     see open-browser-when-ready.ps1), then opens the browser. It runs
rem     with "start /b" so it stays attached to THIS console (no new
rem     window) and dies with it - Ctrl+C or closing this window kills the
rem     helper along with the server below. Prints nothing on timeout; the
rem     foreground uvicorn output already shows startup errors.
start /b "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0open-browser-when-ready.ps1" -Url "http://%HOST%:%PORT%/"

echo [start.bat] Starting server on http://%HOST%:%PORT% (Ctrl+C to stop) ...
"%VENV_PY%" -m uvicorn backend.app:app --host %HOST% --port %PORT%

endlocal
