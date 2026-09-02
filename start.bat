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

REM Resolve the port once (PORT -^> RETRODB_PORT -^> config default) so the
REM banner and the browser-open URL below match what app.py actually binds.
REM On a malformed value server_port.py prints the reason and produces no
REM output, so SERVER_PORT stays undefined and we stop here.
set SERVER_PORT=
for /f "delims=" %%p in ('%PYTHON% server_port.py') do set SERVER_PORT=%%p
if not defined SERVER_PORT (
    echo ERROR: Could not determine the server port ^(see the message above^).
    pause
    exit /b 1
)

REM Check if Flask is installed
%PYTHON% -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo Running the installer...
    REM install.py prefers `--require-hashes -r requirements.lock`; a bare
    REM `pip install -r requirements.txt` here defeated that ^(Pass 59.12^).
    %PYTHON% install.py
    REM `if errorlevel 1`, not `%errorlevel%` — inside a parenthesised block
    REM the latter expands at parse time, i.e. before install.py has run.
    if errorlevel 1 (
        echo ERROR: dependency install failed - see the output above.
        pause
        exit /b 1
    )
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
echo   Local:   http://localhost:%SERVER_PORT%
echo   Press Ctrl+C to stop the server
echo ========================================================
echo.

REM Open the browser (returns immediately; server still runs in foreground).
start "" http://localhost:%SERVER_PORT%

%PYTHON% app.py
pause
