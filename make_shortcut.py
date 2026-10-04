"""
Create the "Slayers 2 Fisher" shortcut, in this folder and on the Desktop.

The shortcut starts the bot with pythonw (no console window) and shows the Tk
feather icon. Everything is looked up on this PC, so run it again if you move
the folder or reinstall Python. setup.bat runs it for you.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
NAME = "Slayers 2 Fisher.lnk"


def find_pythonw() -> Path:
    venv = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    here = Path(sys.executable).with_name("pythonw.exe")
    if here.exists():
        return here
    raise SystemExit("pythonw.exe not found. Run setup.bat first.")


def find_icon(pythonw: Path) -> str:
    """The Tk DLL of this Python holds the feather icon (tk86t.dll, tcl9tk90.dll...)."""
    dlls = Path(sys.base_prefix).resolve() / "DLLs"
    for pattern in ("tcl9tk*.dll", "tk*.dll"):
        found = sorted(dlls.glob(pattern))
        if found:
            return f"{found[-1]},0"
    return f"{pythonw},0"


def _ps(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcut(folder: Path, pythonw: Path, icon: str) -> Path:
    path = folder / NAME
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps(path)}); "
              f"$s.TargetPath = {_ps(pythonw)}; $s.Arguments = 'main.py'; "
              f"$s.WorkingDirectory = {_ps(APP_DIR)}; $s.IconLocation = {_ps(icon)}; "
              "$s.Description = 'Slayers 2 Auto-Fisher'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True)
    return path


def desktop_folder() -> Path:
    # Asks Windows, so a Desktop moved into OneDrive is found too.
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "[Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def main() -> None:
    pythonw = find_pythonw()
    icon = find_icon(pythonw)
    print(f"Created {make_shortcut(APP_DIR, pythonw, icon)}")
    desktop = desktop_folder()
    if desktop.is_dir():
        print(f"Created {make_shortcut(desktop, pythonw, icon)}")


if __name__ == "__main__":
    main()
