"""
The fishing loop: cast -> wait for bite -> minigame -> collect -> repeat.

Runs in its own thread. Every loop calls ``_guard()``, which stops the current
step (releasing all input) as soon as you pause, quit, hit the failsafe
corner, or Roblox stops being the focused window.
"""
from __future__ import annotations

import logging
import random
import threading
import time
import traceback
from dataclasses import dataclass

from camera import CameraKeeper
from capture import ScreenCapture
from config import collect_region, key_label
from controller import MinigameController
from debugging import DebugSaver, annotate_minigame, annotate_prompt
from detection import (BarDetector, BarGeometry, MinigameReading, PromptDetector, PromptMatch,
                       nearest_water)
from notifier import Notifier
from quest import QuestRunner
from win_input import InputController
from window import RobloxWindow, cursor_in_failsafe_corner

log = logging.getLogger(__name__)


class Interrupted(Exception):
    """Raised inside a step when the bot must stop what it's doing."""


@dataclass
class StatusSnapshot:
    state: str
    detail: str
    minigames: int
    catches: int      # collected via the T prompt
    no_prompt: int    # minigame over but no Collect prompt: caught straight into the inventory, or escaped
    failed: int       # a Collect prompt that didn't go away after holding T
    recasts: int
    fps: float
    quests: int = 0   # quests handed in (quest mode)


class Status:
    """Shared between the bot thread (writes) and the UI thread (reads)."""

    def __init__(self, start_key: str = "F6"):
        self._lock = threading.Lock()
        self.state = "Stopped"
        self.detail = f"Press {start_key} in Roblox to start"
        self.minigames = self.catches = self.no_prompt = self.failed = self.recasts = self.quests = 0
        self.fps = 0.0

    def set(self, state: str, detail: str = "") -> None:
        with self._lock:
            if (state, detail) != (self.state, self.detail):
                log.debug("State: %s %s", state, detail)
            self.state, self.detail = state, detail

    def add(self, field_name: str) -> None:
        with self._lock:
            setattr(self, field_name, getattr(self, field_name) + 1)

    def snapshot(self) -> StatusSnapshot:
        with self._lock:
            return StatusSnapshot(self.state, self.detail, self.minigames, self.catches,
                                  self.no_prompt, self.failed, self.recasts, self.fps, self.quests)


