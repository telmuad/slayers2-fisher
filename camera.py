"""
Keeps the Roblox camera where you want it.

Roblox's camera has two hard limits the bot can always return to: fully
zoomed out, and looking straight down (top-down). Only the direction the
camera faces (yaw) has no limit, but from straight above, turning the camera
just rotates the picture around your character, which is easy to measure.

Saving a view (calibration, or `python main.py --save-camera`):
  1. From your view, zoom out one notch at a time until the picture stops
     changing, counting the notches.
  2. Tilt down step by step until it stops changing (top-down), counting.
  3. Save a top-down snapshot, and learn how far a drag turns the camera.
  4. Tilt back up and zoom back in by the counted amounts: your view again.
     Save a snapshot of it too.

Keeping it (once each time you press the start key, before the first cast):
  * Compare the screen with the saved view. If it still matches, done.
  * Otherwise: zoom fully out, tilt fully down, turn until the top-down
    snapshot lines up, then tilt up and zoom in by the saved amounts.

Never runs during the minigame or while a Collect prompt is up.
"""
from __future__ import annotations

import logging
import math
import time

import cv2
import numpy as np

from config import resolve_path, save_config

log = logging.getLogger(__name__)

SCALE = 0.25          # snapshots are compared at quarter resolution
EVENT = 30            # mouse counts per input event in every camera drag. Keeping this
                      # identical everywhere matters: Windows mouse acceleration scales
                      # each event by its size, so mixed sizes would not add up.
PITCH_STEP = 90       # mouse counts per tilt step when looking for the top-down limit
MAX_ZOOM_OUT = 60     # notches that surely reach full zoom-out


def _to_gray(img_bgr: np.ndarray) -> np.ndarray:
    small = cv2.resize(img_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _land_mask(img_bgr_small: np.ndarray) -> np.ndarray:
    """Where to compare: not the (animated) water, not the UI around the edges."""
    h, w = img_bgr_small.shape[:2]
    hsv = cv2.cvtColor(img_bgr_small, cv2.COLOR_BGR2HSV)
    water = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 125) & (hsv[..., 1] >= 100)
    m = np.zeros((h, w), np.uint8)
    m[int(0.08 * h):int(0.80 * h), int(0.03 * w):int(0.72 * w)] = 255
    m[water] = 0
    return m


