"""
Calibration: tell the bot where things are on your screen.

Step 1: with the fishing bar on screen, press the start key (F6 by default).
        On the snapshot, drag a box around the bar, then click the water spot
        to cast at.
Step 2: with the "T / Collect" prompt on screen, press it again. Drag the area the
        prompt can appear in, then drag a tight box around the white T circle
        (saved as a template image).

Results go into config.json and templates/collect_t.png.
"""
from __future__ import annotations

import copy
import ctypes
import threading

import cv2
import numpy as np
from pynput import keyboard

from capture import ScreenCapture
from config import TEMPLATE_DIR, collect_region, key_label, resolve_path, save_config
from debugging import annotate_minigame, annotate_prompt
from detection import BarDetector, PromptDetector
from hotkeys import parse_key
from window import foreground_window, primary_monitor_rect, window_rect

WIN = "Calibration - Slayers 2 Auto-Fisher"
ENTER_KEYS = (13, 10, 32)   # Enter / Space
ESC = 27


class CalibrationCancelled(Exception):
    pass


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------
def wait_for_snapshot(cfg: dict, cap: ScreenCapture, message: str, allow_skip: bool):
    """
    Wait for the start key (take snapshot) or, if allowed, the pause key
    (skip). Returns (image, monitor_rect) of the monitor the focused window
    is on, or None.
    """
    snap_key, skip_key = parse_key(cfg["hotkeys"]["start"]), parse_key(cfg["hotkeys"]["pause"])
    print("\n" + message)
    print(f"  -> Press {key_label(cfg, 'start')} to take the snapshot."
          + (f"  Press {key_label(cfg, 'pause')} to skip this step." if allow_skip else ""))
    print("     (Ctrl+C in this console cancels calibration.)")
    pressed = threading.Event()
    choice = {}

    def on_press(key):
        if key == snap_key:
            choice["key"] = "snap"
            pressed.set()
        elif key == skip_key and allow_skip:
            choice["key"] = "skip"
            pressed.set()

    with keyboard.Listener(on_press=on_press):
        while not pressed.wait(0.2):
            pass
    if choice["key"] == "skip":
        print("  Skipped.")
        return None

    hwnd = foreground_window()
    if hwnd:
        left, top, right, bottom = window_rect(hwnd)
        monitor = cap.monitor_containing((left + right) // 2, (top + bottom) // 2)
    else:
        monitor = primary_monitor_rect()
    img = cap.grab(monitor)
    print(f"  Snapshot taken ({monitor[2]}x{monitor[3]} monitor at {monitor[0]},{monitor[1]}).")
    return img, monitor


# --------------------------------------------------------------------------
# Interactive picking in an OpenCV window
# --------------------------------------------------------------------------
class Picker:
    """Shows an image; the user drags a rectangle or clicks a point."""

    def __init__(self, img: np.ndarray, lines: list[str], mode: str = "rect",
                 max_zoom: float = 1.0, markers=None):
        self.img, self.lines, self.mode = img, lines, mode
        self.markers = markers or []          # [(x, y, w, h, colour)] drawn in image coords
        _, _, sw, sh = primary_monitor_rect()
        h, w = img.shape[:2]
        self.banner = 26 * len(lines) + 12
        self.scale = min(max_zoom, (sw * 0.94) / w, (sh * 0.86 - self.banner) / h)
        interp = cv2.INTER_AREA if self.scale < 1 else cv2.INTER_NEAREST
        self.disp = cv2.resize(img, None, fx=self.scale, fy=self.scale, interpolation=interp)
        self.start = self.end = None
        self.dragging = False

    def _to_img(self, x, y):
        ix = int(round(x / self.scale))
        iy = int(round((y - self.banner) / self.scale))
        h, w = self.img.shape[:2]
        return min(max(ix, 0), w - 1), min(max(iy, 0), h - 1)

    def _to_disp(self, x, y):
        return int(x * self.scale), int(y * self.scale) + self.banner

    def _on_mouse(self, event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start = self.end = self._to_img(x, y)
            self.dragging = self.mode == "rect"
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            self.end = self._to_img(x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.dragging:
            self.end = self._to_img(x, y)
            self.dragging = False

    def result(self):
        if self.start is None:
            return None
        if self.mode == "point":
            return self.start
        (x0, y0), (x1, y1) = self.start, self.end
        x, y, w, h = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
        return (x, y, w, h) if w >= 5 and h >= 5 else None

    def _render(self):
        canvas = np.zeros((self.banner + self.disp.shape[0], self.disp.shape[1], 3), np.uint8)
        canvas[self.banner:] = self.disp
        for i, line in enumerate(self.lines):
            colour = (0, 255, 255) if i == 0 else (255, 255, 255)
            cv2.putText(canvas, line, (10, 26 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62, colour, 1, cv2.LINE_AA)
        for (x, y, w, h, colour) in self.markers:
            cv2.rectangle(canvas, self._to_disp(x, y), self._to_disp(x + w, y + h), colour, 2)
        r = self.result()
        if self.mode == "rect" and self.start is not None:
            (x0, y0), (x1, y1) = self.start, self.end
            cv2.rectangle(canvas, self._to_disp(x0, y0), self._to_disp(x1, y1), (0, 255, 0), 2)
        elif self.mode == "point" and r is not None:
            px, py = self._to_disp(*r)
            cv2.drawMarker(canvas, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 28, 2)
            cv2.circle(canvas, (px, py), 10, (0, 0, 255), 2)
        return canvas

    def run(self):
        """Returns the rect/point in image coordinates, or None if Esc was pressed."""
        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WIN, self._on_mouse)
        _bring_to_front()
        try:
            while True:
                cv2.imshow(WIN, self._render())
                key = cv2.waitKey(20) & 0xFF
                if key in ENTER_KEYS and self.result() is not None:
                    return self.result()
                if key in (ord("r"), ord("R")):
                    self.start = self.end = None
                if key == ESC:
                    return None
                if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                    raise CalibrationCancelled("calibration window closed")
        finally:
            cv2.destroyWindow(WIN)
            cv2.waitKey(1)


def show_result(img: np.ndarray, lines: list[str]) -> bool:
    """Show a result image. Enter = accept (True), R = redo (False)."""
    picker = Picker(img, lines, mode="none", max_zoom=3.0)
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    _bring_to_front()
    try:
        while True:
            cv2.imshow(WIN, picker._render())
            key = cv2.waitKey(20) & 0xFF
            if key in ENTER_KEYS:
                return True
            if key in (ord("r"), ord("R")):
                return False
            if key == ESC or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                raise CalibrationCancelled("cancelled")
    finally:
        cv2.destroyWindow(WIN)
        cv2.waitKey(1)


def _bring_to_front():
    """Keep the calibration window above Roblox and try to give it focus."""
    try:
        cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    hwnd = ctypes.windll.user32.FindWindowW(None, WIN)
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)


def _clip(x, y, w, h, img_w, img_h):
    x, y = max(0, x), max(0, y)
    return x, y, min(w, img_w - x), min(h, img_h - y)


# --------------------------------------------------------------------------
# The two calibration steps
# --------------------------------------------------------------------------
def calibrate_bar(cfg: dict, cap: ScreenCapture) -> None:
    shot = wait_for_snapshot(cfg, cap, (
        "STEP 1 of 2 - the fishing bar\n"
        "  Go to Roblox, cast your rod and wait for a bite, so the fishing bar is on screen."),
        allow_skip=False)
    img, mon = shot
    H, W = img.shape[:2]

    while True:
        sel = Picker(img, [
            "STEP 1a: Drag a box around the whole fishing bar.",
            "Include a bit of water on the left and right. ENTER = OK, R = redo, ESC = cancel",
        ]).run()
        if sel is None:
            raise CalibrationCancelled("cancelled")
        x, y, w, h = sel
        # Pad the selection: the zone sticks out sideways, and the bar is
        # found by comparing it with the water next to it.
        px, py = max(12, int(0.35 * w)), max(8, int(0.06 * h))
        rx, ry, rw, rh = _clip(x - px, y - py, w + 2 * px, h + 2 * py, W, H)
        crop = img[ry:ry + rh, rx:rx + rw]

        test_cfg = copy.deepcopy(cfg)
        test_cfg["bar_expected"] = None
        reading = BarDetector(test_cfg).analyze(crop)
        ok = reading.bar is not None
        verdict = ("Bar FOUND (magenta), zone %s, box %s." % (
            "found" if reading.zone else "NOT found", "found" if reading.box else "NOT found")
            if ok else "Bar NOT found in this area - see README 'Tuning detection'.")
        accept = show_result(annotate_minigame(crop, reading), [
            verdict, "ENTER = use this area, R = select again"])
        if accept:
            break

    cfg["monitor"] = mon
    cfg["bar_region"] = [mon[0] + rx, mon[1] + ry, rw, rh]
    cfg["bar_expected"] = reading.bar.to_dict() if ok else None
    if not ok:
        print("  WARNING: the bar wasn't detected. Run 'python main.py --preview' while fishing to tune.")

    point = Picker(img, [
        "STEP 1b: Click the spot on the water where the rod should cast.",
        "ENTER = OK, R = redo, ESC = cancel",
    ], mode="point", markers=[(rx, ry, rw, rh, (255, 0, 255))]).run()
    if point is None:
        raise CalibrationCancelled("cancelled")
    cfg["cast_point"] = [mon[0] + point[0], mon[1] + point[1]]
    print(f"  Bar region {cfg['bar_region']}, cast point {cfg['cast_point']}")


def calibrate_collect(cfg: dict, cap: ScreenCapture) -> None:
    shot = wait_for_snapshot(cfg, cap, (
        "STEP 2 of 2 - the collect prompt\n"
        "  Go back to Roblox and catch something by hand. While the 'T  Collect' prompt\n"
        f"  is showing (DON'T press T yet), press {key_label(cfg, 'start')}."),
        allow_skip=True)
    if shot is None:
        return
    img, mon = shot
    H, W = img.shape[:2]
    if not cfg.get("monitor"):
        cfg["monitor"] = mon

    sel = Picker(img, [
        "STEP 2a: Drag a GENEROUS box around where the collect prompt can appear.",
        "ENTER = OK, R = redo, ESC = use the default (middle of the screen)",
    ]).run()
    if sel is not None:
        cfg["collect_region"] = [mon[0] + sel[0], mon[1] + sel[1], sel[2], sel[3]]
    else:
        cfg["collect_region"] = None
    region = collect_region(cfg)
    rx, ry, rw, rh = _clip(region[0] - mon[0], region[1] - mon[1], region[2], region[3], W, H)
    crop = img[ry:ry + rh, rx:rx + rw]

    TEMPLATE_DIR.mkdir(exist_ok=True)
    circle_path = resolve_path(cfg["collect_template"])
    word_path = resolve_path(cfg["collect_word_template"])
    while True:
        for path in (circle_path, word_path):
            path.unlink(missing_ok=True)
        circle = Picker(crop, [
            "STEP 2b: Drag a TIGHT box around just the white circle with the 'T'.",
            "ENTER = save, R = redo, ESC = skip",
        ], max_zoom=4.0).run()
        if circle is not None:
            x, y, w, h = circle
            cv2.imwrite(str(circle_path), crop[y:y + h, x:x + w])
        word = Picker(crop, [
            "STEP 2c: Drag a TIGHT box around just the word 'Collect' (under the item name).",
            "Needed so the bot never presses T on other prompts like 'Purchase'.",
            "ENTER = save, R = redo, ESC = skip (then the bot won't press T unless OCR is set up)",
        ], max_zoom=4.0).run()
        if word is not None:
            x, y, w, h = word
            cv2.imwrite(str(word_path), crop[y:y + h, x:x + w])
        det = PromptDetector(cfg, circle_path, word_path)
        match = det.find(crop)
        if match:
            verdict = f"Collect prompt FOUND ({match.method}, score {match.score:.2f})."
        elif not det.can_verify_word:
            verdict = "No 'Collect' template: the bot will not press T. Press R to select again."
        else:
            verdict = "Collect prompt NOT found with these boxes - press R and try tighter boxes."
        if show_result(annotate_prompt(crop, match), [verdict, "ENTER = keep, R = select again"]):
            print(f"  {verdict}")
            return


def save_camera_view(cfg: dict, cap: ScreenCapture | None = None) -> None:
    """Snapshot the camera view the bot should keep (see camera.py)."""
    from camera import CameraKeeper, Driver
    cap = cap or ScreenCapture()
    shot = wait_for_snapshot(cfg, cap, (
        "CAMERA VIEW\n"
        "  In Roblox, set up the camera the way the bot should keep it: water in front of\n"
        f"  you where the cast spot is. Close any menus, then press {key_label(cfg, 'start')} and don't touch the\n"
        "  mouse for ~15 seconds while the bot measures the camera (it will zoom/tilt and\n"
        "  come back to your view)."),
        allow_skip=True)
    if shot is None:
        return
    _, mon = shot
    if not cfg.get("monitor"):
        cfg["monitor"] = mon
    driver = Driver(cfg)
    try:
        CameraKeeper(cfg, driver).setup()
        print("  Camera view saved. The bot will put the camera back to it if it moves.")
    except RuntimeError as e:
        print(f"  Camera view NOT saved: {e}")
    finally:
        driver.inp.release_all(force=True)


def run_calibration(cfg: dict, only_collect: bool = False) -> dict:
    """Interactive calibration. Returns the updated config (also saved to disk)."""
    cfg = copy.deepcopy(cfg)
    cap = ScreenCapture()
    print("=" * 70)
    print(" CALIBRATION")
    print(" Use the same Roblox window size / UI scale you'll fish with.")
    print("=" * 70)
    try:
        if not only_collect:
            calibrate_bar(cfg, cap)
        calibrate_collect(cfg, cap)
        if not only_collect:
            save_camera_view(cfg, cap)
    except (CalibrationCancelled, KeyboardInterrupt):
        cv2.destroyAllWindows()
        raise SystemExit("\nCalibration cancelled - nothing was saved.")
    cfg["calibrated"] = True
    save_config(cfg)
    print("\nCalibration saved to config.json.")
    return cfg
