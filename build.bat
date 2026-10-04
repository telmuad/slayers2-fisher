@echo off
cd /d "%~dp0"
rem Builds dist\Slayers 2 Fisher\Slayers 2 Fisher.exe and a zip for a release.
rem Run setup.bat first.
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip --version >nul 2>nul || ".venv\Scripts\python.exe" -m ensurepip --upgrade || goto :failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt || goto :failed
".venv\Scripts\python.exe" build_exe.py || goto :failed
pause
exit /b 0

:failed
echo.
echo Build failed - see the messages above.
pause
exit /b 1
