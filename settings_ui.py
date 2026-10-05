"""
Settings window: every setting in config.json, editable without opening the file.

The window is built from FIELDS below (one entry per setting: where it lives
in the config, a label, a short explanation and the allowed range), so a new
setting only needs a new line there. Values filled in by calibration (screen
positions, camera measurements) aren't listed: use the Setup menu for those.
"""
from __future__ import annotations

import copy
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import DEFAULTS
from hotkeys import check_hotkeys
from notifier import Message, post, valid_webhook

BG, PANEL, FG, MUTED, ACCENT = "#1b1e24", "#242831", "#e8eaed", "#9aa4b2", "#4aa3ff"


@dataclass
class Field:
    path: tuple[str, ...]       # where it lives in the config, e.g. ("timing", "bite_timeout_s")
    label: str
    help: str = ""
    kind: str = "float"         # float, int, bool, str, list, key, file, webhook, choice
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()         # for "choice": ((value, label), ...)

    def label_for(self, value) -> str:
        return next((lab for v, lab in self.choices if v == value), str(value))


def F(path: str, label: str, help: str = "", kind: str = "float", lo=None, hi=None, choices=()) -> Field:
    return Field(tuple(path.split(".")), label, help, kind, lo, hi, tuple(choices))


# (tab, [(section, [fields])])
TABS: list[tuple[str, list[tuple[str, list[Field]]]]] = [
    ("General", [
        ("Mode", [
            F("mode", "What the bot does",
              "Fishing: casts, plays the minigame and collects. Quests: does Angler Runo's crate "
              "quest with the fish you have. You can also switch in the main window.", "choice",
              choices=(("fishing", "Fishing"), ("quests", "Quests"))),
        ]),
        ("Hotkeys", [
            F("hotkeys.start", "Start / resume", "Also takes the snapshots during calibration.", "key"),
            F("hotkeys.pause", "Pause", "Lets go of everything. Also skips a calibration step.", "key"),
            F("hotkeys.quit", "Quit", "Stops the bot and closes the app.", "key"),
        ]),
        ("Camera", [
            F("camera.enabled", "Keep the camera on the saved view",
              "Each time you press start, put the camera back if it moved. Never between catches.", "bool"),
            F("camera.tolerance_px", "Allowed camera drift (px)",
              "How far off the view may be, on average, before it is reset.", "int", 5, 1000),
            F("camera.tolerance_deg", "Direction accuracy (degrees)",
              "How exactly the camera direction is lined up when resetting.", "float", 0.1, 20),
            F("camera.min_points", "Matched points needed",
              "Points that must match the saved view to trust a comparison.", "int", 5, 1000),
        ]),
        ("Debug", [
            F("debug.enabled", "Save debug images",
              "Saves what the bot sees to the debug folder while it fishes.", "bool"),
            F("debug.save_every_n_frames", "Minigame: save every Nth frame", "", "int", 1, 1000),
            F("debug.save_waiting_every_s", "Waiting for a bite: save every (s)", "", "float", 0.1, 600),
            F("debug.max_images", "Keep at most (images)", "The oldest are deleted past this.", "int", 10, 100000),
        ]),
        ("Roblox window", [
            F("window.process_names", "Roblox program names",
              "Comma separated. The bot only sends input while one of these is the focused window.", "list"),
            F("window.title", "Window title", "Only checked for the Microsoft Store version of Roblox.", "str"),
        ]),
    ]),
    ("Fishing", [
        ("Casting", [
            F("timing.bite_timeout_s", "Recast if no bite after (s)", "", "float", 3, 600),
            F("timing.cast_click_hold_s", "Cast click length (s)", "", "float", 0.01, 2),
            F("timing.cast_snap_to_water", "Move the cast onto water",
              "If the cast spot isn't water (the camera moved), click the nearest water instead.", "bool"),
            F("timing.cast_search_radius_px", "Look for water within (px)", "", "int", 0, 5000),
            F("timing.cast_water_margin_px", "Stay this far from the dock edge (px)", "", "int", 0, 1000),
            F("timing.reel_in_before_recast", "Reel in before recasting",
              "Turn on if, after a timeout, the first click reels the line in instead of casting.", "bool"),
        ]),
        ("Minigame", [
            F("timing.minigame_end_grace_s", "Bar gone for (s) = minigame over", "", "float", 0.05, 10),
            F("timing.minigame_max_s", "Give up on a minigame after (s)", "", "float", 5, 1200),
            F("timing.control_fps", "Control rate (fps)", "How often the minigame is checked and steered.",
              "int", 10, 240),
            F("timing.poll_fps", "Detection rate while waiting (fps)", "", "int", 1, 120),
        ]),
        ("Collecting", [
            F("timing.collect_appear_timeout_s", "Wait for a Collect prompt (s)",
              "Some caught items drift a while before their prompt shows.", "float", 0, 60),
            F("timing.collect_max_hold_s", "Never hold T longer than (s)", "", "float", 0.5, 60),
            F("timing.collect_gone_confirm_s", "Prompt missing for (s) = collected", "", "float", 0.05, 10),
            F("timing.after_collect_delay_s", "Wait after collecting (s)",
              "Lets the catch animation finish before casting again.", "float", 0, 30),
        ]),
        ("Random pauses", [
            F("timing.delay_min_s", "Pause between steps, min (s)", "", "float", 0, 30),
            F("timing.delay_max_s", "Pause between steps, max (s)", "", "float", 0, 30),
        ]),
    ]),
    ("Minigame", [
        ("Controller (positions are a fraction of the bar's height)", [
            F("controller.gain", "Gain", "How hard it reacts to distance from the target. Higher = snappier.",
              "float", 0, 1000),
            F("controller.prediction_s", "Look-ahead (s)", "Predicts this far ahead using the box's speed.",
              "float", 0, 3),
            F("controller.braking", "Braking", "Room the box needs to stop, per speed squared.", "float", 0, 10),
            F("controller.auto_braking", "Learn braking while playing", "", "bool"),
            F("controller.dead_zone", "Dead zone", "Errors smaller than this are ignored.", "float", 0, 0.5),
            F("controller.hover_duty", "Hover duty", "Share of the time to hold the click to stay still.",
              "float", 0, 1),
            F("controller.pwm_period_s", "Feathering period (s)", "Length of one hold/release cycle.",
              "float", 0.005, 1),
            F("controller.velocity_smoothing", "Speed smoothing", "0 = raw, 0.9 = very smooth but laggy.",
              "float", 0, 0.99),
            F("controller.target_offset", "Target offset", "Aim above (+) or below (-) the zone centre.",
              "float", -0.5, 0.5),
            F("controller.box_lost_hold_s", "Coast when the box is lost (s)", "", "float", 0, 5),
        ]),
    ]),
    ("Quests", [
        ("Angler Runo's crate quest", [
            F("quests.level", "Which quest", "", "choice",
              choices=((45, "Lv 45: Ill fill your crates"), (60, "Lv 60: Ill land the good catch"))),
            F("quests.cooldown_s", "Wait after handing in (s)",
              "The game's cooldown between quests is 10 s.", "float", 0, 600),
            F("quests.load_hold_s", "Hold T on the crate for (s)",
              "Long enough for all your fish to go in.", "float", 0.3, 15),
        ]),
        ("Names on screen (only change these if the game renames them)", [
            F("quests.npc_name", "Quest giver", "", "str"),
            F("quests.crate_name", "Crate", "", "str"),
            F("quests.max_dialogue_clicks", "Give up on a conversation after (clicks)", "", "int", 3, 100),
        ]),
    ]),
    ("Notifications", [
        ("Discord webhook", [
            F("notifications.webhook_url", "Webhook URL",
              "In Discord: open a channel's settings > Integrations > Webhooks > New Webhook > "
              "Copy Webhook URL, and paste it here. Leave empty to turn notifications off.", "webhook"),
            F("notifications.username", "Name shown in Discord", "", "str"),
            F("notifications.ping_user_id", "Your Discord user ID (optional)",
              "To be @mentioned on alerts, so your phone buzzes. In Discord: Settings > Advanced > "
              "Developer Mode on, then right-click your name > Copy User ID.", "str"),
        ]),
        ("Messages", [
            F("notifications.on_catch", "Every catch", "Each catch collected with T.", "bool"),
            F("notifications.on_quest", "Every finished quest",
              "Running out of fish for a quest always sends an alert.", "bool"),
            F("notifications.catch_picture", "With a picture of the catch",
              "A close-up of the item and its Collect prompt.", "bool"),
            F("notifications.on_no_prompt", "Minigames without a Collect prompt",
              "Caught straight into your inventory, or the fish escaped.", "bool"),
            F("notifications.on_start_stop", "Started / paused / stopped", "", "bool"),
            F("notifications.summary_every_min", "Status update every (minutes)",
              "Counts and catch rate while the bot runs. 0 = off.", "int", 0, 1440),
            F("notifications.screenshots", "Add a screenshot to status updates and alerts",
              "A picture of the Roblox screen, so you can see what's going on.", "bool"),
        ]),
        ("Alerts (with a ping, if your user ID is set). 0 = off", [
            F("notifications.alert_idle_min", "Nothing hooked for (minutes)", "", "int", 0, 1440),
            F("notifications.alert_unfocused_min", "Roblox not focused for (minutes)",
              "For example if Roblox crashed, disconnected or another window popped up.", "int", 0, 1440),
            F("notifications.alert_recasts", "Casts in a row without a bite", "", "int", 0, 1000),
        ]),
    ]),
    ("Detection", [
        ("Collect prompt", [
            F("detection.require_collect_word", "Only press T after finding the word \"Collect\"",
              "Keeps the bot from pressing T on other prompts, like the rod shop's \"Purchase\".", "bool"),
            F("detection.word_threshold", "\"Collect\" match score needed", "", "float", 0, 1),
            F("detection.word_keep_threshold", "Score accepted while holding T", "", "float", 0, 1),
            F("detection.prompt_follow_px", "Follow a drifting prompt within (px)", "", "int", 0, 5000),
            F("detection.template_threshold", "T circle score needed", "", "float", 0, 1),
            F("detection.template_keep_threshold", "T circle score while holding T", "", "float", 0, 1),
            F("detection.prompt_scale_min", "Smallest prompt size (x calibrated)", "", "float", 0.1, 10),
            F("detection.prompt_scale_max", "Largest prompt size (x calibrated)", "", "float", 0.1, 10),
            F("detection.prompt_scale_step", "Size search step", "", "float", 0.01, 1),
            F("detection.use_circle_fallback", "Shape-based T circle detector",
              "Only used if the \"Collect\" check above is off.", "bool"),
            F("detection.use_ocr", "Use OCR for \"Collect\" if Tesseract is installed", "", "bool"),
            F("detection.tesseract_cmd", "Tesseract program", "Leave empty if Tesseract is on your PATH.", "file"),
        ]),
        ("Fishing bar", [
            F("detection.edge_window_px", "Edge window (px)", "Pixels compared on each side of an edge.",
              "int", 1, 50),
            F("detection.edge_max_ratio", "Edge brightness ratio", "Inside must be at most this x as bright.",
              "float", 0, 1),
            F("detection.edge_min_step", "Edge brightness step", "...and at least this much darker (0-255).",
              "int", 0, 255),
            F("detection.edge_min_coverage", "Edge coverage", "", "float", 0, 1),
            F("detection.bar_min_edge_score", "Bar edge score", "", "float", 0, 1),
            F("detection.bar_min_height_frac", "Bar min height (share of area)", "", "float", 0, 1),
            F("detection.bar_min_aspect", "Bar min height/width", "", "float", 0, 100),
            F("detection.bar_size_tolerance", "Bar size tolerance", "", "float", 0, 5),
        ]),
        ("Target zone (HSV: hue 0-180, saturation and brightness 0-255)", [
            F("detection.zone_h_min", "Hue min", "", "int", 0, 180),
            F("detection.zone_h_max", "Hue max", "", "int", 0, 180),
            F("detection.zone_s_min", "Saturation min", "", "int", 0, 255),
            F("detection.zone_v_min", "Brightness min", "", "int", 0, 255),
            F("detection.zone_height_frac", "Zone height (share of bar)", "", "float", 0, 1),
        ]),
        ("White box", [
            F("detection.box_v_min", "Brightness min", "", "int", 0, 255),
            F("detection.box_s_max", "Saturation max", "", "int", 0, 255),
            F("detection.box_size_frac", "Box size (share of bar width)", "", "float", 0, 5),
            F("detection.size_tolerance", "Box/zone size tolerance", "", "float", 0, 5),
            F("detection.box_max_aspect", "Box max aspect ratio", "", "float", 1, 20),
        ]),
        ("Water", [
            F("detection.water_h_min", "Hue min", "", "int", 0, 180),
            F("detection.water_h_max", "Hue max", "", "int", 0, 180),
            F("detection.water_s_min", "Saturation min", "", "int", 0, 255),
            F("detection.water_v_min", "Brightness min", "", "int", 0, 255),
        ]),
    ]),
]

