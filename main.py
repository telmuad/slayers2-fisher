"""
Slayers 2 Auto-Fisher - entry point.

    python main.py                      run the bot (calibrates first if needed)
    python main.py --calibrate          redo the whole calibration
    python main.py --calibrate-collect  redo only the collect-prompt step
    python main.py --preview            live detection view, sends no input
    python main.py --debug              run the bot and save debug images
    python main.py --simulate           watch the bot play a simulated minigame

Hotkeys while running: F6 start, F7 pause, F8 quit (change them in config.json).
Emergency stop: shove the mouse into the top-left corner of the screen.
"""
from __future__ import annotations

import argparse
import atexit
import ctypes
import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, calibration_problem, key_label, load_config
from window import make_dpi_aware


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    file_handler = RotatingFileHandler(LOG_DIR / "fishing_bot.log", maxBytes=1_000_000,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    if sys.stdout is not None:          # no console when started windowless (pythonw)
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

    # Must happen before any window or screenshot, so pixels line up.
    make_dpi_aware()
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)   # 1 ms sleep precision for a steady fps
    except OSError:
        pass
    setup_logging()
    log = logging.getLogger("main")

    cfg = load_config()
    from hotkeys import check_hotkeys
    check_hotkeys(cfg)
    if args.simulate:
        from simulator import run_simulation
        run_simulation(cfg, record=args.record, seconds=args.seconds)
        return
    if args.save_camera:
        from calibration import save_camera_view
        save_camera_view(cfg)
        return
    from capture import ScreenCapture
    monitors = [[m["left"], m["top"], m["width"], m["height"]] for m in ScreenCapture().monitors()[1:]]
    problem = calibration_problem(cfg, monitors)
    if problem and sys.stdout is None:
        # Calibration talks to you through a console, which a windowless start doesn't have.
        show_message("Slayers 2 Auto-Fisher",
                     f"{problem}\n\nDouble-click calibrate.bat first, then start the app again.")
        return
    if problem and not args.calibrate:
        print(f"\n{problem} Starting calibration.")
    if args.calibrate or args.calibrate_collect or problem:
        from calibration import run_calibration
        explicit = args.calibrate or args.calibrate_collect
        cfg = run_calibration(cfg, only_collect=args.calibrate_collect and not problem)
        if explicit:
            print("Done. Run 'python main.py' to start fishing.")
            return

    if args.preview:
        from debugging import run_preview
        run_preview(cfg)
        return

    from bot import FishingBot
    from hotkeys import start_hotkeys
    from ui import StatusWindow

    debug = args.debug or cfg["debug"]["enabled"]
    bot = FishingBot(cfg, debug=debug)
    atexit.register(bot.inp.release_all, force=True)
    signal.signal(signal.SIGINT, lambda *_: bot.quit("Ctrl+C"))

    keys = cfg["hotkeys"]
    listener = start_hotkeys({keys["start"]: bot.start, keys["pause"]: bot.pause,
                              keys["quit"]: lambda: bot.quit(key_label(cfg, "quit"))})
    worker = threading.Thread(target=bot.run, name="bot", daemon=True)
    worker.start()
    log.info("Ready. Click into Roblox, equip your rod, then press %s to start.", key_label(cfg, "start"))

    StatusWindow(bot, debug).run()      # blocks until quit

    if not bot.quit_event.is_set():
        bot.quit("status window closed")
    worker.join(timeout=2)
    bot.inp.release_all(force=True)
    listener.stop()
    s = bot.status.snapshot()
    log.info("Session over: %d minigames, %d collected, %d without a prompt, %d collect failures, %d recasts",
             s.minigames, s.catches, s.no_prompt, s.failed, s.recasts)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if sys.stdout is None and isinstance(e.code, str):     # e.g. a broken config.json
            show_message("Slayers 2 Auto-Fisher", e.code, error=True)
        raise
    except Exception as e:
        logging.getLogger("main").exception("Crashed")
        if sys.stdout is None:          # windowless: nobody would see the traceback otherwise
            show_message("Slayers 2 Auto-Fisher - error",
                         f"The bot stopped because of an error:\n\n{e}\n\nDetails are in logs\\fishing_bot.log", error=True)
        raise
