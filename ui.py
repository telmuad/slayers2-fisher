"""
The app window (tkinter): status, Start/Pause, Settings and the Setup menu.

Tkinter must run on the main thread, so the bot runs in a worker thread and
this window polls its status 10 times a second. Calibration, preview and the
simulator run as separate processes (they need their own console or OpenCV
windows); while one runs, the bot and its hotkeys are switched off so the
calibration's snapshot key can't start fishing.

Avoid clicking this window while fishing: that takes focus away from Roblox,
which pauses the bot until you click back into the game.
"""
from __future__ import annotations

import copy
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from bot import FishingBot, Status
from capture import ScreenCapture
from config import (APP_DIR, DEBUG_DIR, LOG_DIR, VERSION, calibration_problem, key_label, load_config,
                    save_config)
from hotkeys import start_hotkeys
from notifier import Notifier

log = logging.getLogger(__name__)

STATE_COLORS = {
    "Casting": "#4aa3ff",
    "Waiting": "#9aa4b2",
    "Minigame": "#f5c542",
    "Collecting": "#4cd07d",
    "Paused": "#ff8a4c",
    "Stopped": "#ff5c5c",
    "Setup": "#c792ea",
}
BG, FG, MUTED, BUTTON = "#1b1e24", "#e8eaed", "#9aa4b2", "#2f3440"


