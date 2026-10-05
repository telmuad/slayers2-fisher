"""
Build the Windows app: dist/Slayers 2 Fisher/Slayers 2 Fisher.exe, zipped as
dist/Slayers2Fisher-<version>-windows.zip for a GitHub release.

Needs the build tools first (build.bat installs them):
    python -m pip install -r requirements-build.txt

It is a folder build (an .exe next to an _internal folder) rather than a
single .exe: it starts much faster and antivirus programs flag it far less.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
from config import VERSION  # noqa: E402

NAME = "Slayers 2 Fisher"
BUILD, DIST = APP_DIR / "build", APP_DIR / "dist"

ZIP_README = f"""Slayers 2 Auto-Fisher {VERSION}

1. Extract this whole folder somewhere you keep programs (e.g. Documents).
   Don't run it from inside the zip: your settings would be lost.
2. Double-click "{NAME}.exe".
   Windows may say it "protected your PC" because the app isn't signed:
   click "More info", then "Run anyway".
3. Click Calibrate and follow the instructions, then press F6 in Roblox.

Your settings, logs and calibration are saved in this folder.
Full guide: https://github.com/telmuad/slayers2-fisher
"""


def feather_icon() -> Path:
    """The Tk feather (the icon the app window shows) as an .ico for the exe."""
    from icoextract import IconExtractor
    dlls = Path(sys.base_prefix).resolve() / "DLLs"
    found = sorted(dlls.glob("tcl9tk*.dll")) + sorted(dlls.glob("tk*.dll"))
    if not found:
        raise SystemExit(f"No Tk DLL found in {dlls}")
    out = BUILD / "feather.ico"
    BUILD.mkdir(exist_ok=True)
    IconExtractor(str(found[0])).export_icon(str(out), num=0)
    return out


def build() -> Path:
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        str(APP_DIR / "main.py"),
        "--name", NAME,
        "--windowed",                      # no console; calibration opens its own
        "--onedir",
        "--noconfirm", "--clean",
        "--icon", str(feather_icon()),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        # pynput picks its Windows backend at run time, so PyInstaller can't see it
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--exclude-module", "pytesseract",
        # Windows text recognition (quest mode): loaded inside functions
        "--collect-submodules", "winrt",
    ])
    return DIST / NAME


def make_zip(folder: Path) -> Path:
    (folder / "README.txt").write_text(ZIP_README, encoding="utf-8")
    shutil.copy(APP_DIR / "LICENSE", folder / "LICENSE.txt")
    out = DIST / f"Slayers2Fisher-{VERSION}-windows.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(folder))
    return out


if __name__ == "__main__":
    folder = build()
    leftovers = [p.name for p in folder.iterdir() if p.name in ("config.json", "logs", "templates", "debug")]
    if leftovers:
        raise SystemExit(f"Refusing to zip personal files: {leftovers}")
    z = make_zip(folder)
    print(f"\nBuilt {folder / (NAME + '.exe')}\nZipped {z} ({z.stat().st_size / 1e6:.0f} MB)")
