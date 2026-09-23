@echo off
REM ===========================================================================
REM  Run HY Motion Studio from the source code (no .exe needed).
REM
REM  First run: creates a small private Python environment in app\.venv and
REM  installs the window toolkit (PySide6) into it. Later runs start straight
REM  away. Needs Python 3.10-3.12 from python.org ("py" launcher).
REM ===========================================================================
setlocal
cd /d "%~dp0"
set "VENV=app\.venv\Scripts\python.exe"

if not exist "%VENV%" (
    echo Setting up for the first time - this takes a minute...
    py -3.11 -m venv app\.venv 2>nul || py -3 -m venv app\.venv || goto :nopython
    "%VENV%" -m pip install --upgrade pip >nul
    "%VENV%" -m pip install -r app\requirements.txt || goto :fail
)

start "" "app\.venv\Scripts\pythonw.exe" "app\HYMotionStudio.pyw"
exit /b 0

:nopython
echo.
echo [error] Python was not found. Install Python 3.11 from https://www.python.org
echo         (tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1

:fail
echo.
echo [error] Installing the requirements failed - see the messages above.
pause
exit /b 1