def tool_command(*args: str) -> list[str]:
    """This program again, with command-line options (works for the .exe too)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(APP_DIR / "main.py"), *args]


def current_monitors() -> list[list[int]]:
    return [[m["left"], m["top"], m["width"], m["height"]] for m in ScreenCapture().monitors()[1:]]


class App:
    def __init__(self, cfg: dict, debug: bool = False):
        self.cfg = cfg
        self.debug_flag = debug                  # --debug on the command line
        self.bot: FishingBot | None = None
        self.worker: threading.Thread | None = None
        self.status: Status | None = None        # kept across reloads so the counts survive
        self.problem: str | None = None          # why the bot can't run (not calibrated...)
        self.listener = None
        self.hotkeys_on = True
        self.quitting = threading.Event()
        self.tool: subprocess.Popen | None = None
        self.tool_name = ""
        self.settings = None
        self._build_window()
        self._start_bot()
        self._start_hotkeys()
        self._refresh()

    # -- window ---------------------------------------------------------------------
    def _build_window(self):
        self.root = tk.Tk()
        self.root.title(f"Slayers 2 Auto-Fisher {VERSION}")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.quit("window closed"))

        pad = {"padx": 10, "sticky": "w"}
        self.state_var, self.detail_var = tk.StringVar(), tk.StringVar()
        self.stats_var, self.fps_var, self.hint_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.state_label = tk.Label(self.root, textvariable=self.state_var, bg=BG, fg=FG,
                                    font=("Segoe UI", 14, "bold"))
        self.state_label.grid(row=0, column=0, columnspan=3, pady=(8, 0), **pad)
        tk.Label(self.root, textvariable=self.detail_var, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                 wraplength=290, justify="left").grid(row=1, column=0, columnspan=3, **pad)
        tk.Label(self.root, textvariable=self.stats_var, bg=BG, fg=FG, justify="left",
                 font=("Consolas", 10)).grid(row=2, column=0, columnspan=3, pady=(6, 0), **pad)
        tk.Label(self.root, textvariable=self.fps_var, bg=BG, fg=MUTED,
                 font=("Consolas", 9)).grid(row=3, column=0, columnspan=3, **pad)

        bar = tk.Frame(self.root, bg=BG)
        bar.grid(row=4, column=0, columnspan=3, padx=8, pady=(8, 0), sticky="w")
        style = {"bg": BUTTON, "fg": FG, "activebackground": "#3a404c", "activeforeground": FG,
                 "relief": "flat", "bd": 0, "padx": 10, "pady": 3, "font": ("Segoe UI", 9),
                 "cursor": "hand2"}
        self.main_button = tk.Button(bar, width=9, command=self._main_button, **style)
        self.main_button.pack(side="left", padx=2)
        tk.Button(bar, text="Settings", command=self.open_settings, **style).pack(side="left", padx=2)
        self.setup_button = tk.Menubutton(bar, text="Setup ▾", **style)
        menu = tk.Menu(self.setup_button, tearoff=False)
        menu.add_command(label="Calibrate everything...", command=lambda: self.run_tool("Calibrating", "--calibrate"))
        menu.add_command(label="Redo the collect prompt...",
                         command=lambda: self.run_tool("Calibrating", "--calibrate-collect"))
        menu.add_command(label="Save the camera view...",
                         command=lambda: self.run_tool("Saving the camera view", "--save-camera"))
        menu.add_separator()
        menu.add_command(label="Preview detection (no input)...",
                         command=lambda: self.run_tool("Preview", "--preview"))
        menu.add_command(label="Simulator...", command=lambda: self.run_tool("Simulator", "--simulate"))
        menu.add_separator()
        menu.add_command(label="Open the log folder", command=lambda: self._open_folder(LOG_DIR))
        menu.add_command(label="Open the debug image folder", command=lambda: self._open_folder(DEBUG_DIR))
        self.setup_button.configure(menu=menu)
        self.setup_button.pack(side="left", padx=2)

        # Fishing or quest mode, switchable here or in Settings
        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "fishing"))
        self.mode_button = tk.Menubutton(bar, width=8, **style)
        mode_menu = tk.Menu(self.mode_button, tearoff=False)
        for value, label in (("fishing", "Fishing"), ("quests", "Quests")):
            mode_menu.add_radiobutton(label=label, value=value, variable=self.mode_var,
                                      command=self._mode_changed)
        self.mode_button.configure(menu=mode_menu)
        self.mode_button.pack(side="left", padx=2)

        tk.Label(self.root, textvariable=self.hint_var, bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).grid(row=5, column=0, columnspan=3, pady=(6, 8), **pad)

        # Top-right corner of the primary screen, out of the way.
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 300)
        self.root.geometry(f"+{self.root.winfo_screenwidth() - w - 20}+40")

    def _mode_changed(self):
        mode = self.mode_var.get()
        if mode == self.cfg.get("mode"):
            return
        self._suspend()
        cfg = copy.deepcopy(self.cfg)
        cfg["mode"] = mode
        save_config(cfg)
        log.info("Mode: %s", mode)
        self._resume(cfg)

    def _open_folder(self, path):
        path.mkdir(exist_ok=True)
        os.startfile(path)

    # -- bot lifecycle ----------------------------------------------------------------
    def _start_bot(self):
        self.mode_var.set(self.cfg.get("mode", "fishing"))
        # Quest mode reads everything by its text, so it doesn't need the fishing calibration.
        self.problem = (None if self.cfg.get("mode") == "quests"
                        else calibration_problem(self.cfg, current_monitors()))
        self.hint_var.set("{} start   {} pause   {} quit".format(
            *(key_label(self.cfg, a) for a in ("start", "pause", "quit")))
            + ("   Discord on" if Notifier.configured(self.cfg) else "")
            + ("   [debug images]" if self._debug else ""))
        if self.problem:
            log.info("Not starting the bot: %s", self.problem)
            return
        self.bot = FishingBot(self.cfg, debug=self._debug, status=self.status, notifier=Notifier(self.cfg))
        self.status = self.bot.status
        self.status.set("Stopped", f"Press {key_label(self.cfg, 'start')} in Roblox to start")
        self.worker = threading.Thread(target=self.bot.run, name="bot", daemon=True)
        self.worker.start()
        log.info("Ready. Click into Roblox, equip your rod, then press %s to start.", key_label(self.cfg, "start"))

    @property
    def _debug(self) -> bool:
        return self.debug_flag or bool(self.cfg["debug"]["enabled"])

    def _stop_bot(self):
        bot, self.bot = self.bot, None
        if bot is None:
            return
        bot.quit("reloading", notify=False)
        if self.worker:
            self.worker.join(timeout=3)
        bot.inp.release_all(force=True)
        bot.notify.close(timeout=5 if self.quitting.is_set() else 1)

    def _start_hotkeys(self):
        if self.listener:
            self.listener.stop()
        k = self.cfg["hotkeys"]
        self.listener = start_hotkeys({k["start"]: lambda: self._hotkey("start"),
                                       k["pause"]: lambda: self._hotkey("pause"),
                                       k["quit"]: lambda: self._hotkey("quit")})

    def _hotkey(self, action: str):
        """Runs on the hotkey thread: only thread-safe calls here."""
        if not self.hotkeys_on:
            return
        if action == "quit":
            self.quit(key_label(self.cfg, "quit"))
        elif self.bot is not None:
            self.bot.start() if action == "start" else self.bot.pause()

    def _main_button(self):
        if self.problem:
            self.run_tool("Calibrating", "--calibrate")
        elif self.bot is not None:
            if self.bot.running.is_set():
                self.bot.pause("Pause button")
            else:
                self.bot.start()    # it waits until you click into Roblox

    def quit(self, reason: str):
        """Thread-safe: the window closes on its next refresh."""
        if self.bot is not None:
            self.bot.quit(reason)
        self.quitting.set()

    # -- settings and tools -----------------------------------------------------------
    def _suspend(self):
        """Stop the bot and ignore hotkeys (while settings are open or a tool runs)."""
        self.hotkeys_on = False
        self._stop_bot()

    def _resume(self, cfg: dict | None = None):
        self.cfg = cfg if cfg is not None else load_config()
        self._start_hotkeys()
        self._start_bot()
        self.hotkeys_on = True

    def open_settings(self):
        if self.settings is not None or self.tool is not None:
            return
        from settings_ui import SettingsWindow
        self._suspend()
        mon = self.cfg.get("monitor")
        if self.problem:
            note = f"{self.problem} Use Setup > Calibrate everything in the main window."
        else:
            note = (f"Calibrated for a {mon[2]}x{mon[3]} screen. Screen positions and the camera view "
                    "are set by calibration: use the Setup menu in the main window to redo them.")

        def saved(new_cfg):
            self.settings = None
            save_config(new_cfg)
            log.info("Settings saved")
            self._resume(new_cfg)

        def closed():
            self.settings = None
            self._resume(self.cfg)

        self.settings = SettingsWindow(self.root, copy.deepcopy(self.cfg), saved, closed, note)

    def run_tool(self, name: str, *args: str):
        if self.tool is not None or self.settings is not None:
            return
        self._suspend()
        try:
            self.tool = subprocess.Popen(tool_command(*args), cwd=str(APP_DIR))
        except OSError as e:
            messagebox.showerror("Couldn't start", str(e), parent=self.root)
            self._resume(self.cfg)
            return
        self.tool_name = name
        log.info("Started %s (%s)", name, " ".join(args))

    # -- refresh ----------------------------------------------------------------------
    def _refresh(self) -> None:
        if self.quitting.is_set() or (self.bot is not None and self.bot.quit_event.is_set()):
            self.root.destroy()      # quit key, failsafe corner, or window closed
            return
        if self.tool is not None and self.tool.poll() is not None:
            log.info("%s finished", self.tool_name)
            self.tool = None
            self._resume()           # calibration may have changed config.json
        self._show()
        self.root.after(100, self._refresh)

    def _show(self):
        busy_tool = self.tool is not None
        if busy_tool:
            state, detail = "Setup", f"{self.tool_name}... Follow the instructions in its window."
        elif self.settings is not None:
            state, detail = "Paused", "Settings are open"
        elif self.problem:
            state, detail = "Stopped", f"{self.problem} Click Calibrate to set the bot up for your screen."
        elif self.status is not None:
            snap = self.status.snapshot()
            state, detail = snap.state, snap.detail
        else:
            state, detail = "Stopped", ""
        self.state_var.set("Not calibrated" if self.problem and not busy_tool and self.settings is None
                           else state)
        self.state_label.configure(fg=STATE_COLORS.get(state, FG))
        self.detail_var.set(detail)

        quests = self.cfg.get("mode") == "quests"
        self.mode_button.configure(text=("Quests" if quests else "Fishing") + " ▾",
                                   state="disabled" if busy_tool or self.settings is not None else "normal")
        if self.status is not None:
            s = self.status.snapshot()
            if quests:
                lines = [f"Quests done: {s.quests:<4}", f"Lv {self.cfg['quests']['level']} crate quest"]
            else:
                lines = [f"Minigames: {s.minigames:<4} Collected: {s.catches:<4}",
                         f"No prompt: {s.no_prompt:<4} Recasts:   {s.recasts:<4}"]
            if s.failed and not quests:
                lines.append(f"Collect failed: {s.failed}")
            self.stats_var.set("\n".join(lines))
            busy = s.state in ("Waiting", "Minigame") and self.bot is not None
            self.fps_var.set(f"{s.fps:5.1f} fps" if busy else "  --  fps")
        else:
            self.stats_var.set("Minigames: 0    Collected: 0\nNo prompt: 0    Recasts:   0")
            self.fps_var.set("  --  fps")

        locked = busy_tool or self.settings is not None
        if self.problem:
            text = "Calibrate"
        elif self.bot is not None and self.bot.running.is_set():
            text = "Pause"
        else:
            text = "Start"
        self.main_button.configure(text=text, state="disabled" if locked else "normal")
        self.setup_button.configure(state="disabled" if locked else "normal")

    # -- run ---------------------------------------------------------------------------
    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.quitting.set()
            self._stop_bot()
            if self.listener:
                self.listener.stop()
            if self.status is not None:
                s = self.status.snapshot()
                log.info("Session over: %d minigames, %d collected, %d without a prompt, "
                         "%d collect failures, %d recasts",
                         s.minigames, s.catches, s.no_prompt, s.failed, s.recasts)
