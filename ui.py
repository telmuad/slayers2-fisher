"""
Small always-on-top status window (tkinter).

Tkinter must run on the main thread, so the bot runs in a worker thread and
this window just polls its status 10 times a second. Avoid clicking this
window while fishing: that takes focus away from Roblox, which pauses the bot
until you click back into the game.
"""
from __future__ import annotations

import tkinter as tk

from bot import FishingBot
from config import key_label

STATE_COLORS = {
    "Casting": "#4aa3ff",
    "Waiting": "#9aa4b2",
    "Minigame": "#f5c542",
    "Collecting": "#4cd07d",
    "Paused": "#ff8a4c",
    "Stopped": "#ff5c5c",
}
BG, FG, MUTED = "#1b1e24", "#e8eaed", "#9aa4b2"


class StatusWindow:
    def __init__(self, bot: FishingBot, debug: bool):
        self.bot = bot
        self.root = tk.Tk()
        self.root.title("Slayers 2 Auto-Fisher")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", lambda: bot.quit("window closed"))

        pad = {"padx": 10, "pady": 1, "sticky": "w"}
        self.state_var = tk.StringVar()
        self.detail_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.fps_var = tk.StringVar()

        self.state_label = tk.Label(self.root, textvariable=self.state_var, bg=BG, fg=FG,
                                    font=("Segoe UI", 14, "bold"))
        self.state_label.grid(row=0, column=0, columnspan=3, padx=10, pady=(8, 0), sticky="w")
        tk.Label(self.root, textvariable=self.detail_var, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=3, **pad)
        tk.Label(self.root, textvariable=self.stats_var, bg=BG, fg=FG, justify="left",
                 font=("Consolas", 10)).grid(row=2, column=0, columnspan=3, padx=10, pady=(6, 0), sticky="w")
        tk.Label(self.root, textvariable=self.fps_var, bg=BG, fg=MUTED,
                 font=("Consolas", 9)).grid(row=3, column=0, columnspan=3, **pad)

        keys = [key_label(bot.cfg, a) for a in ("start", "pause", "quit")]
        hint = "{} start   {} pause   {} quit".format(*keys)
        if debug:
            hint += "   [DEBUG: saving images]"
        tk.Label(self.root, text=hint, bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).grid(row=4, column=0, columnspan=3, padx=10, pady=(6, 8), sticky="w")

        # Top-right corner of the primary screen, out of the way.
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 260)
        self.root.geometry(f"+{self.root.winfo_screenwidth() - w - 20}+40")
        self._refresh()

    def _refresh(self) -> None:
        if self.bot.quit_event.is_set():
            self.root.destroy()
            return
        s = self.bot.status.snapshot()
        self.state_var.set(s.state)
        self.state_label.configure(fg=STATE_COLORS.get(s.state, FG))
        self.detail_var.set(s.detail)
        lines = [f"Minigames: {s.minigames:<4} Collected: {s.catches:<4}",
                 f"No prompt: {s.no_prompt:<4} Recasts:   {s.recasts:<4}"]
        if s.failed:
            lines.append(f"Collect failed: {s.failed}")
        self.stats_var.set("\n".join(lines))
        busy = s.state in ("Waiting", "Minigame")
        self.fps_var.set(f"{s.fps:5.1f} fps" if busy else "  --  fps")
        self.root.after(100, self._refresh)

    def run(self) -> None:
        self.root.mainloop()