class FishingBot:
    def __init__(self, cfg: dict, debug: bool = False, status: Status | None = None,
                 notifier: Notifier | None = None):
        self.cfg = cfg
        self.t = cfg["timing"]
        self.capture = ScreenCapture()
        self.inp = InputController()
        self.window = RobloxWindow(cfg)
        self.bar_det = BarDetector(cfg)
        self.prompt_det = PromptDetector.from_config(cfg)
        self.ctrl = MinigameController(cfg)
        self.dbg = DebugSaver(cfg, debug)
        self.debug_every = max(1, int(cfg["debug"]["save_every_n_frames"]))

        self.bar_region = cfg["bar_region"]
        self.collect_region = collect_region(cfg)
        self.cast_point = cfg["cast_point"]

        self.start_key, self.pause_key = key_label(cfg, "start"), key_label(cfg, "pause")
        self.status = status or Status(self.start_key)   # passed in to keep the counts across a settings reload
        self.running = threading.Event()      # start key sets, pause key clears
        self.quit_event = threading.Event()   # quit key / failsafe
        self._resync = True                   # after any interruption, look before casting
        self.camera = CameraKeeper(cfg, self)
        self._camera_pending = False          # start sets: check the camera once, before the next cast
        self._fps_last = 0.0
        self.unfocused_since: float | None = None   # while running but Roblox isn't focused
        self._no_bites = 0                    # casts in a row without a bite
        self.last_in_zone: float | None = None  # % of the last minigame the box was in the zone
        self.quests = QuestRunner(self)     # quest mode (reads the screen with Windows OCR)
        self.notify = notifier or Notifier(cfg)
        self.notify.bot = self
        if self.notify.screenshot is None:
            self.notify.screenshot = lambda: self.capture.grab(list(self.quests.mon))

        log.info("Bot ready. Bar region %s, cast point %s, collect region %s, prompt detection: %s",
                 self.bar_region, self.cast_point, self.collect_region,
                 ", ".join(self.prompt_det.methods) or "NONE (run --calibrate-collect!)")

    # ------------------------------------------------------------------
    # Control (called from hotkey / UI threads)
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.running.is_set():
            log.info("Started (%s)", self.start_key)
            self._camera_pending = True
            self._no_bites = 0
            self.notify.started()
        self.running.set()

    def pause(self, reason: str | None = None, notify: bool = True) -> None:
        if self.running.is_set():
            log.info("Paused (%s)", reason or self.pause_key)
            if notify:
                self.notify.paused(reason or self.pause_key)
        self.running.clear()
        self.inp.release_all()

    def quit(self, reason: str = "quit key", notify: bool = True) -> None:
        """``notify=False`` when the app is only rebuilding the bot (new settings)."""
        log.info("Quit requested (%s)", reason)
        first = not self.quit_event.is_set()
        self.quit_event.set()
        self.running.clear()
        if notify and first:
            self.notify.stopped(reason)
        self.inp.release_all(force=True)

    # ------------------------------------------------------------------
    # Main thread loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        while not self.quit_event.is_set():
            try:
                if not self.running.is_set():
                    self.unfocused_since = None
                    # Keep "Stopped" (never started) and error messages visible.
                    if self.status.state != "Stopped" and not self.status.detail.startswith(("Error", "Out of fish")):
                        self.status.set("Paused", f"Press {self.start_key} to resume")
                    time.sleep(0.05)
                    continue
                if cursor_in_failsafe_corner():
                    self.quit("mouse in top-left corner")
                    break
                if not self.window.is_focused():
                    if self.unfocused_since is None:
                        self.unfocused_since = time.time()
                    self.status.set("Paused", "Roblox is not the focused window")
                    self.inp.release_all()
                    self._resync = True
                    time.sleep(0.1)
                    continue
                self.unfocused_since = None
                self._step()
            except Interrupted as e:
                self.inp.release_all()
                self._resync = True
                log.info("Interrupted: %s", e)
            except Exception:
                log.exception("Unexpected error - pausing")
                self.notify.error(traceback.format_exc(limit=3))
                self.inp.release_all()
                self.running.clear()
                self.status.set("Paused", "Error! See logs/fishing_bot.log")
        self.inp.release_all(force=True)
        self.status.set("Stopped", "Quit")

    def _step(self) -> None:
        if self.cfg.get("mode") == "quests":
            self.quests.step()
            return
        if self._resync:
            # Just started or resumed: pick up wherever the game is.
            self._resync = False
            reading = self._read_bar()
            if reading.bar is not None:
                log.info("Resuming mid-minigame")
                self._play_minigame(reading.bar)
                self._after_minigame()
                return
            if self._find_prompt() is not None:
                log.info("Resuming at collect prompt")
                self._collect()
                self._random_delay()
                return
        self._cycle()

    def _cycle(self) -> None:
        self._cast()
        bar = self._wait_for_bite()
        if bar is None:
            self.status.add("recasts")
            self._no_bites += 1
            self.notify.no_bite(self._no_bites)
            return
        self._no_bites = 0
        self._play_minigame(bar)
        self._after_minigame()

    def _after_minigame(self) -> None:
        self._random_delay()
        self._collect()
        self._random_delay()

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def _cast(self) -> None:
        self.status.set("Casting")
        self._guard()
        if self._camera_pending:
            # Only once per start press, never between catches. Cleared afterwards,
            # so a reset cut short (pause, focus lost) is redone before the next cast.
            self.camera.keep()
            self._camera_pending = False
        x, y = self._cast_spot()
        self.inp.move_to(x, y)
        self._sleep(0.05)
        self._guard()
        self.inp.click(self.t["cast_click_hold_s"])
        log.info("Cast at (%d, %d)", x, y)

    def _cast_spot(self) -> tuple[int, int]:
        """
        The calibrated cast spot, moved onto the nearest water if it isn't
        water any more. Clicks on the dock don't cast, and the camera can turn.
        """
        cx, cy = self.cast_point
        if not self.t["cast_snap_to_water"]:
            return cx, cy
        r = int(self.t["cast_search_radius_px"])
        left, top, width, height = self.cfg.get("monitor") or [cx - r, cy - r, 2 * r, 2 * r]
        x0, y0 = max(left, cx - r), max(top, cy - r)
        x1, y1 = min(left + width, cx + r), min(top + height, cy + r)
        img = self.capture.grab([x0, y0, x1 - x0, y1 - y0])
        spot = nearest_water(img, (cx - x0, cy - y0), self.cfg["detection"],
                             int(self.t["cast_water_margin_px"]))
        if spot is None:
            log.warning("No water within %d px of the cast spot - casting there anyway. "
                        "Did the camera turn? Recalibrate if this keeps happening.", r)
            return cx, cy
        sx, sy = spot[0] + x0, spot[1] + y0
        if (sx, sy) != (cx, cy):
            log.info("Cast spot (%d, %d) isn't water any more; using nearest water (%d, %d)",
                     cx, cy, sx, sy)
        return sx, sy

    def _wait_for_bite(self) -> BarGeometry | None:
        self.status.set("Waiting", "for a bite")
        timeout = self.t["bite_timeout_s"]
        deadline = time.perf_counter() + timeout
        seen_in_a_row = 0
        next_debug = 0.0
        self._fps_last = 0.0
        while time.perf_counter() < deadline:
            t0 = self._guard()
            frame = self.capture.grab(self.bar_region)
            reading = self.bar_det.analyze(frame)
            self._tick_fps()
            if reading.bar is not None:
                seen_in_a_row += 1
                if seen_in_a_row >= 2:     # two frames in a row = really there
                    self.dbg.save("bite", annotate_minigame(frame, reading))
                    return reading.bar
            else:
                seen_in_a_row = 0
            if self.dbg.enabled and t0 >= next_debug:
                self.dbg.save("waiting", annotate_minigame(frame, reading))
                next_debug = t0 + self.cfg["debug"]["save_waiting_every_s"]
            self._pace(self.t["poll_fps"], t0)
        log.info("No bite within %.0fs - recasting", timeout)
        if self.t["reel_in_before_recast"]:
            self._guard()
            self.inp.click(self.t["cast_click_hold_s"])
            self._sleep(1.0)
        return None

    def _play_minigame(self, bar: BarGeometry) -> None:
        # The bar slides in, so the first frames can show it shorter than it
        # is. Measure positions against the full bar seen during calibration.
        if self.cfg.get("bar_expected"):
            bar = BarGeometry.from_dict(self.cfg["bar_expected"])
        self.status.set("Minigame")
        self.status.add("minigames")
        self.notify.hooked()
        self.last_in_zone = None
        log.info("Minigame started (bar x %d-%d, y %d-%d)", bar.x0, bar.x1, bar.top, bar.bottom)
        self.ctrl.reset()
        grace = self.t["minigame_end_grace_s"]
        start = last_seen = time.perf_counter()
        frame_no = measured = inside = 0
        self._fps_last = 0.0
        try:
            while True:
                t0 = self._guard()
                frame = self.capture.grab(self.bar_region)
                reading = self.bar_det.analyze(frame, locked=bar)
                now = time.perf_counter()
                if reading.visible:
                    last_seen = now
                    box = bar.to_fraction(reading.box.cy) if reading.box else None
                    zone = bar.to_fraction(reading.zone.cy) if reading.zone else None
                    self.inp.set_mouse(self.ctrl.update(box, zone, now))
                    if reading.box and reading.zone:
                        measured += 1
                        inside += abs(reading.box.cy - reading.zone.cy) <= reading.zone.h / 2
                else:
                    self.inp.mouse_up()
                    if now - last_seen >= grace:
                        break
                if now - start > self.t["minigame_max_s"]:
                    log.warning("Minigame ran longer than %.0fs - giving up on it",
                                self.t["minigame_max_s"])
                    break
                if self.dbg.enabled and frame_no % self.debug_every == 0:
                    self.dbg.save("minigame", annotate_minigame(frame, reading, bar, self.ctrl.state))
                frame_no += 1
                self._tick_fps()
                self._pace(self.t["control_fps"], t0)
        finally:
            self.inp.mouse_up()
        if measured:
            self.last_in_zone = 100 * inside / measured
        log.info("Minigame ended after %.1fs (%d frames, box in the zone %.0f%% of the time, "
                 "learned braking %.2f)", time.perf_counter() - start, frame_no,
                 100 * inside / max(1, measured), self.ctrl.braking)

    def _collect(self) -> bool:
        self.status.set("Collecting", "looking for the prompt")
        match = self._wait_for_prompt(self.t["collect_appear_timeout_s"])
        if match is None:
            self.status.add("no_prompt")
            log.info("No collect prompt - the catch went straight to the inventory, or the fish escaped")
            self.notify.no_prompt(self.last_in_zone)
            return False
        picture = self._catch_picture(match) if self.notify.enabled else None

        self.status.set("Collecting", "holding T")
        for attempt in (1, 2):
            gone = self._hold_t_until_gone(match)
            if gone:
                self.status.add("catches")
                log.info("Collected! (%s match %.2f)", match.method, match.score)
                self.notify.caught(picture, self.last_in_zone)
                # A click during the catch animation is ignored, so let it finish.
                self._sleep(self.t["after_collect_delay_s"])
                return True
            log.warning("Prompt still visible after holding T for %.1fs (attempt %d)",
                        self.t["collect_max_hold_s"], attempt)
            self._random_delay()
        self.status.add("failed")
        return False

    def _hold_t_until_gone(self, match: PromptMatch) -> bool:
        self._sleep(random.uniform(0.05, 0.2))
        self._guard()
        confirm = self.t["collect_gone_confirm_s"]
        near = match.rect
        self.inp.key_down("t")
        start = last_seen = time.perf_counter()
        try:
            while time.perf_counter() - start < self.t["collect_max_hold_s"]:
                self._sleep(0.05)
                frame = self.capture.grab(self.collect_region)
                hit = self.prompt_det.find(frame, near=near)
                if hit is None:
                    # It may have drifted further than we looked: search everywhere
                    # before deciding it's gone.
                    hit = self.prompt_det.find(frame)
                now = time.perf_counter()
                if hit is not None:
                    last_seen, near = now, hit.rect
                elif now - last_seen >= confirm:
                    return True
            return False
        finally:
            self.inp.key_up("t")

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------
    def _catch_picture(self, match: PromptMatch):
        """A close-up of the caught item and its prompt, for the catch notification."""
        try:
            img = self.capture.grab(self.collect_region)
            r, h = match.rect, max(8, match.rect.h)
            x0, y0 = max(0, int(r.x - 8 * h)), max(0, int(r.y - 12 * h))
            x1, y1 = min(img.shape[1], int(r.x + r.w + 14 * h)), min(img.shape[0], int(r.y + r.h + 3 * h))
            return img[y0:y1, x0:x1].copy() if x1 > x0 and y1 > y0 else None
        except Exception:
            return None

    def _read_bar(self) -> MinigameReading:
        return self.bar_det.analyze(self.capture.grab(self.bar_region))

    def _find_prompt(self) -> PromptMatch | None:
        return self.prompt_det.find(self.capture.grab(self.collect_region))

    def _wait_for_prompt(self, timeout: float) -> PromptMatch | None:
        deadline = time.perf_counter() + timeout
        frame = None
        while time.perf_counter() < deadline:
            t0 = self._guard()
            frame = self.capture.grab(self.collect_region)
            match = self.prompt_det.find(frame)
            if match is not None:
                self.dbg.save("prompt_found", annotate_prompt(frame, match))
                return match
            self._pace(self.t["poll_fps"], t0)
        if self.dbg.enabled and frame is not None:
            self.dbg.save("prompt_missing", annotate_prompt(frame, None, self.prompt_det.best_score(frame)))
        return None

    # ------------------------------------------------------------------
    # Timing / safety helpers
    # ------------------------------------------------------------------
    def _guard(self) -> float:
        """Raise Interrupted if we must stop; otherwise return the current time."""
        if self.quit_event.is_set():
            raise Interrupted("quit")
        if not self.running.is_set():
            raise Interrupted("paused")
        if cursor_in_failsafe_corner():
            self.quit("mouse in top-left corner")
            raise Interrupted("failsafe corner")
        if not self.window.is_focused():
            raise Interrupted("Roblox lost focus")
        return time.perf_counter()

    def _sleep(self, seconds: float) -> None:
        """Sleep, but keep checking whether we should stop."""
        end = time.perf_counter() + seconds
        while True:
            self._guard()
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return
            time.sleep(min(0.02, remaining))

    def _random_delay(self) -> None:
        self._sleep(random.uniform(self.t["delay_min_s"], self.t["delay_max_s"]))

    @staticmethod
    def _pace(fps: float, t_start: float) -> None:
        """Sleep so the loop runs at roughly ``fps`` iterations per second."""
        remaining = 1.0 / fps - (time.perf_counter() - t_start)
        if remaining > 0:
            time.sleep(remaining)

    def _tick_fps(self) -> None:
        now = time.perf_counter()
        if self._fps_last:
            dt = now - self._fps_last
            if dt > 0:
                self.status.fps = 0.9 * self.status.fps + 0.1 * (1.0 / dt) if self.status.fps else 1.0 / dt
        self._fps_last = now
