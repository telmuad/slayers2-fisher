@echo off
cd /d "%~dp0"
rem One-time setup: a private Python environment in .venv with the
rem requirements, then the "Slayers 2 Fisher" shortcuts. Safe to run again.

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.11 or newer was not found.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
    echo then run setup.bat again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment in .venv ...
    %PY% -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -m pip --version >nul 2>nul || ".venv\Scripts\python.exe" -m ensurepip --upgrade || goto :failed
echo Installing the requirements ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :failed
".venv\Scripts\python.exe" make_shortcut.py || goto :failed

echo.
echo Setup done. Start the app with the "Slayers 2 Fisher" shortcut and click Calibrate.
pause
exit /b 0

:failed
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
