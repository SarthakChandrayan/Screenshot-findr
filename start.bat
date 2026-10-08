@echo off
rem Double-click to run Screenshot Findr. First run (and each new version) sets things up.
cd /d "%~dp0"
set VERSION=0.3.0
if not exist .venv (
    echo Setting up Screenshot Findr for the first time...
    py -3 -m venv .venv || python -m venv .venv || (echo Python 3 is required: https://www.python.org/downloads/ & pause & exit /b 1)
)
if not exist ".venv\installed-%VERSION%" (
    echo Installing Screenshot Findr %VERSION%...
    .venv\Scripts\python -m pip install --upgrade pip >nul
    rem "smart" adds search by meaning; fall back to the basic install if it can't be installed
    .venv\Scripts\python -m pip install -e ".[smart]" || .venv\Scripts\python -m pip install -e . || (pause & exit /b 1)
    echo.> ".venv\installed-%VERSION%"
)
.venv\Scripts\python -m screenshot_findr %*
pause
