@echo off
cd /d "%~dp0"
rem Use the local virtual environment if there is one, otherwise the system Python.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
) else (
    python main.py %*
)
pause
