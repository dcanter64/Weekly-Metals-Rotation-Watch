@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=py -3"
)
if not defined PYTHON_EXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo Python was not found. Install Python 3, or create a .venv in this folder.
    pause
    exit /b 1
)

%PYTHON_EXE% automation\metals_rotation_watch.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo The report failed. If the error mentions missing packages, run:
    echo   %PYTHON_EXE% -m pip install yfinance pandas numpy
)

echo.
pause
exit /b %RC%
