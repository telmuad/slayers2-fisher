"""
Global hotkeys (work even while Roblox has focus).

Start / pause / quit, set in the "hotkeys" section of config.json (F6 / F7 /
F8 by default). The listener runs in its own background thread, started by
pynput.
"""
from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

log = logging.getLogger(__name__)


def parse_key(name: str) -> keyboard.Key:
    """A config key name like "f6" or "page_up" -> the pynput key."""
    key = getattr(keyboard.Key, str(name).strip().lower(), None)
    if not isinstance(key, keyboard.Key):
        raise SystemExit(
            f'Unknown hotkey "{name}" in config.json.\n'
            "Use a key name like f6, f9, insert, home, page_up or pause.")
    return key


def check_hotkeys(cfg: dict) -> None:
    """Stop with a clear message if the configured hotkeys are unusable."""
    names = cfg["hotkeys"]
    for action in ("start", "pause", "quit"):
        if action not in names:
            raise SystemExit(f'config.json: "hotkeys" is missing "{action}".')
    keys = [parse_key(names[a]) for a in ("start", "pause", "quit")]
    if len(set(keys)) < len(keys):
        raise SystemExit("config.json: start, pause and quit need three different hotkeys.")


def start_hotkeys(bindings: dict[str, Callable[[], None]]) -> keyboard.Listener:
    """
    ``bindings`` maps key names like "f6" to callbacks. Callbacks run on the
    listener thread, so they must be quick and thread-safe.
    """
    keymap = {parse_key(name): fn for name, fn in bindings.items()}

    def on_press(key):
        fn = keymap.get(key)
        if fn is not None:
            try:
                fn()
            except Exception:
                log.exception("Hotkey handler failed")

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener
