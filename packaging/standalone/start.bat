@echo off
REM =============================================================================
REM RetroDB - Standalone launcher (Windows)
REM =============================================================================
REM Double-click to start.  The bundle ships no .py files, so this must not
REM invoke Python — it only runs the retrodb.exe next to it, which resolves its
REM own port and opens the browser.
REM =============================================================================

title RetroDB
cd /d "%~dp0"

if not exist "retrodb.exe" (
    echo ERROR: retrodb.exe is missing from %~dp0.
    echo        Re-extract the Standalone zip, keeping the folder intact.
    pause
    exit /b 1
)

retrodb.exe
pause