# Shown at the top of a tab
TAB_NOTES = {
    "Quests": "Stand between Angler Runo and his crate, close enough that both his Chat prompt "
              "and the crate's Load prompt can show up, and keep the quest list on the left of the "
              "screen visible. Then choose Quests mode and press start. When you run out of fish, "
              "it sends a Discord alert and pauses.",
    "Notifications": "Get Discord messages, for example on your phone, to check the bot is "
                     "working while you're away. Errors always send an alert.",
    "Minigame": "How the bot steers the white box. The defaults were measured in the real game; "
                "try changes in the Simulator (Setup menu) first, one value at a time.",
    "Detection": "How the bot recognises things on screen. Only change these if Preview detection "
                 "(Setup menu) shows something being missed or mistaken.",
}

# Tk key names -> config names (only keys that can't be typed into Roblox chat)
TK_KEYS = {f"F{i}": f"f{i}" for i in range(1, 25)}
TK_KEYS.update({"Insert": "insert", "Delete": "delete", "Home": "home", "End": "end",
                "Prior": "page_up", "Next": "page_down", "Pause": "pause",
                "Scroll_Lock": "scroll_lock", "Num_Lock": "num_lock", "Print": "print_screen"})


def _get(cfg: dict, path: tuple[str, ...]):
    for p in path:
        cfg = cfg[p]
    return cfg


