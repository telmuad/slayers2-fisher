"""
Simulator: watch the real bot play a simulated copy of the fishing minigame.

Nothing is sent to Windows or Roblox. The bot's detection, controller and
state machine are exactly the code that runs for real; only the screen
capture and the mouse/keyboard are swapped for a fake game drawn to look
like Slayers 2 (see-through bar, tick marks, yellow zone, white box, the
"T / Collect" prompt with its hold ring).

    python main.py --simulate
    python main.py --simulate --record sim.mp4 --seconds 60   (no window, saves a video)

Keys (click the simulator window first):
    1-5   box physics: Slayers 2 (measured) / Momentum / Floaty / Heavy / Instant
    - +   slower / faster target zone
    P     pause / resume the bot
    Q Esc quit
"""
from __future__ import annotations

import collections
import copy
import logging
import random
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import bot as bot_module
from bot import FishingBot
from debugging import annotate_minigame, annotate_prompt
from detection import BarDetector, PromptDetector
from notifier import Notifier
from window import primary_monitor_rect

log = logging.getLogger("game")

BAR_W, BAR_H = 240, 640          # simulated bar region (same size as your screenshot)
PROMPT_W, PROMPT_H = 560, 360    # simulated collect-prompt region
PROMPT_REGION_X = 100_000        # fake screen x; only used to tell the two regions apart

# Bar layout inside its region
OUT_X0, OUT_X1, OUT_TOP, OUT_BOT, RADIUS = 84, 156, 40, 600, 14
IN_TOP, IN_BOT = OUT_TOP + 6, OUT_BOT - 6
BOX, ZONE_H = 32, 56
TRAVEL = IN_BOT - IN_TOP - BOX           # pixels the box centre can move
ZONE_HALF = (ZONE_H / 2) / TRAVEL        # zone half-height as a fraction of TRAVEL

# name, lift acceleration, gravity, max speed up, max speed down (bar travels per s)
PHYSICS = {
    ord("1"): ("Slayers 2 (measured)", 2.0, 2.0, 0.65, 0.65),   # from recordings of the real game
    ord("2"): ("Momentum", 3.0, 3.0, 1.2, 1.2),
    ord("3"): ("Floaty", 1.6, 1.6, 0.8, 0.8),
    ord("4"): ("Heavy", 2.5, 4.5, 1.0, 1.6),
    ord("5"): ("Instant", None, None, 0.8, 0.8),
}
ITEMS = ["Metal Scraps", "Old Boot", "Sea Bass", "Rusty Katana", "Demon Carp", "Treasure Chest"]

