"""
Configuration handling.

All settings live in ``config.json`` next to this file. The file is created on
first run with the defaults below, and calibration fills in the screen
positions. Any key missing from your config.json falls back to the default, so
it is safe to delete lines you don't care about.
"""
from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

VERSION = "1.3.0"

# Settings, logs and calibration images live next to the program: next to
# the .exe when packaged with PyInstaller, otherwise next to this file.
APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
CONFIG_PATH = APP_DIR / "config.json"
TEMPLATE_DIR = APP_DIR / "templates"
DEBUG_DIR = APP_DIR / "debug"
LOG_DIR = APP_DIR / "logs"

DEFAULTS: dict = {
    "mode": "fishing",          # "fishing", or "quests" (Angler Runo's crate quest, see quest.py)

    # ---- Filled in by calibration (absolute screen pixels) -----------------
    "calibrated": False,
    "monitor": None,            # [left, top, width, height] of the monitor Roblox was on
    "bar_region": None,         # [left, top, width, height] around the fishing bar
    "bar_expected": None,       # bar geometry seen during calibration (region-relative)
    "cast_point": None,         # [x, y] spot on the water to click when casting
    "collect_region": None,     # [left, top, width, height]; null = middle of the screen
    "collect_template": "templates/collect_t.png",         # the white "T" circle
    "collect_word_template": "templates/collect_word.png", # the word "Collect"

    # ---- Timing (seconds unless noted) --------------------------------------
    "timing": {
        "bite_timeout_s": 20.0,          # recast if the bar hasn't shown up by then
        "minigame_end_grace_s": 0.5,     # bar must be gone this long to count as ended
        "minigame_max_s": 90.0,          # safety cap on one minigame
        "collect_appear_timeout_s": 5.0, # wait this long for a Collect prompt (some items drift first)
        "collect_max_hold_s": 5.0,       # never hold T longer than this
        "collect_gone_confirm_s": 0.4,   # prompt must be missing this long to count as gone
        "delay_min_s": 0.3,              # random pause between steps (min)
        "delay_max_s": 0.8,              # random pause between steps (max)
        "cast_click_hold_s": 0.08,       # how long the cast click is held
        "cast_snap_to_water": True,      # if the cast spot isn't water (camera moved), use the nearest water
        "cast_search_radius_px": 500,    # how far from the cast spot to look for water
        "cast_water_margin_px": 60,      # keep the click this far from the dock edge
        "after_collect_delay_s": 1.5,    # let the catch animation finish before recasting
        "reel_in_before_recast": False,  # click once to reel in before recasting after a timeout
        "control_fps": 60,               # minigame control loop rate
        "poll_fps": 20                   # detection rate while waiting for the bar/prompt
    },

    # ---- Minigame controller -------------------------------------------------
    # Positions are measured as a fraction of the bar's height (0 = bottom, 1 = top).
    "controller": {
        "gain": 25.0,               # how hard to react to distance from the target
        "prediction_s": 0.30,       # look this far ahead using the box's velocity (the "D" part)
        "braking": 0.2,             # stopping distance per speed^2 (starting guess if auto_braking)
        "auto_braking": True,       # learn "braking" from how the box actually slows down
        "dead_zone": 0.0,           # ignore errors smaller than this (fraction of bar height)
        "hover_duty": 0.5,          # fraction of time to hold click to stay still
        "pwm_period_s": 0.05,       # length of one hold/release cycle when feathering
        "velocity_smoothing": 0.5,  # 0 = raw velocity, 0.9 = very smooth (but laggy)
        "target_offset": 0.0,       # aim above (+) or below (-) the zone centre, fraction of bar height
        "box_lost_hold_s": 0.3      # if the box vanishes, coast on the last estimate this long
    },

    # ---- Colour thresholds (OpenCV HSV: H 0-180, S 0-255, V 0-255) -----------
    "detection": {
        # The bar: its see-through inside is darker than the water beside it.
        "edge_window_px": 4,           # pixels compared on each side of an edge
        "edge_max_ratio": 0.85,        # inside must be <= this x as bright as outside
        "edge_min_step": 8,            # ... and at least this much darker (0-255)
        "edge_min_coverage": 0.2,      # an edge must show on this share of the region's rows
        "bar_min_edge_score": 0.5,     # share of the bar's own rows showing its edges
        "bar_min_height_frac": 0.35,   # bar must fill this much of the region's height
        "bar_min_aspect": 2.5,         # bar must be at least this many times taller than wide
        "bar_size_tolerance": 0.4,     # allowed width/position drift vs. calibration
        # Target zone: a see-through tint, yellow normally and green while the box
        # is inside it, over the blue bar (hue ~104). Measured in the real game:
        # zone H 42-90, V 66+; lily pads seen through the bar are darker (V ~57).
        "zone_h_min": 15,
        "zone_h_max": 95,
        "zone_s_min": 60,
        "zone_v_min": 65,
        # White / light-grey player box
        "box_v_min": 165,
        "box_s_max": 90,
        "box_size_frac": 0.51,         # box side / bar width (measured: 31 px box in a 61 px bar)
        "zone_height_frac": 0.107,     # zone height / bar height (measured: 54 px in a 506 px bar)
        "size_tolerance": 0.4,         # allowed +-40% around those sizes
        "box_max_aspect": 2.2,         # reject blobs wider/taller than this ratio (tick marks)
        # Water, for checking the cast spot (clicks on the dock don't cast)
        "water_h_min": 95,
        "water_h_max": 125,
        "water_s_min": 110,
        "water_v_min": 90,
        # Collect prompt. Other prompts (e.g. "Rare Fishing Rod / Purchase") use the
        # same T circle, so by default T is only pressed once the word "Collect" is found.
        "require_collect_word": True,  # NEVER turn off near shops or other T prompts
        "word_threshold": 0.65,        # match score needed to find the word "Collect" (real prompts 0.76-0.85, "Purchase" <0.5)
        "word_keep_threshold": 0.55,   # lower score accepted while already holding T
        "prompt_follow_px": 200,       # while holding T, first look this far around the last spot
        "template_threshold": 0.72,    # T circle (only used alone if require_collect_word is off)
        "template_keep_threshold": 0.5,# T circle next to the word / while holding T
        # The prompt's size follows the camera zoom (1.0 = the size when calibrated)
        "prompt_scale_min": 0.6,
        "prompt_scale_max": 2.0,
        "prompt_scale_step": 0.1,
        "use_circle_fallback": True,   # shape-based T-circle detector (only if the check above is off)
        "use_ocr": True,               # OCR for "Collect" if pytesseract + Tesseract are installed
        "tesseract_cmd": ""            # e.g. "C:/Program Files/Tesseract-OCR/tesseract.exe"
    },

    # ---- Camera keeping ------------------------------------------------------
    # When you press the start key, turn/zoom the camera back to the saved view if it moved
    # (once, before the first cast; never between catches).
    "camera": {
        "enabled": True,
        "reference": "templates/camera_view.png",      # your view (saved by --save-camera)
        "topdown": "templates/camera_topdown.png",     # the same spot seen from straight above
        "tolerance_px": 60,          # how far off (screen px, on average) the view may be before resetting
        "tolerance_deg": 0.6,        # how exactly to line up the direction (degrees)
        "min_points": 25,            # matched points needed to trust a comparison
        # Measured by --save-camera; don't edit by hand:
        "zoom_notches": None,        # mouse-wheel notches in from fully zoomed out
        "pitch_counts": None,        # mouse counts of tilt up from top-down
        "counts_per_degree": None    # mouse counts per degree of camera turn
    },

    # ---- Hotkeys -------------------------------------------------------------
    # Any of: f1-f24, insert, delete, home, end, page_up, page_down, pause,
    # scroll_lock, num_lock, print_screen. Start also takes calibration
    # snapshots; pause also skips a calibration step.
    "hotkeys": {
        "start": "f6",
        "pause": "f7",
        "quit": "f8"
    },

    # ---- Quest mode (quest.py) -------------------------------------------------
    "quests": {
        "level": 60,                  # 45 = "Ill fill your crates", 60 = "Ill land the good catch"
        "cooldown_s": 12,             # wait after handing in (the game's cooldown is 10 s)
        "load_hold_s": 2.0,           # how long to hold T on the crate
        "npc_name": "Angler Runo",
        "crate_name": "Fish Crate",
        "max_dialogue_clicks": 15     # give up on a conversation after this many clicks
    },

    # ---- Discord notifications (Settings > Notifications) ---------------------
    "notifications": {
        "webhook_url": "",            # Discord channel > Edit > Integrations > Webhooks > Copy URL
        "username": "Slayers 2 Fisher",
        "ping_user_id": "",           # your Discord user ID, to be @mentioned on alerts
        "on_catch": True,             # a message for every collected catch
        "on_quest": True,             # a message for every finished quest
        "catch_picture": True,        # ... with a close-up of what was caught
        "on_no_prompt": False,        # also when a minigame ends without a Collect prompt
        "on_start_stop": True,        # started / paused / stopped
        "summary_every_min": 30,      # status update while running (0 = off)
        "alert_idle_min": 10,         # alert: nothing hooked for this long (0 = off)
        "alert_unfocused_min": 5,     # alert: Roblox not focused for this long (0 = off)
        "alert_recasts": 5,           # alert: this many casts in a row without a bite (0 = off)
        "screenshots": True           # attach a screenshot to status updates and alerts
    },

    # ---- Roblox window -------------------------------------------------------
    "window": {
        "process_names": ["RobloxPlayerBeta.exe", "Windows10Universal.exe"],
        "title": "Roblox"
    },

    # ---- Debug ---------------------------------------------------------------
    "debug": {
        "enabled": False,             # also switchable with --debug
        "save_every_n_frames": 6,     # during the minigame
        "save_waiting_every_s": 2.0,  # while waiting for a bite
        "max_images": 600             # oldest images are deleted past this
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Return ``base`` updated with ``override``, recursing into nested dicts."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load config.json merged over the defaults. Creates the file if missing."""
    if not path.exists():
        cfg = copy.deepcopy(DEFAULTS)
        save_config(cfg, path)
        log.info("Created default config at %s", path)
        return cfg
    try:
        with path.open("r", encoding="utf-8") as f:
            user_cfg = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"config.json is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}\n"
            "Fix the typo, or delete config.json to start over."
        ) from e
    return _deep_merge(DEFAULTS, user_cfg)


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def resolve_path(relative: str) -> Path:
    """Paths in the config are relative to the app folder."""
    p = Path(relative)
    return p if p.is_absolute() else APP_DIR / p


def key_label(cfg: dict, action: str) -> str:
    """How to show a hotkey to the user: "f6" -> "F6", "page_up" -> "Page Up"."""
    name = str(cfg["hotkeys"][action]).strip().lower()
    if name[:1] == "f" and name[1:].isdigit():
        return name.upper()
    return name.replace("_", " ").title()


def calibration_problem(cfg: dict, monitors: list[list[int]]) -> str | None:
    """
    Why the saved calibration can't be used on this PC, or None if it can.
    ``monitors`` is [left, top, width, height] of each connected screen.
    Calibration is in screen pixels, so it only fits the screen it was made on.
    """
    if not cfg["calibrated"]:
        return "The bot isn't calibrated yet."
    mon = cfg.get("monitor")
    if not mon or list(mon) not in [list(m) for m in monitors]:
        return ("The screen the bot was calibrated on isn't here any more "
                "(different resolution, display scaling, or another PC).")
    return None


def collect_region(cfg: dict) -> list[int]:
    """The calibrated collect-prompt search area, or the middle of the screen."""
    if cfg.get("collect_region"):
        return cfg["collect_region"]
    mon = cfg.get("monitor")
    if not mon:
        from window import primary_monitor_rect
        mon = primary_monitor_rect()
    # Most of the screen: the caught item (and its prompt) can drift around.
    left, top, width, height = mon
    return [left + int(width * 0.08), top + int(height * 0.06),
            int(width * 0.84), int(height * 0.84)]
