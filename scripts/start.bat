@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem PLS-regresjon startup script (Windows)
rem
rem Double-click this file from Explorer, or run it from any
rem working directory - it moves to the repo root itself. It will
rem create/reuse a local virtual environment, start the FastAPI
rem server, wait for it to respond, then open it in the browser.
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

echo [start.bat] Starting server on http://%HOST%:%PORT% ...
start "PLS-regresjon server" cmd /k ""%VENV_PY%" -m uvicorn backend.app:app --host %HOST% --port %PORT%"

rem --- Poll until the server responds, then open the browser. Timeout after ~30s. ---
set "READY=0"
for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://%HOST%:%PORT%/' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "READY=1"
        goto :server_ready
    )
    timeout /t 1 /nobreak >nul
)

:server_ready
if "%READY%"=="1" (
    echo [start.bat] Server is up. Opening browser ...
    start "" "http://%HOST%:%PORT%/"
) else (
    echo [start.bat] WARNING: Server did not respond within 30 seconds. Check the server window for errors.
)

endlocal
