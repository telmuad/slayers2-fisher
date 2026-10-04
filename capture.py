"""
Screen capture with mss.

mss objects can't be shared between threads on Windows, so each thread gets
its own instance automatically.
"""
from __future__ import annotations

import threading

import mss
import numpy as np


class ScreenCapture:
    def __init__(self):
        self._local = threading.local()

    def _sct(self) -> "mss.base.MSSBase":
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = getattr(mss, "MSS", None) or mss.mss   # newer mss renamed the class
            sct = sct()
            self._local.sct = sct
        return sct

    def grab(self, region: list[int] | tuple[int, int, int, int]) -> np.ndarray:
        """Capture [left, top, width, height] (absolute screen pixels) as a BGR image."""
        left, top, width, height = (int(v) for v in region)
        shot = self._sct().grab({"left": left, "top": top, "width": width, "height": height})
        # mss gives BGRA; drop alpha and make the array contiguous for OpenCV
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def monitors(self) -> list[dict]:
        """mss monitor list: [0] is the whole virtual desktop, [1..] are real monitors."""
        return self._sct().monitors

    def monitor_containing(self, x: int, y: int) -> list[int]:
        """[left, top, width, height] of the monitor containing point (x, y)."""
        mons = self.monitors()[1:]
        for m in mons:
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return [m["left"], m["top"], m["width"], m["height"]]
        m = mons[0]
        return [m["left"], m["top"], m["width"], m["height"]]
