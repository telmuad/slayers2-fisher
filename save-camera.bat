@echo off
cd /d "%~dp0"
rem Save the current Roblox camera view as the one the bot keeps.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py --save-camera
) else (
    python main.py --save-camera
)
pause
