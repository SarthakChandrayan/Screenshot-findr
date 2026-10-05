@echo off
rem Double-click to run Screenshot Findr. First run sets everything up.
cd /d "%~dp0"
if not exist .venv (
    echo Setting up Screenshot Findr for the first time...
    py -3 -m venv .venv || python -m venv .venv || (echo Python 3 is required: https://www.python.org/downloads/ & pause & exit /b 1)
    .venv\Scripts\python -m pip install --upgrade pip >nul
    .venv\Scripts\python -m pip install -e . || (pause & exit /b 1)
)
.venv\Scripts\python -m screenshot_findr %*
pause
