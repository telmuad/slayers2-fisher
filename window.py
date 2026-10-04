"""
Windows helpers: DPI awareness, Roblox focus detection, cursor position.

Everything here talks to the Win32 API through ctypes, so there are no extra
dependencies.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77


def make_dpi_aware() -> None:
    """
    Make screen coordinates real pixels. Without this, Windows display scaling
    (125%, 150%...) makes screenshots and mouse positions disagree.
    Must be called before any window is created.
    """
    try:
        # Per-monitor v2 (Windows 10 1703+)
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def primary_monitor_rect() -> list[int]:
    return [0, 0, user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)]


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def cursor_in_failsafe_corner(margin: int = 3) -> bool:
    """True if the cursor is jammed into the top-left corner of the screen."""
    x, y = cursor_pos()
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    near_primary = abs(x) <= margin and abs(y) <= margin
    near_virtual = x - vx <= margin and y - vy <= margin
    return near_primary or near_virtual


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def window_process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) in screen pixels."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


class RobloxWindow:
    """Answers "is Roblox the focused window right now?" cheaply."""

    def __init__(self, cfg: dict):
        self.process_names = {n.lower() for n in cfg["window"]["process_names"]}
        self.title = cfg["window"]["title"]
        self._known_hwnd = 0

    def is_focused(self) -> bool:
        hwnd = foreground_window()
        if not hwnd:
            return False
        if hwnd == self._known_hwnd:
            return True
        proc = window_process_name(hwnd).lower()
        if proc not in self.process_names:
            return False
        # The Microsoft Store build runs as Windows10Universal.exe, which other
        # Store apps use too, so the window title has to match as well.
        if proc == "windows10universal.exe" and window_title(hwnd) != self.title:
            return False
        self._known_hwnd = hwnd
        return True