def _set(cfg: dict, path: tuple[str, ...], value) -> None:
    for p in path[:-1]:
        cfg = cfg.setdefault(p, {})
    cfg[path[-1]] = value


def key_text(name: str) -> str:
    name = str(name).lower()
    return name.upper() if name[:1] == "f" and name[1:].isdigit() else name.replace("_", " ").title()


class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls with the mouse wheel."""

    def __init__(self, parent):
        super().__init__(parent, style="Panel.TFrame")
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Panel.TFrame")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # Every widget in the window has the window in its bindtags, so this
        # catches the wheel anywhere; only the tab under the mouse scrolls.
        self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):     # pointer over a popup menu or a closing window
            return
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            widget = widget.master


class SettingsWindow:
    def __init__(self, parent: tk.Tk, cfg: dict, on_save: Callable[[dict], None],
                 on_close: Callable[[], None], calibration_note: str):
        self.cfg = cfg
        self.on_save, self.on_close = on_save, on_close
        self.vars: dict[tuple[str, ...], tk.Variable] = {}
        self.fields: dict[tuple[str, ...], tuple[Field, int]] = {}    # field, tab index
        self.capturing: tuple[str, ...] | None = None
        self.key_buttons: dict[tuple[str, ...], ttk.Button] = {}

        self.win = tk.Toplevel(parent)
        self.win.title("Settings - Slayers 2 Auto-Fisher")
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)
        self.win.bind("<KeyPress>", self._on_key)
        self._style()

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        for index, (tab, sections) in enumerate(TABS):
            scroll = ScrollFrame(self.notebook)
            self.notebook.add(scroll, text=f"  {tab}  ")
            row = 0
            note = calibration_note if index == 0 else TAB_NOTES.get(tab)
            if note:
                ttk.Label(scroll.inner, text=note, style="Note.TLabel",
                          wraplength=560, justify="left").grid(row=row, column=0, columnspan=2,
                                                               sticky="w", padx=12, pady=(10, 0))
                row += 1
            for title, fields in sections:
                ttk.Label(scroll.inner, text=title, style="Section.TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(14, 4))
                row += 1
                for f in fields:
                    row = self._add_field(scroll.inner, f, row, index)
            scroll.inner.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self.win, style="Main.TFrame")
        buttons.pack(fill="x", padx=10, pady=10)
        ttk.Button(buttons, text="Reset this tab to defaults", command=self.reset_tab).pack(side="left")
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right", padx=6)

        self.win.geometry("660x640")
        self.win.minsize(520, 400)
        self.win.focus_force()

    # -- building ----------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self.win)
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, fieldbackground="#2f3440",
                    bordercolor="#3a404c", lightcolor=PANEL, darkcolor=PANEL, font=("Segoe UI", 9))
        s.configure("Main.TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(8, 4))
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])
        s.configure("Section.TLabel", foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        s.configure("Help.TLabel", foreground=MUTED, font=("Segoe UI", 8))
        s.configure("Note.TLabel", foreground=MUTED)
        s.configure("TButton", background="#2f3440", padding=(10, 4))
        s.map("TButton", background=[("active", "#3a404c")])
        s.configure("Accent.TButton", background="#2d6cdf", foreground="white")
        s.map("Accent.TButton", background=[("active", "#3b7cf0")])
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("TEntry", foreground=FG, insertcolor=FG)
        s.configure("TCombobox", fieldbackground="#2f3440", background="#2f3440", foreground=FG,
                    arrowcolor=FG, selectbackground="#2f3440", selectforeground=FG)
        s.map("TCombobox", fieldbackground=[("readonly", "#2f3440")], foreground=[("readonly", FG)],
              selectbackground=[("readonly", "#2f3440")], selectforeground=[("readonly", FG)])
        self.win.option_add("*TCombobox*Listbox.background", "#2f3440")
        self.win.option_add("*TCombobox*Listbox.foreground", FG)
        self.win.option_add("*TCombobox*Listbox.selectBackground", "#2d6cdf")
        s.configure("Vertical.TScrollbar", background="#3a404c", troughcolor=PANEL,
                    arrowcolor=MUTED, bordercolor=PANEL)
        s.map("Vertical.TScrollbar", background=[("active", "#4a5160")])

    def _add_field(self, parent, f: Field, row: int, tab: int) -> int:
        value = _get(self.cfg, f.path)
        self.fields[f.path] = (f, tab)
        pad = {"padx": (24, 8)}
        if f.kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(parent, text=f.label, variable=var).grid(row=row, column=0, columnspan=2,
                                                                      sticky="w", pady=(4, 0), **pad)
        else:
            ttk.Label(parent, text=f.label).grid(row=row, column=0, sticky="w", pady=(4, 0), **pad)
            if f.kind == "key":
                var = tk.StringVar(value=str(value).lower())
                btn = ttk.Button(parent, text=key_text(value), width=14,
                                 command=lambda p=f.path: self._start_capture(p))
                btn.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=(4, 0))
                self.key_buttons[f.path] = btn
            elif f.kind == "choice":
                var = tk.StringVar(value=f.label_for(value))
                ttk.Combobox(parent, textvariable=var, values=[lab for _, lab in f.choices],
                             state="readonly", width=32).grid(row=row, column=1, sticky="w",
                                                              padx=(0, 12), pady=(4, 0))
            elif f.kind == "webhook":
                var = tk.StringVar(value=str(value))
                box = ttk.Frame(parent, style="Panel.TFrame")
                ttk.Entry(box, textvariable=var, width=28, show="•").pack(side="left")
                self.test_button = ttk.Button(box, text="Test", command=self._test_webhook)
                self.test_button.pack(side="left", padx=4)
                box.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=(4, 0))
            elif f.kind == "file":
                var = tk.StringVar(value=str(value))
                box = ttk.Frame(parent, style="Panel.TFrame")
                ttk.Entry(box, textvariable=var, width=28).pack(side="left")
                ttk.Button(box, text="Browse...", command=lambda v=var: self._browse(v)).pack(side="left", padx=4)
                box.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=(4, 0))
            else:
                text = ", ".join(value) if f.kind == "list" else str(value)
                var = tk.StringVar(value=text)
                width = 34 if f.kind in ("str", "list") else 12
                ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="w",
                                                                      padx=(0, 12), pady=(4, 0))
        self.vars[f.path] = var
        row += 1
        if f.help:
            ttk.Label(parent, text=f.help, style="Help.TLabel", wraplength=560, justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", padx=(24, 12))
            row += 1
        return row

    def _browse(self, var: tk.StringVar):
        path = filedialog.askopenfilename(parent=self.win, title="Find tesseract.exe",
                                          filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        if path:
            var.set(path)

    # -- hotkey capture -------------------------------------------------------------
    def _start_capture(self, path):
        self._stop_capture()
        self.capturing = path
        self.key_buttons[path].configure(text="Press a key...")

    def _stop_capture(self):
        if self.capturing:
            self.key_buttons[self.capturing].configure(text=key_text(self.vars[self.capturing].get()))
        self.capturing = None

    def _on_key(self, event):
        if not self.capturing:
            return
        if event.keysym == "Escape":
            self._stop_capture()
            return "break"
        name = TK_KEYS.get(event.keysym)
        if name is None:
            messagebox.showinfo("Pick another key",
                                "Use F1-F24, Insert, Delete, Home, End, Page Up, Page Down, Pause, "
                                "Scroll Lock or Num Lock. Letters and numbers would also go to Roblox "
                                "(and its chat).", parent=self.win)
            return "break"
        self.vars[self.capturing].set(name)
        self._stop_capture()
        return "break"

    # -- webhook test ---------------------------------------------------------------
    def _test_webhook(self):
        n = {k: self.vars[("notifications", k)].get() for k in ("webhook_url", "username", "ping_user_id")}
        url = n["webhook_url"].strip()
        if not valid_webhook(url):
            messagebox.showerror("Webhook", "Paste a Discord webhook URL first "
                                 "(https://discord.com/api/webhooks/...).", parent=self.win)
            return
        ping = n["ping_user_id"].strip()
        self.test_button.configure(text="Sending...", state="disabled")

        def send():
            try:
                post(url, Message("Test message", "Notifications from the Slayers 2 Auto-Fisher work."
                                  + (" You'll be pinged on alerts." if ping else ""), ping=bool(ping)),
                     n["username"].strip(), ping)
                result = None
            except Exception as e:      # shown to the user, never raised
                result = getattr(e, "reason", None) or str(e)
            self.win.after(0, lambda: self._test_done(result))
        threading.Thread(target=send, daemon=True).start()

    def _test_done(self, error):
        if not self.win.winfo_exists():
            return
        self.test_button.configure(text="Test", state="normal")
        if error is None:
            messagebox.showinfo("Webhook", "Sent! Check your Discord channel.", parent=self.win)
        else:
            messagebox.showerror("Webhook", f"Couldn't send: {error}\n\nCheck the URL, and that the "
                                 "webhook wasn't deleted in Discord.", parent=self.win)

    # -- actions --------------------------------------------------------------------
    def _parse(self, f: Field, var: tk.Variable):
        """The value as it goes into config.json, or raise ValueError with a message."""
        raw = var.get()
        if f.kind == "bool":
            return bool(raw)
        if f.kind == "choice":
            for v, lab in f.choices:
                if lab == raw:
                    return v
            raise ValueError("pick one of the choices")
        if f.kind == "list":
            items = [x.strip() for x in str(raw).split(",") if x.strip()]
            if not items:
                raise ValueError("needs at least one name")
            return items
        if f.kind in ("str", "key", "file", "webhook"):
            text = str(raw).strip()
            if f.kind == "webhook" and text and not valid_webhook(text):
                raise ValueError("paste a Discord webhook URL (https://discord.com/api/webhooks/...), "
                                 "or leave it empty")
            if f.path == ("notifications", "ping_user_id") and text and not (text.isdigit() and 15 <= len(text) <= 21):
                raise ValueError("a Discord user ID is a long number, like 123456789012345678")
            return text
        try:
            number = float(str(raw).strip().replace(",", "."))
        except ValueError:
            raise ValueError("must be a number") from None
        if f.kind == "int":
            if number != int(number):
                raise ValueError("must be a whole number")
            number = int(number)
        if f.lo is not None and number < f.lo or f.hi is not None and number > f.hi:
            raise ValueError(f"must be between {f.lo:g} and {f.hi:g}")
        return number

    def _fail(self, path, message: str):
        f, tab = self.fields[path]
        self.notebook.select(tab)
        messagebox.showerror("Can't save", f"{f.label}: {message}", parent=self.win)

    def save(self):
        self._stop_capture()
        new = copy.deepcopy(self.cfg)
        for path, var in self.vars.items():
            f, _ = self.fields[path]
            try:
                _set(new, path, self._parse(f, var))
            except ValueError as e:
                self._fail(path, str(e))
                return
        t = new["timing"]
        if t["delay_min_s"] > t["delay_max_s"]:
            self._fail(("timing", "delay_min_s"), "can't be more than the max pause")
            return
        if new["detection"]["prompt_scale_min"] > new["detection"]["prompt_scale_max"]:
            self._fail(("detection", "prompt_scale_min"), "can't be more than the largest size")
            return
        try:
            check_hotkeys(new)
        except SystemExit as e:
            self._fail(("hotkeys", "start"), str(e).replace("config.json: ", ""))
            return
        if self.cfg["detection"]["require_collect_word"] and not new["detection"]["require_collect_word"]:
            if not messagebox.askyesno(
                    "Turn off the Collect check?",
                    "Without it the bot presses T on ANY prompt with a T, including the rod shop's "
                    "\"Purchase\" right next to the fishing spot.\n\nTurn it off anyway?",
                    icon="warning", parent=self.win):
                return
        self.win.destroy()
        self.on_save(new)

    def cancel(self):
        self.win.destroy()
        self.on_close()

    def reset_tab(self):
        _, sections = TABS[self.notebook.index("current")]
        for _, fields in sections:
            for f in fields:
                value = _get(DEFAULTS, f.path)
                var = self.vars[f.path]
                if f.kind == "list":
                    var.set(", ".join(value))
                elif f.kind == "choice":
                    var.set(f.label_for(value))
                elif f.kind == "key":
                    var.set(value)
                    self.key_buttons[f.path].configure(text=key_text(value))
                else:
                    var.set(value)