class CameraKeeper:
    def __init__(self, cfg: dict, bot):
        self.cfg = cfg
        self.c = cfg["camera"]
        self.bot = bot   # screen, input and stop checks go through the bot
        self.monitor = cfg.get("monitor")
        self.orb = cv2.ORB_create(2000, scaleFactor=1.2, nlevels=8, fastThreshold=8)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.view = self._load("reference")
        self.topdown = self._load("topdown")

    def _load(self, key):
        path = resolve_path(self.c[key])
        img = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if img is None:
            return None
        return img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), _land_mask(img)

    @property
    def enabled(self) -> bool:
        return (bool(self.c["enabled"]) and self.monitor is not None and self.view is not None
                and self.topdown is not None and self.c.get("zoom_notches") is not None)

    # -- low-level ------------------------------------------------------------
    def _snap(self):
        img = self.bot.capture.grab(self.monitor)
        small = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        return small, cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), _land_mask(small)

    def _cursor_to_world(self):
        m = self.monitor
        self.bot._guard()
        self.bot.inp.move_to(m[0] + m[2] // 2, m[1] + int(m[3] * 0.4))

    @staticmethod
    def _changed(a, b) -> float:
        """How different two snapshots are (mean grey difference on land)."""
        mask = (a[2] > 0) & (b[2] > 0)
        return float(np.abs(a[1].astype(np.float32) - b[1].astype(np.float32))[mask].mean()) if mask.any() else 0.0

    def _match(self, ref, cur):
        ka, da = self.orb.detectAndCompute(ref[1], ref[2])
        kb, db = self.orb.detectAndCompute(cur[1], cur[2])
        if da is None or db is None or len(ka) < 20 or len(kb) < 20:
            return None
        m = sorted(self.matcher.match(da, db), key=lambda x: x.distance)[:500]
        if len(m) < 20:
            return None
        return (np.float32([ka[x.queryIdx].pt for x in m]), np.float32([kb[x.trainIdx].pt for x in m]))

    def view_error(self) -> tuple[float, int] | None:
        """(average px the current view is off from the saved one, matched points)."""
        pts = self._match(self.view, self._snap())
        if pts is None:
            return None
        H, inl = cv2.findHomography(pts[0], pts[1], cv2.RANSAC, 4.0)
        if H is None:
            return None
        h, w = self.view[1].shape
        grid = np.float32([[x * w, y * h] for y in (0.25, 0.45, 0.65) for x in (0.15, 0.38, 0.6)])
        moved = cv2.perspectiveTransform(grid[None], H)[0] - grid
        return float(np.linalg.norm(moved, axis=1).mean() / SCALE), int(inl.sum())

    def _rotation(self) -> float | None:
        """Degrees the current top-down picture is turned relative to the saved one."""
        pts = self._match(self.topdown, self._snap())
        if pts is None:
            return None
        M, inl = cv2.estimateAffinePartial2D(pts[0], pts[1], method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is None or inl.sum() < self.c["min_points"]:
            return None
        return math.degrees(math.atan2(M[1, 0], M[0, 0]))

    # -- moves ------------------------------------------------------------------
    def _zoom_out_fully(self):
        self._cursor_to_world()
        self.bot.inp.scroll(-MAX_ZOOM_OUT, delay_s=0.015)

    def _tilt_to_topdown(self):
        self._cursor_to_world()
        self.bot.inp.right_drag(0, int(self.c["pitch_counts"]) + 1500, step=EVENT, delay_s=0.003)

    def _back_to_view(self):
        self._cursor_to_world()
        self.bot.inp.right_drag(0, -int(self.c["pitch_counts"]), step=EVENT, delay_s=0.005)
        self.bot.inp.scroll(int(self.c["zoom_notches"]), delay_s=0.04)
        self.bot._sleep(0.4)

    def _align_yaw(self) -> bool:
        searched = 0
        for _ in range(12):
            self.bot._sleep(0.35)
            angle = self._rotation()
            if angle is None:
                # Turned too far to recognise (e.g. facing the other way):
                # look around in 60-degree steps until the snapshot matches.
                if searched >= 6:
                    log.warning("Camera: can't match the top-down snapshot in any direction")
                    return False
                searched += 1
                self._cursor_to_world()
                self.bot.inp.right_drag(int(round(60 * self.c["counts_per_degree"])), 0, step=EVENT, delay_s=0.005)
                continue
            if abs(angle) <= self.c["tolerance_deg"]:
                return True
            counts = max(-3000, min(3000, int(round(-angle * self.c["counts_per_degree"]))))
            self._cursor_to_world()
            self.bot.inp.right_drag(counts, 0, step=EVENT, delay_s=0.005)
        return abs(self._rotation() or 99) <= self.c["tolerance_deg"]

    # -- public ---------------------------------------------------------------
    def keep(self) -> None:
        """Put the camera back to the saved view if it has moved."""
        if not self.enabled:
            return
        err = self.view_error()
        if err is not None and err[0] <= self.c["tolerance_px"] and err[1] >= self.c["min_points"]:
            return
        log.info("Camera has moved (%s) - resetting it",
                 "can't match the saved view" if err is None else f"off by ~{err[0]:.0f}px")
        t0 = time.perf_counter()
        self._zoom_out_fully()
        self._tilt_to_topdown()
        ok = self._align_yaw()
        self._back_to_view()
        err = self.view_error()
        log.info("Camera reset in %.1fs: %s", time.perf_counter() - t0,
                 f"off by ~{err[0]:.0f}px ({err[1]} points)" if err else "can't match the saved view")
        if not ok:
            log.warning("Camera: couldn't line up the direction; save a new view with --save-camera")

    def setup(self) -> None:
        """Record the current camera view as the one to keep (see module docs)."""
        self._cursor_to_world()
        # 1. zoom out one notch at a time until nothing changes
        notches, prev = 0, self._snap()
        while notches < MAX_ZOOM_OUT:
            self.bot.inp.scroll(-1); notches += 1
            self.bot._sleep(0.25)
            cur = self._snap()
            if self._changed(prev, cur) < 1.5:
                notches -= 1          # that last notch did nothing
                break
            prev = cur
        # 2. tilt down step by step until nothing changes (top-down)
        counts = 0
        while counts < 6000:
            self._cursor_to_world()
            self.bot.inp.right_drag(0, PITCH_STEP, step=EVENT, delay_s=0.005); counts += PITCH_STEP
            self.bot._sleep(0.25)
            cur = self._snap()
            if self._changed(prev, cur) < 1.5:
                counts -= PITCH_STEP
                break
            prev = cur
        # 3. top-down snapshot, and how far a drag turns the camera
        top = self.bot.capture.grab(self.monitor)
        _save(self.c["topdown"], top)
        self.topdown = self._load("topdown")
        self._cursor_to_world()
        self.bot.inp.right_drag(400, 0, step=EVENT, delay_s=0.005)
        self.bot._sleep(0.4)
        angle = self._rotation()
        self._cursor_to_world()
        self.bot.inp.right_drag(-400, 0, step=EVENT, delay_s=0.005)
        if not angle or abs(angle) < 2:
            raise RuntimeError("couldn't measure how far the camera turns - is the view too plain?")
        self.c.update(zoom_notches=notches, pitch_counts=counts, counts_per_degree=400 / angle)
        # 4. back to the original view; save the view exactly as the bot reproduces it
        self._back_to_view()
        _save(self.c["reference"], self.bot.capture.grab(self.monitor))
        self.view = self._load("reference")
        self.cfg["camera"] = self.c
        save_config(self.cfg)
        err = self.view_error()
        log.info("Saved camera view: %d zoom notches from fully out, %d counts up from top-down, "
                 "%.1f counts per degree of turn; back at your view within ~%s px",
                 notches, counts, 400 / angle, f"{err[0]:.0f}" if err else "?")


class Driver:
    """Screen + input + safety checks for using CameraKeeper outside the bot."""

    def __init__(self, cfg: dict):
        from capture import ScreenCapture
        from win_input import InputController
        from window import RobloxWindow
        self.capture, self.inp, self.window = ScreenCapture(), InputController(), RobloxWindow(cfg)

    def _guard(self):
        from window import cursor_in_failsafe_corner
        if not self.window.is_focused() or cursor_in_failsafe_corner():
            self.inp.release_all(force=True)
            raise RuntimeError("stopped: Roblox isn't the focused window (or mouse in the corner)")
        return time.perf_counter()

    def _sleep(self, s: float):
        time.sleep(s)
        self._guard()


def _save(rel_path: str, img_bgr: np.ndarray) -> None:
    path = resolve_path(rel_path)
    path.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(path), cv2.resize(img_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA))
