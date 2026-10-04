"""
Mouse and keyboard input through the Windows SendInput API.

Roblox often ignores the virtual-key events that pyautogui sends, so keys are
sent as hardware scan codes, the same way a real keyboard reports them.
Every press is tracked so ``release_all()`` can always let go of anything the
bot is holding.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

# Hardware scan codes (US layout position; Roblox reads keys by position).
# T (collect) is the only key the bot can press. Movement keys (WASD, arrows,
# space) are deliberately absent, so asking for one raises KeyError instead.
SCAN_CODES = {"t": 0x14}

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF,
                                                 dwFlags=flags))


def _key(scan: int, up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=scan, dwFlags=flags))


class InputController:
    """Thread-safe mouse/keyboard output that remembers what is held down."""

    def __init__(self):
        self._lock = threading.Lock()
        self._mouse_held = False
        self._right_held = False
        self._keys_held: set[int] = set()

    # ---- mouse -------------------------------------------------------------
    def move_to(self, x: int, y: int) -> None:
        """Put the cursor at (x, y), then nudge it so Roblox notices the move."""
        with self._lock:
            user32.SetCursorPos(int(x), int(y))
            _send(_mouse(MOUSEEVENTF_MOVE, 1, 0))
            _send(_mouse(MOUSEEVENTF_MOVE, -1, 0))

    def mouse_down(self) -> None:
        with self._lock:
            if not self._mouse_held:
                _send(_mouse(MOUSEEVENTF_LEFTDOWN))
                self._mouse_held = True

    def mouse_up(self) -> None:
        with self._lock:
            if self._mouse_held:
                _send(_mouse(MOUSEEVENTF_LEFTUP))
                self._mouse_held = False

    def set_mouse(self, hold: bool) -> None:
        """Hold or release the left button; only sends input when it changes."""
        self.mouse_down() if hold else self.mouse_up()

    def click(self, hold_s: float = 0.08) -> None:
        self.mouse_down()
        time.sleep(hold_s)
        self.mouse_up()

    @property
    def mouse_held(self) -> bool:
        return self._mouse_held

    # ---- camera ------------------------------------------------------------
    def right_drag(self, dx: int, dy: int, step: int = 20, delay_s: float = 0.01) -> None:
        """
        Hold the right button and move the mouse by (dx, dy) in small steps.
        In Roblox this turns the camera. The button is always released.
        """
        with self._lock:
            self._right_held = True
            _send(_mouse(MOUSEEVENTF_RIGHTDOWN))
        try:
            time.sleep(0.05)
            n = max(1, int(max(abs(dx), abs(dy)) / step))
            done_x = done_y = 0
            for i in range(1, n + 1):
                tx, ty = round(dx * i / n), round(dy * i / n)
                with self._lock:
                    _send(_mouse(MOUSEEVENTF_MOVE, tx - done_x, ty - done_y))
                done_x, done_y = tx, ty
                time.sleep(delay_s)
            time.sleep(0.05)
        finally:
            with self._lock:
                _send(_mouse(MOUSEEVENTF_RIGHTUP))
                self._right_held = False

    def scroll(self, notches: int, delay_s: float = 0.05) -> None:
        """Mouse wheel: positive = away from you (zooms in in Roblox)."""
        for _ in range(abs(notches)):
            with self._lock:
                _send(_mouse(MOUSEEVENTF_WHEEL, data=WHEEL_DELTA if notches > 0 else -WHEEL_DELTA))
            time.sleep(delay_s)

    # ---- keyboard ----------------------------------------------------------
    def key_down(self, key: str) -> None:
        scan = SCAN_CODES[key]
        with self._lock:
            if scan not in self._keys_held:
                _send(_key(scan, up=False))
                self._keys_held.add(scan)

    def key_up(self, key: str) -> None:
        scan = SCAN_CODES[key]
        with self._lock:
            if scan in self._keys_held:
                _send(_key(scan, up=True))
                self._keys_held.discard(scan)

    # ---- safety ------------------------------------------------------------
    def release_all(self, force: bool = False) -> None:
        """
        Let go of everything the bot is holding. With ``force=True`` the
        left button and T are released even if we think they're already up
        (used on quit, in case state got out of sync).
        """
        with self._lock:
            ups = []
            if self._mouse_held or force:
                ups.append(_mouse(MOUSEEVENTF_LEFTUP))
            if self._right_held or force:
                ups.append(_mouse(MOUSEEVENTF_RIGHTUP))
            self._right_held = False
            keys = set(self._keys_held)
            if force:
                keys.add(SCAN_CODES["t"])
            ups.extend(_key(scan, up=True) for scan in keys)
            self._mouse_held = False
            self._keys_held.clear()
            if ups:
                try:
                    _send(*ups)
                except OSError:
                    pass  # nothing more we can do; never crash while releasing
