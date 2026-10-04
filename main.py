"""
Slayers 2 Auto-Fisher - entry point.

    python main.py                      open the app (status, Start/Pause, Settings, Setup menu)
    python main.py --calibrate          redo the whole calibration
    python main.py --calibrate-collect  redo only the collect-prompt step
    python main.py --save-camera        save the current camera view as the one to keep
    python main.py --preview            live detection view, sends no input
    python main.py --debug              open the app and save debug images
    python main.py --simulate           watch the bot play a simulated minigame

The app's Setup menu runs the others for you. Hotkeys while running: F6
start, F7 pause, F8 quit (change them in Settings). Emergency stop: shove the
mouse into the top-left corner of the screen.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

from config import DEFAULTS, LOG_DIR, calibration_problem, load_config
from window import make_dpi_aware

_own_console = False        # True when we opened a console window ourselves


def ensure_console(title: str) -> None:
    """
    Calibration and preview talk to you through a console. When started
    without one (the shortcut, the .exe, or the app's Setup menu), open one.
    """
    global _own_console
    if sys.stdout is not None:
        return
    kernel32 = ctypes.windll.kernel32
    if not kernel32.AllocConsole():
        return
    kernel32.SetConsoleTitleW(title)
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout
    sys.stdin = open("CONIN$", "r", encoding="utf-8")
    _own_console = True


def close_console() -> None:
    """Keep our own console open until the last message has been read."""
    if _own_console:
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, KeyboardInterrupt, OSError):
            pass


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    file_handler = RotatingFileHandler(LOG_DIR / "fishing_bot.log", maxBytes=1_000_000,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    if sys.stdout is not None:          # no console when started windowless (pythonw / the .exe)
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter(fmt, "%H:%M:%S"))
        root.addHandler(console)


def show_message(title: str, text: str, error: bool = False) -> None:
    """A Windows message box - the only way to tell the user something without a console."""
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-fisher for Slayers 2 (Roblox)")
    parser.add_argument("--calibrate", action="store_true", help="redo the calibration")
    parser.add_argument("--calibrate-collect", action="store_true",
                        help="redo only the collect-prompt calibration")
    parser.add_argument("--preview", action="store_true",
                        help="show live detection without sending input")
    parser.add_argument("--debug", action="store_true", help="save debug images to ./debug")
    parser.add_argument("--simulate", action="store_true",
                        help="watch the bot play a simulated minigame (no input sent)")
    parser.add_argument("--record", metavar="FILE.mp4",
                        help="with --simulate: save a video instead of showing a window")
    parser.add_argument("--seconds", type=float, default=60,
                        help="with --record: how long to record (default 60)")
    parser.add_argument("--save-camera", action="store_true",
                        help="save the current Roblox camera view as the one to keep")
    args = parser.parse_args()

    if args.calibrate or args.calibrate_collect or args.preview or args.save_camera:
        ensure_console("Slayers 2 Auto-Fisher - setup")

    # Must happen before any window or screenshot, so pixels line up.
    make_dpi_aware()
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)   # 1 ms sleep precision for a steady fps
    except OSError:
        pass
    setup_logging()

    cfg = load_config()
    from hotkeys import check_hotkeys
    try:
        check_hotkeys(cfg)
    except SystemExit as e:
        # A hand-edited config.json with a bad key: fall back to the defaults
        # so the app still opens and the keys can be fixed in Settings.
        logging.getLogger("main").warning("%s Using the default hotkeys.", e)
        if sys.stdout is None:
            show_message("Slayers 2 Auto-Fisher", f"{e}\n\nUsing F6 / F7 / F8 until you change them in Settings.")
        cfg["hotkeys"] = copy.deepcopy(DEFAULTS["hotkeys"])

    if args.simulate:
        from simulator import run_simulation
        run_simulation(cfg, record=args.record, seconds=args.seconds)
        return
    if args.save_camera:
        from calibration import save_camera_view
        save_camera_view(cfg)
        return

    from ui import App, current_monitors
    problem = calibration_problem(cfg, current_monitors())
    if args.calibrate or args.calibrate_collect or (args.preview and problem):
        from calibration import run_calibration
        if problem and args.calibrate_collect:
            print(f"\n{problem} Doing the whole calibration first.")
        cfg = run_calibration(cfg, only_collect=args.calibrate_collect and not problem)
        if not args.preview:
            print("Done. Close this window and press Start in the app.")
            return
    if args.preview:
        from debugging import run_preview
        run_preview(cfg)
        return

    app = App(cfg, debug=args.debug)
    signal.signal(signal.SIGINT, lambda *_: app.quit("Ctrl+C"))
    app.run()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if isinstance(e.code, str):
            if _own_console:
                print(e.code)
            elif sys.stdout is None:          # e.g. a broken config.json
                show_message("Slayers 2 Auto-Fisher", e.code, error=True)
        raise
    except Exception as e:
        logging.getLogger("main").exception("Crashed")
        if sys.stdout is None:          # windowless: nobody would see the traceback otherwise
            show_message("Slayers 2 Auto-Fisher - error",
                         f"The program stopped because of an error:\n\n{e}\n\nDetails are in logs\\fishing_bot.log",
                         error=True)
        elif _own_console:
            import traceback
            traceback.print_exc()
        raise
    finally:
        close_console()