DECOY_POS = (60, 312)    # where the "Purchase" shop prompt sits in the prompt area
FILL_HOLD_S = 1.0        # how long T must be held to collect
PROMPT_DRIFT = 140       # px/s the caught item (and its prompt) drifts, plus random hops
BITE_DELAY = (1.5, 4.0)  # seconds from cast to bite


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def _ocean(w: int, h: int, seed: int, islands: int) -> np.ndarray:
    """Blue water with light wavy streaks and a few dark-green islands."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    shade = 0.92 + 0.08 * np.sin(xx / 90 + yy / 140)
    img = np.dstack([165 * shade, 78 * shade, 28 * shade])
    wave = np.sin(xx * 0.045 + np.sin(yy * 0.02) * 2.0) * np.sin(yy * 0.03 + np.sin(xx * 0.015) * 1.5)
    img += np.clip(1 - np.abs(wave) / 0.06, 0, 1)[..., None] * np.float32([28, 22, 14])
    img = np.clip(img, 0, 255).astype(np.uint8)
    for _ in range(islands):
        centre = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        axes = (int(rng.integers(30, 70)), int(rng.integers(12, 26)))
        cv2.ellipse(img, centre, axes, float(rng.integers(-25, 25)), 0, 360, (40, 52, 17), -1, cv2.LINE_AA)
    return img


def _rounded(shape, x0, y0, x1, y1, r) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    cv2.rectangle(m, (x0 + r, y0), (x1 - r, y1), 255, -1)
    cv2.rectangle(m, (x0, y0 + r), (x1, y1 - r), 255, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m > 127


def _blend(img: np.ndarray, mask: np.ndarray, colour, alpha: float) -> None:
    img[mask] = (img[mask] * (1 - alpha) + np.float32(colour) * alpha)


ACTION_FONT, ACTION_SCALE = cv2.FONT_HERSHEY_SIMPLEX, 0.45


def _draw_prompt(img: np.ndarray, pos, name: str, action: str, ring: float | None = None) -> np.ndarray:
    """A Roblox-style prompt: white T circle + dark pill with name and action."""
    cx, cy = pos
    pill = _rounded(img.shape, cx + 8, cy - 22, cx + 36 + 12 * max(len(name), 8), cy + 22, 20)
    f = img.astype(np.float32)
    _blend(f, pill, (32, 26, 22), 0.72)
    img = f.astype(np.uint8)
    cv2.putText(img, name, (cx + 28, cy - 2), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(img, action, _action_origin(pos), ACTION_FONT, ACTION_SCALE, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 17, (248, 248, 248), -1, cv2.LINE_AA)
    cv2.putText(img, "T", (cx - 7, cy + 8), cv2.FONT_HERSHEY_DUPLEX, 0.7, (15, 15, 15), 2, cv2.LINE_AA)
    if ring is not None:   # hold-progress ring
        cv2.ellipse(img, (cx, cy), (21, 21), -90, 0, 360 * ring, (255, 255, 255), 3, cv2.LINE_AA)
    return img


def _action_origin(pos):
    return pos[0] + 28, pos[1] + 15


def _scroll(tex: np.ndarray, w: int, h: int, t: float) -> np.ndarray:
    """Slowly drifting crop of a bigger texture (ping-pong so it never jumps)."""
    def tri(speed, span):
        if span <= 0:
            return 0
        p = (t * speed) % (2 * span)
        return int(p if p < span else 2 * span - p)
    oy, ox = tri(9, tex.shape[0] - h), tri(6, tex.shape[1] - w)
    return tex[oy:oy + h, ox:ox + w].astype(np.float32)


# --------------------------------------------------------------------------
# The simulated game
# --------------------------------------------------------------------------
class SimGame:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = "idle"          # idle -> line_out -> minigame -> caught -> prompt -> idle
        self.t_last = time.perf_counter()
        self.physics = ord("1")
        self.zone_speed = 0.3
        self.mouse = self.t_key = False
        self.t_hold_start = 0.0
        self.catches = self.escapes = self.wrong_t = 0
        self.progress = 0.0
        self.box = self.vel = 0.0
        self.zone = self.zone_goal = 0.5
        self.next_goal_t = 0.0
        self.item = ""
        self.prompt_pos = (170, 180)

        self.bar_tex = _ocean(BAR_W * 2, BAR_H * 2, seed=3, islands=10)
        self.prompt_tex = _ocean(PROMPT_W * 2, PROMPT_H * 2, seed=7, islands=4)
        shape = (BAR_H, BAR_W)
        self.bar_mask = _rounded(shape, OUT_X0, OUT_TOP, OUT_X1, OUT_BOT, RADIUS)
        inner = _rounded(shape, OUT_X0 + 2, OUT_TOP + 2, OUT_X1 - 2, OUT_BOT - 2, RADIUS - 2)
        self.outline = self.bar_mask & ~inner
        # The see-through inside gets darker towards the bottom (like the real bar).
        fade = np.clip((np.arange(BAR_H) - OUT_TOP) / (OUT_BOT - OUT_TOP), 0, 1)
        factor = (0.72 - 0.39 * fade).astype(np.float32)[:, None, None]
        self.darken = np.where(self.bar_mask[..., None], factor, np.float32(1.0))
        self.ticks = np.zeros(shape, bool)
        for i, y in enumerate(range(IN_TOP + 10, IN_BOT - 8, 11)):
            length = 20 if i % 5 == 0 else 10
            self.ticks[y:y + 2, OUT_X0 + 7:OUT_X0 + 7 + length] = True
        g = np.linspace(238, 196, BOX, dtype=np.float32)[:, None, None]
        self.box_sprite = np.repeat(np.repeat(g, BOX, axis=1), 3, axis=2) + np.float32([6, 2, 0])
        self.box_mask = _rounded((BOX, BOX), 0, 0, BOX - 1, BOX - 1, 5)

    # -- inputs from the bot (via SimInput) -----------------------------------
    def click(self) -> None:
        with self.lock:
            self.update()
            if self.state in ("idle", "line_out"):
                self.state = "line_out"
                self.bite_t = time.perf_counter() + random.uniform(*BITE_DELAY)
                log.info("line cast")

    def set_mouse(self, held: bool) -> None:
        with self.lock:
            self.update()
            self.mouse = held

    def set_t(self, held: bool) -> None:
        with self.lock:
            self.update()
            if held and not self.t_key:
                self.t_hold_start = time.perf_counter()
                if self.state != "prompt":
                    self.wrong_t += 1
                    log.warning("T pressed with no collect prompt - in the real game this "
                                "could trigger the Purchase prompt!")
            self.t_key = held

    # -- game logic -----------------------------------------------------------
    def update(self) -> None:
        now = time.perf_counter()
        dt = min(0.05, now - self.t_last)
        self.t_last = now
        if self.state == "line_out" and now >= self.bite_t:
            self.state = "minigame"
            self.box, self.vel, self.progress = 0.0, 0.0, 0.3
            self.zone = self.zone_goal = random.uniform(0.3, 0.7)
            self.next_goal_t = now + 0.8
            log.info("a fish bites! minigame on")
        elif self.state == "minigame":
            self._physics(dt, now)
        elif self.state == "caught" and now - self.caught_t > 0.4:
            self.state = "prompt"
            self.prompt_pos = (random.randint(120, 260), random.randint(140, 230))
            angle = random.uniform(0, 6.283)
            self.prompt_vel = (PROMPT_DRIFT * np.cos(angle), PROMPT_DRIFT * np.sin(angle))
            self.next_hop_t = now + random.uniform(0.3, 0.8)
        elif self.state == "prompt":
            self._move_prompt(dt, now)

    def _move_prompt(self, dt: float, now: float) -> None:
        """The caught item bobs around, and every so often jumps, taking its prompt along."""
        x, y = self.prompt_pos
        vx, vy = self.prompt_vel
        x, y = x + vx * dt, y + vy * dt
        x0, x1, y0, y1 = 40, PROMPT_W - 260, 40, 250       # stays clear of the Purchase prompt
        if not x0 <= x <= x1:
            vx, x = -vx, min(x1, max(x0, x))
        if not y0 <= y <= y1:
            vy, y = -vy, min(y1, max(y0, y))
        if now >= self.next_hop_t:                          # a sudden hop
            x = min(x1, max(x0, x + random.choice((-1, 1)) * random.uniform(80, 160)))
            y = min(y1, max(y0, y + random.choice((-1, 1)) * random.uniform(40, 90)))
            self.next_hop_t = now + random.uniform(0.3, 0.8)
        self.prompt_pos, self.prompt_vel = (int(round(x)), int(round(y))), (vx, vy)
        if self.state == "prompt" and self.t_key and now - self.t_hold_start >= FILL_HOLD_S:
            self.state = "idle"
            self.catches += 1
            log.info("collected %s", self.item)

    def _physics(self, dt: float, now: float) -> None:
        _, up, down, vmax_up, vmax_down = PHYSICS[self.physics]
        if up is None:       # "Instant": holding sets the speed directly
            self.vel = vmax_up if self.mouse else -vmax_down
        else:
            self.vel += (up if self.mouse else -down) * dt
            self.vel = max(-vmax_down, min(vmax_up, self.vel))
        self.box += self.vel * dt
        if self.box <= 0 or self.box >= 1:
            self.box = min(1.0, max(0.0, self.box))
            self.vel = 0.0
        # The zone wanders to random spots, like a fish darting around.
        if now >= self.next_goal_t:
            self.zone_goal = random.uniform(0.1, 0.9)
            self.next_goal_t = now + random.uniform(0.5, 1.6)
        step = self.zone_speed * dt
        self.zone += max(-step, min(step, self.zone_goal - self.zone))
        inside = abs(self.box - self.zone) <= ZONE_HALF
        self.progress += (0.35 if inside else -0.2) * dt
        if self.progress >= 1.0:
            self.state, self.caught_t = "caught", now
            self.item = random.choice(ITEMS)
            log.info("fish caught (%s)", self.item)
        elif self.progress <= 0.0:
            self.state = "idle"
            self.escapes += 1
            log.info("the fish escaped")

    # -- rendering ------------------------------------------------------------
    @staticmethod
    def _y(frac: float) -> int:
        """Box/zone centre fraction (0 = bottom) -> pixel y."""
        return int(round(IN_BOT - BOX / 2 - frac * TRAVEL))

    def render_bar(self, force_visible: bool = False) -> np.ndarray:
        img = _scroll(self.bar_tex, BAR_W, BAR_H, self.t_last)
        if self.state == "minigame" or force_visible:
            img *= self.darken
            _blend(img, self.ticks, (150, 140, 130), 0.45)
            zy = self._y(self.zone)
            zone = _rounded(img.shape, OUT_X0 - 4, zy - ZONE_H // 2, OUT_X1 + 4, zy + ZONE_H // 2, 6)
            zone_in = _rounded(img.shape, OUT_X0 - 2, zy - ZONE_H // 2 + 2, OUT_X1 + 2, zy + ZONE_H // 2 - 2, 5)
            _blend(img, zone_in, (45, 205, 205), 0.33)
            _blend(img, zone & ~zone_in, (70, 235, 235), 0.9)
            by = self._y(self.box) - BOX // 2
            bx = (OUT_X0 + OUT_X1) // 2 - BOX // 2
            patch = img[by:by + BOX, bx:bx + BOX]
            patch[self.box_mask] = self.box_sprite[self.box_mask]
            _blend(img, self.outline, (235, 220, 205), 0.5)
        return img.astype(np.uint8)

    def render_prompt(self, force_visible: bool = False) -> np.ndarray:
        img = _scroll(self.prompt_tex, PROMPT_W, PROMPT_H, self.t_last).astype(np.uint8)
        # A shop prompt that always sits here, like the rod shop next to the real
        # fishing spot. The bot must never press T for it.
        img = _draw_prompt(img, DECOY_POS, "Rare Fishing Rod", "Purchase")
        if self.state == "prompt" or force_visible:
            ring = None
            if self.t_key and self.state == "prompt":
                ring = min(1.0, (time.perf_counter() - self.t_hold_start) / FILL_HOLD_S)
            img = _draw_prompt(img, self.prompt_pos, self.item or "Metal Scraps", "Collect", ring)
        return img


class SimCapture:
    """Stands in for ScreenCapture: returns simulated frames."""

    def __init__(self, game: SimGame):
        self.game = game

    def grab(self, region):
        with self.game.lock:
            self.game.update()
            if region[0] >= PROMPT_REGION_X:
                return self.game.render_prompt()
            return self.game.render_bar()


class SimInput:
    """Stands in for InputController: presses go to the simulated game only."""

    def __init__(self, game: SimGame):
        self.game = game
        self._mouse_held = False
        self._keys: set[str] = set()

    def move_to(self, x, y):
        pass

    def mouse_down(self):
        self._mouse_held = True
        self.game.set_mouse(True)

    def mouse_up(self):
        self._mouse_held = False
        self.game.set_mouse(False)

    def set_mouse(self, hold):
        self.mouse_down() if hold else self.mouse_up()

    def click(self, hold_s=0.08):
        self.mouse_down()
        time.sleep(hold_s)
        self.mouse_up()
        self.game.click()

    @property
    def mouse_held(self):
        return self._mouse_held

    def key_down(self, key):
        self._keys.add(key)
        self.game.set_t(True)

    def key_up(self, key):
        self._keys.discard(key)
        self.game.set_t(False)

    def release_all(self, force=False):
        self.mouse_up()
        for key in list(self._keys):
            self.key_up(key)


class _PanelLog(logging.Handler):
    """Keeps the last few log lines for the on-screen event log."""

    def __init__(self):
        super().__init__()
        self.lines = collections.deque(maxlen=13)

    def emit(self, record):
        self.lines.append((record.name, time.strftime("%H:%M:%S"), record.getMessage()))


# --------------------------------------------------------------------------
# The simulator window
# --------------------------------------------------------------------------
STATE_BGR = {"Casting": (255, 163, 74), "Waiting": (178, 164, 154), "Minigame": (66, 197, 245),
             "Collecting": (125, 208, 76), "Paused": (76, 138, 255), "Stopped": (92, 92, 255)}
BG = (36, 30, 27)
WHITE, MUTED, CYAN, GREEN = (235, 235, 235), (178, 164, 154), (230, 220, 90), (125, 208, 76)
ROW1_H, BOT_VIEW_W, STATUS_W = 712, 960, 340
TOTAL_W = BAR_W + BOT_VIEW_W + STATUS_W


def _text(img, s, x, y, scale=0.5, colour=WHITE, thick=1):
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thick, cv2.LINE_AA)


def _fit(img, w, h):
    """Pad (or shrink) to exactly w x h."""
    if img.shape[1] > w or img.shape[0] > h:
        f = min(w / img.shape[1], h / img.shape[0])
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    out = np.full((h, w, 3), BG, np.uint8)
    out[:img.shape[0], :img.shape[1]] = img
    return out


def _header(img, title):
    head = np.full((22, img.shape[1], 3), BG, np.uint8)
    _text(head, title, 6, 16, 0.5, CYAN)
    return np.vstack([head, img])


class Simulator:
    def __init__(self, cfg: dict):
        self.game = SimGame()
        cfg = copy.deepcopy(cfg)

        # "Calibrate" on the simulated screen, exactly like the real calibration does.
        probe = copy.deepcopy(cfg)
        probe["bar_expected"] = None
        found = BarDetector(probe).analyze(self.game.render_bar(force_visible=True)).bar
        if found is None:
            raise RuntimeError("The detector could not find the simulated bar")
        # Save the T circle and the word "Collect", like calibration step 2 does.
        self.game.item = "Metal Scraps"
        shot = self.game.render_prompt(force_visible=True)
        cx, cy = self.game.prompt_pos
        template = Path(tempfile.gettempdir()) / "slayers2_sim_collect_t.png"
        cv2.imwrite(str(template), shot[cy - 18:cy + 19, cx - 18:cx + 19])
        (tw, th), base = cv2.getTextSize("Collect", ACTION_FONT, ACTION_SCALE, 1)
        wx, wy = _action_origin(self.game.prompt_pos)
        word = Path(tempfile.gettempdir()) / "slayers2_sim_collect_word.png"
        cv2.imwrite(str(word), shot[wy - th - 2:wy + base + 2, wx - 2:wx + tw + 2])
        self.game.item = ""

        cfg.update(calibrated=True, bar_region=[0, 0, BAR_W, BAR_H], bar_expected=found.to_dict(),
                   cast_point=[BAR_W // 2, BAR_H // 2],
                   collect_region=[PROMPT_REGION_X, 0, PROMPT_W, PROMPT_H],
                   collect_template=str(template), collect_word_template=str(word))
        cfg["detection"]["use_ocr"] = False
        cfg["camera"]["enabled"] = False     # there is no real camera in the simulation
        self.cfg = cfg
        self.expected = found

        # The real bot, with the screen and input swapped for the simulation.
        bot_module.cursor_in_failsafe_corner = lambda: False
        # Never send Discord messages about simulated catches.
        quiet = copy.deepcopy(cfg)
        quiet["notifications"]["webhook_url"] = ""
        self.bot = FishingBot(cfg, debug=False, notifier=Notifier(quiet))
        self.bot.capture = SimCapture(self.game)
        self.bot.inp = SimInput(self.game)
        self.bot.window.is_focused = lambda: True

        # Separate detector copies for the "what the bot sees" view.
        self.view_bar_det = BarDetector(cfg)
        self.view_prompt_det = PromptDetector(cfg, template, word)
        self.panel_log = _PanelLog()
        logging.getLogger().addHandler(self.panel_log)

    # -- one frame of the window ----------------------------------------------
    def compose(self) -> np.ndarray:
        g = self.game
        with g.lock:
            g.update()
            bar_frame, prompt_frame = g.render_bar(), g.render_prompt()
            game_state, progress, physics = g.state, g.progress, PHYSICS[g.physics][0]
            zone_speed, g_catches, g_escapes = g.zone_speed, g.catches, g.escapes
            wrong_t = g.wrong_t
        status = self.bot.status.snapshot()

        reading = self.view_bar_det.analyze(bar_frame, locked=self.expected if game_state == "minigame" else None)
        ctrl = self.bot.ctrl.state if status.state == "Minigame" else None
        bot_view = annotate_minigame(bar_frame, reading, self.expected if reading.visible else None, ctrl)
        match = self.view_prompt_det.find(prompt_frame)
        score = match.score if match else self.view_prompt_det.best_score(prompt_frame)
        prompt_view = annotate_prompt(prompt_frame, match, score)

        game_panel = _fit(_header(bar_frame, "GAME (simulated)"), BAR_W, ROW1_H)
        bot_panel = _fit(_header(bot_view, "WHAT THE BOT SEES  (magenta bar, yellow zone, green box, cyan aim)"),
                         BOT_VIEW_W, ROW1_H)
        status_panel = self._status_panel(status, game_state, progress, physics, zone_speed, g_catches, g_escapes, wrong_t)
        row1 = np.hstack([game_panel, bot_panel, status_panel])

        prompt_panel = _header(prompt_view, "COLLECT PROMPT AREA (game + bot detection)")
        log_panel = self._log_panel(TOTAL_W - prompt_panel.shape[1], prompt_panel.shape[0])
        row2 = np.hstack([prompt_panel, log_panel])
        return np.vstack([row1, row2])

    def _status_panel(self, s, game_state, progress, physics, zone_speed, g_catches, g_escapes, wrong_t):
        p = np.full((ROW1_H, STATUS_W, 3), BG, np.uint8)
        _text(p, "BOT", 14, 30, 0.5, MUTED)
        _text(p, s.state, 14, 66, 1.05, STATE_BGR.get(s.state, WHITE), 2)
        _text(p, s.detail[:34], 14, 92, 0.45, MUTED)
        _text(p, f"Minigames {s.minigames}   Collected {s.catches}", 14, 130, 0.6)
        _text(p, f"No prompt {s.no_prompt}   Recasts {s.recasts}", 14, 156, 0.6)
        _text(p, f"Collect failed {s.failed}", 14, 182, 0.6, WHITE if s.failed == 0 else (60, 60, 255))
        _text(p, f"{s.fps:5.1f} fps" if s.state in ("Waiting", "Minigame") else "   -- fps", 14, 208, 0.5, MUTED)

        held = self.bot.inp.mouse_held
        cv2.rectangle(p, (14, 228), (326, 262), GREEN if held else (60, 55, 50), -1)
        _text(p, "LEFT MOUSE: " + ("HOLD" if held else "released"), 24, 251, 0.55, (20, 20, 20) if held else WHITE)
        t_held = bool(self.bot.inp._keys)
        cv2.rectangle(p, (14, 270), (326, 304), GREEN if t_held else (60, 55, 50), -1)
        _text(p, "T KEY: " + ("HELD" if t_held else "up"), 24, 293, 0.55, (20, 20, 20) if t_held else WHITE)

        cv2.line(p, (14, 322), (326, 322), (70, 65, 60), 1)
        _text(p, "GAME (simulated)", 14, 348, 0.5, MUTED)
        _text(p, {"idle": "idle", "line_out": "line in the water", "minigame": "minigame",
                  "caught": "fish caught!", "prompt": "collect prompt shown"}[game_state], 14, 374, 0.6)
        if game_state == "minigame":
            cv2.rectangle(p, (14, 388), (326, 408), (70, 65, 60), 1)
            fill = int(14 + 312 * max(0.0, min(1.0, progress)))
            colour = GREEN if progress > 0.35 else (76, 138, 255)
            cv2.rectangle(p, (15, 389), (fill, 407), colour, -1)
            _text(p, f"catch progress {progress:4.0%}", 14, 428, 0.45, MUTED)
        _text(p, f"Collected {g_catches}   Escaped {g_escapes}   Wrong T {wrong_t}", 14, 458, 0.55,
              WHITE if wrong_t == 0 else (60, 60, 255))
        _text(p, f"Box physics: {physics}", 14, 490, 0.55, CYAN)
        _text(p, f"Zone speed:  {zone_speed:.1f} bar/s", 14, 514, 0.55, CYAN)

        cv2.line(p, (14, 534), (326, 534), (70, 65, 60), 1)
        help_lines = ["1 Measured  2 Momentum", "3 Floaty  4 Heavy  5 Instant", "- / +  zone slower / faster",
                      "P  pause / resume bot", "Q  quit"]
        for i, line in enumerate(help_lines):
            _text(p, line, 14, 560 + 24 * i, 0.48, MUTED)
        _text(p, "No input is sent to Windows.", 14, 696, 0.42, (120, 110, 100))
        return p

    def _log_panel(self, w, h):
        p = np.full((h, w, 3), BG, np.uint8)
        _text(p, "EVENT LOG", 12, 22, 0.5, CYAN)
        with self.panel_log.lock:           # the bot thread logs while we draw
            lines = list(self.panel_log.lines)
        for i, (name, stamp, msg) in enumerate(lines):
            colour = (230, 190, 120) if name == "game" else WHITE
            prefix = "game" if name == "game" else "bot "
            _text(p, f"{stamp} {prefix}  {msg}"[:110], 12, 48 + 25 * i, 0.47, colour)
        return p

    # -- keys -------------------------------------------------------------------
    def handle_key(self, key: int) -> bool:
        """Returns False when the user wants to quit."""
        g = self.game
        if key in (ord("q"), ord("Q"), 27):
            return False
        if key in PHYSICS:
            with g.lock:
                g.physics = key
            log.info("physics -> %s", PHYSICS[key][0])
        elif key in (ord("-"), ord("_")):
            with g.lock:
                g.zone_speed = max(0.1, round(g.zone_speed - 0.1, 1))
        elif key in (ord("+"), ord("=")):
            with g.lock:
                g.zone_speed = min(1.0, round(g.zone_speed + 0.1, 1))
        elif key in (ord("p"), ord("P")):
            self.bot.pause() if self.bot.running.is_set() else self.bot.start()
        return True

    # -- main loops ---------------------------------------------------------------
    def run(self, record: str | None = None, seconds: float | None = None) -> None:
        worker = threading.Thread(target=self.bot.run, name="bot", daemon=True)
        worker.start()
        self.bot.start()
        log.info("simulation started - the real bot is playing")
        writer = None
        win = "Slayers 2 Auto-Fisher - SIMULATION"
        scale = 1.0
        if record:
            writer = cv2.VideoWriter(record, cv2.VideoWriter_fourcc(*"mp4v"), 30, (TOTAL_W, ROW1_H + 400))
        else:
            _, _, sw, sh = primary_monitor_rect()
            scale = min(1.0, 0.96 * sw / TOTAL_W, 0.88 * sh / (ROW1_H + 400))
            cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        start = time.perf_counter()
        written = 0
        try:
            while True:
                t0 = time.perf_counter()
                frame = self.compose()
                if writer is not None:
                    # Repeat frames if drawing fell behind, so the video plays in real time.
                    due = int((time.perf_counter() - start) * 30) + 1
                    frame = _fit(frame, TOTAL_W, ROW1_H + 400)
                    for _ in range(max(1, due - written)):
                        writer.write(frame)
                        written += 1
                    if time.perf_counter() - start >= (seconds or 60):
                        break
                    time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - t0)))
                    continue
                if scale < 1.0:
                    frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                cv2.imshow(win, frame)
                wait = max(1, int(1000 / 30 - (time.perf_counter() - t0) * 1000))
                if not self.handle_key(cv2.waitKey(wait) & 0xFF):
                    break
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            self.bot.quit("simulator closed")
            worker.join(timeout=2)
            if writer is not None:
                writer.release()
            cv2.destroyAllWindows()
        s = self.bot.status.snapshot()
        print(f"\nSimulation over: bot played {s.minigames} minigames, collected {s.catches}, "
              f"no prompt {s.no_prompt}, collect failed {s.failed}, recasts {s.recasts}. "
              f"Game: {self.game.catches} collected, {self.game.escapes} escaped.")


def run_simulation(cfg: dict, record: str | None = None, seconds: float | None = None) -> None:
    Simulator(cfg).run(record=record, seconds=seconds)
