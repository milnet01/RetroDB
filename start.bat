@echo off
REM =============================================================================
REM RETRODB - Windows Startup Script
REM =============================================================================
REM This script starts the RetroDB web application
REM Usage: Double-click start.bat or run from command prompt
REM =============================================================================

title RetroDB

echo.
echo ========================================================
echo   RetroDB - Retro Gaming ROM Library Manager
echo ========================================================
echo.

REM Check Python
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    python3 --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Python not found! Please install Python 3.8+ from python.org
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)
echo   OK: Python found

REM Check if Flask is installed
%PYTHON% -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    %PYTHON% -m pip install -r requirements.txt
)

REM Create directories if needed
if not exist database mkdir database
if not exist logs mkdir logs
if not exist data mkdir data
if not exist "static\images\boxart" mkdir "static\images\boxart"
if not exist "static\images\screenshots" mkdir "static\images\screenshots"
if not exist "static\images\systems" mkdir "static\images\systems"
if not exist "static\images\ratings" mkdir "static\images\ratings"

REM Build CSS
echo Building CSS bundle...
%PYTHON% build_css.py >nul 2>&1

echo.
echo ========================================================
echo   Starting RetroDB server...
echo   Local:   http://localhost:5000
echo   Press Ctrl+C to stop the server
echo ========================================================
echo.

REM Open the browser (returns immediately; server still runs in foreground).
start "" http://localhost:5000

%PYTHON% app.py
pause
