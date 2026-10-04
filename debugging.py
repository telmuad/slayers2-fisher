"""
Debug images: what the bot "sees".

Each saved image is a strip of panels:
  [annotated frame] [edges] [yellow mask] [white mask]
  * annotated frame: magenta = bar, yellow = target zone, green = white box,
    cyan line = where the controller is aiming, text = controller output
  * edges: red = "gets darker" edges, blue = "gets brighter" edges; the
    bar's left side should be a red line and its right side a blue line
  * yellow / white masks: pixels counted as target zone / player box
If a panel doesn't show what you expect, adjust the matching numbers in the
"detection" section of config.json.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from config import DEBUG_DIR
from controller import ControlState
from detection import BarGeometry, MinigameReading, PromptMatch

MAGENTA, YELLOW, GREEN, CYAN, RED, WHITE = (255, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (0, 0, 255), (255, 255, 255)


def _mask_panel(mask: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(mask.astype(np.uint8) * 255, cv2.COLOR_GRAY2BGR)


def _label(panel: np.ndarray, text: str) -> np.ndarray:
    head = np.zeros((18, panel.shape[1], 3), np.uint8)
    cv2.putText(head, text, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.4, WHITE, 1, cv2.LINE_AA)
    return np.vstack([head, panel])


def annotate_minigame(img: np.ndarray, reading: MinigameReading,
                      locked: BarGeometry | None = None,
                      ctrl: ControlState | None = None) -> np.ndarray:
    """Side-by-side debug view of one bar-region frame."""
    ann = img.copy()
    bar = locked or reading.bar
    if reading.bar is not None:
        b = reading.bar
        cv2.rectangle(ann, (b.x0, b.top), (b.x1, b.bottom), MAGENTA, 1)
    if reading.zone is not None:
        z = reading.zone
        cv2.rectangle(ann, (z.x, z.y), (z.x + z.w - 1, z.y + z.h - 1), YELLOW, 1)
    if reading.box is not None:
        bx = reading.box
        cv2.rectangle(ann, (bx.x, bx.y), (bx.x + bx.w - 1, bx.y + bx.h - 1), GREEN, 2)
    if bar is not None and ctrl is not None and ctrl.target_pos is not None:
        ty = int(bar.bottom - ctrl.target_pos * (bar.bottom - bar.top))
        cv2.line(ann, (max(0, bar.x0 - 6), ty), (bar.x1 + 6, ty), CYAN, 1)

    m = reading.masks
    edges = np.zeros_like(img)
    if m:
        edges[m["into_dark"]] = RED
        edges[m["out_of_dark"]] = (255, 0, 0)
    panels = [_label(ann, "frame"), _label(edges, "edges"),
              _label(_mask_panel(m.get("yellow", np.zeros(img.shape[:2], bool))), "yellow"),
              _label(_mask_panel(m.get("white", np.zeros(img.shape[:2], bool))), "white")]
    out = np.hstack(panels)

    lines = [
        f"bar: {'found' if reading.bar else 'NOT found'}"
        + (f" (edges {reading.bar.edge_score:.2f})" if reading.bar else ""),
        f"zone: {'found' if reading.zone else 'NOT found'}   box: {'found' if reading.box else 'NOT found'}",
    ]
    if ctrl is not None and ctrl.box_pos is not None:
        tgt = f"{ctrl.target_pos:.2f}" if ctrl.target_pos is not None else "?"
        lines.append(f"box {ctrl.box_pos:.2f} target {tgt} vel {ctrl.box_vel:+.2f}/s "
                     f"err {ctrl.error:+.3f} duty {ctrl.duty:.2f} brake {ctrl.braking:.2f} "
                     f"-> {'HOLD' if ctrl.hold else 'release'}")
    footer = np.zeros((16 * len(lines) + 6, out.shape[1], 3), np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(footer, line, (4, 15 + 16 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.42, WHITE, 1, cv2.LINE_AA)
    out = np.vstack([out, footer])
    if out.shape[0] < 500:  # small bars are hard to read, so enlarge
        out = cv2.resize(out, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    return out


def annotate_prompt(img: np.ndarray, match: PromptMatch | None, score: float | None = None) -> np.ndarray:
    ann = img.copy()
    if match is not None:
        r = match.rect
        cv2.rectangle(ann, (r.x, r.y), (r.x + r.w, r.y + r.h), GREEN, 2)
    text = (f"prompt FOUND via {match.method} ({match.score:.2f})" if match
            else "prompt not found") + (f"  best score {score:.2f}" if score is not None else "")
    return _label(ann, text)


def run_preview(cfg: dict) -> None:
    """
    Live view of what the bot detects, WITHOUT sending any input. Fish by
    hand in Roblox and watch the windows. Q/Esc = quit, S = save a snapshot.
    """
    from capture import ScreenCapture
    from config import collect_region
    from controller import MinigameController
    from detection import BarDetector, PromptDetector

    cap = ScreenCapture()
    bar_det = BarDetector(cfg)
    prompt_det = PromptDetector.from_config(cfg)
    ctrl = MinigameController(cfg)
    saver = DebugSaver(cfg, enabled=True)
    coll = collect_region(cfg)
    locked, last_seen, fps, last = None, 0.0, 0.0, time.perf_counter()
    print("Preview running - fish by hand in Roblox. No input is sent.\n"
          "Click a preview window and press Q or Esc to quit, S to save a snapshot to ./debug")

    while True:
        frame = cap.grab(cfg["bar_region"])
        reading = bar_det.analyze(frame, locked=locked)
        now = time.perf_counter()
        if reading.visible:
            if locked is None and reading.bar is not None:
                locked = reading.bar
                ctrl.reset()
            last_seen = now
        elif locked is not None and now - last_seen > cfg["timing"]["minigame_end_grace_s"]:
            locked = None
        if locked is not None:
            ctrl.update(locked.to_fraction(reading.box.cy) if reading.box else None,
                        locked.to_fraction(reading.zone.cy) if reading.zone else None, now)
        bar_view = annotate_minigame(frame, reading, locked, ctrl.state if locked else None)

        shot = cap.grab(coll)
        match = prompt_det.find(shot)
        prompt_view = annotate_prompt(shot, match, None if match else prompt_det.best_score(shot))
        if prompt_view.shape[1] > 900:
            f = 900 / prompt_view.shape[1]
            prompt_view = cv2.resize(prompt_view, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)

        dt = now - last
        last = now
        fps = 0.9 * fps + 0.1 / dt if fps and dt > 0 else (1 / dt if dt > 0 else 0)
        cv2.putText(bar_view, f"{fps:4.0f} fps", (4, bar_view.shape[0] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, CYAN, 1, cv2.LINE_AA)
        cv2.imshow("Preview - fishing bar", bar_view)
        cv2.imshow("Preview - collect prompt", prompt_view)
        key = cv2.waitKey(15) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            break
        if key in (ord("s"), ord("S")):
            saver.save("preview_bar", bar_view)
            saver.save("preview_prompt", prompt_view)
            print("Saved snapshot to ./debug")
    cv2.destroyAllWindows()


class DebugSaver:
    """Writes debug images to ./debug, deleting the oldest past ``max_images``."""

    def __init__(self, cfg: dict, enabled: bool):
        self.enabled = enabled
        self.max_images = int(cfg["debug"]["max_images"])
        self.dir: Path = DEBUG_DIR
        if enabled:
            self.dir.mkdir(exist_ok=True)

    def save(self, name: str, image: np.ndarray) -> None:
        if not self.enabled:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        cv2.imwrite(str(self.dir / f"{stamp}_{name}.png"), image)
        files = sorted(self.dir.glob("*.png"))
        for old in files[:max(0, len(files) - self.max_images)]:
            old.unlink(missing_ok=True)
