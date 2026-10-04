"""
Computer-vision detection for the fishing minigame and the collect prompt.

All coordinates returned here are relative to the captured region (the
calibrated bar region or collect region), with y growing downwards like in
any image.

How the bar is found
--------------------
The bar is *semi-transparent*: its inside is the water behind it, darkened by
roughly 25-65 % (more towards the bottom). Absolute colours therefore change
with the background, but two things don't:
  * the inside is always clearly darker than the water just left/right of it
  * that brightness step happens along two straight vertical lines
So for every column we count how many rows show a "bright -> dark" step (left
edge) or a "dark -> bright" step (right edge), and pick the best pair.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
@dataclass
class BarGeometry:
    x0: int          # first column inside the bar
    x1: int          # last column inside the bar
    top: int
    bottom: int
    edge_score: float = 0.0   # how much of the bar's height shows both edges (0-1)

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    def to_fraction(self, y: float) -> float:
        """Image y -> height inside the bar (0.0 = bottom, 1.0 = top)."""
        return (self.bottom - y) / max(1, self.bottom - self.top)

    def to_dict(self) -> dict:
        return {"x0": self.x0, "x1": self.x1, "top": self.top, "bottom": self.bottom}

    @classmethod
    def from_dict(cls, d: dict) -> "BarGeometry":
        return cls(d["x0"], d["x1"], d["top"], d["bottom"])


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class MinigameReading:
    """Everything found in one frame of the bar region."""
    bar: BarGeometry | None = None     # bar found by its edges this frame
    zone: Rect | None = None
    box: Rect | None = None
    masks: dict = field(default_factory=dict)   # for debug images

    @property
    def visible(self) -> bool:
        """Minigame on screen = the bar itself was found. (Never the zone alone:
        with the bar gone, a lily pad can look just like the zone.)"""
        return self.bar is not None


@dataclass
class PromptMatch:
    rect: Rect
    score: float
    method: str      # "template", "circle" or "ocr"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _longest_run(flags: np.ndarray, max_gap: int = 0) -> tuple[int, int] | None:
    """
    Longest stretch of True values in a 1-D bool array, bridging gaps of up
    to ``max_gap`` False values. Returns (start, end) inclusive, or None.
    """
    idx = np.flatnonzero(flags)
    if idx.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(idx) > max_gap + 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    best = int(np.argmax(ends - starts))
    return int(starts[best]), int(ends[best])


def _peaks(score: np.ndarray, threshold: float, spacing: int = 3, limit: int = 6) -> list[int]:
    """Indices of the strongest local maxima above ``threshold``."""
    order = np.argsort(score)[::-1]
    picked: list[int] = []
    for i in order:
        if score[i] < threshold or len(picked) >= limit:
            break
        if all(abs(int(i) - p) > spacing for p in picked):
            picked.append(int(i))
    return picked


def _largest_component(mask: np.ndarray, accept) -> Rect | None:
    """Largest connected blob in ``mask`` whose (w, h, area) passes ``accept``."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    best, best_area = None, 0
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area > best_area and accept(w, h, area):
            best, best_area = Rect(x, y, w, h), area
    return best


# --------------------------------------------------------------------------
# Minigame bar
# --------------------------------------------------------------------------
class BarDetector:
    """Finds the fishing bar, the yellow target zone and the white player box."""

    def __init__(self, cfg: dict):
        self.d = cfg["detection"]
        self.expected = cfg.get("bar_expected")

    # -- per-pixel masks ------------------------------------------------------
    def _masks(self, img: np.ndarray) -> dict:
        d = self.d
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        # "yellow" = the target zone, in its yellow or its green state
        yellow = ((h >= d["zone_h_min"]) & (h <= d["zone_h_max"])
                  & (s >= d["zone_s_min"]) & (v >= d["zone_v_min"]))
        white = (v >= d["box_v_min"]) & (s <= d["box_s_max"])
        into_dark, out_of_dark = self._edge_maps(v)
        return {"v": v, "yellow": yellow, "white": white,
                "into_dark": into_dark, "out_of_dark": out_of_dark}

    def _edge_maps(self, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        into_dark[y, x]  : pixels right of x are clearly darker than pixels left of it
        out_of_dark[y, x]: pixels right of x are clearly brighter than pixels left of it
        (x is the first column of the right-hand window.) Edges within
        ``edge_window_px`` of the image border are left False.
        """
        d = self.d
        k = int(d["edge_window_px"])
        H, W = v.shape
        into_dark = np.zeros((H, W), bool)
        out_of_dark = np.zeros((H, W), bool)
        if W < 2 * k + 1:
            return into_dark, out_of_dark
        # mean[:, x] = average of columns x .. x+k-1
        mean = cv2.blur(v.astype(np.float32), (k, 1), anchor=(0, 0))
        left = mean[:, 0:W - 2 * k + 1]     # columns x-k .. x-1, for x = k .. W-k
        right = mean[:, k:W - k + 1]        # columns x .. x+k-1
        ratio, step = d["edge_max_ratio"], d["edge_min_step"]
        diff = left - right
        into_dark[:, k:W - k + 1] = (right <= ratio * left) & (diff >= step)
        out_of_dark[:, k:W - k + 1] = (left <= ratio * right) & (diff <= -step)
        return into_dark, out_of_dark

    # -- the bar itself -------------------------------------------------------
    def _find_bar(self, m: dict) -> BarGeometry | None:
        d = self.d
        into_dark, out_of_dark = m["into_dark"], m["out_of_dark"]
        H, W = into_dark.shape

        # 1. Candidate edges: columns where the step shows up on many rows.
        left_score = into_dark.mean(axis=0)
        right_score = out_of_dark.mean(axis=0)
        thr = d["edge_min_coverage"]
        lefts, rights = _peaks(left_score, thr), _peaks(right_score, thr)

        # 2. Pick the strongest left/right pair that looks like the bar.
        tol = d["bar_size_tolerance"]
        exp = self.expected
        best = None
        for lx in lefts:
            for rx in rights:
                width = rx - lx          # inside columns are lx .. rx-1
                if width < 4:
                    continue
                if exp:
                    exp_w = exp["x1"] - exp["x0"] + 1
                    if (abs(width - exp_w) > tol * exp_w + 2
                            or abs(lx - exp["x0"]) > tol * exp_w + 2):
                        continue
                score = left_score[lx] + right_score[rx]
                if best is None or score > best[0]:
                    best = (score, lx, rx)
        if best is None:
            return None
        _, x0, rx = best
        x1 = rx - 1
        width = x1 - x0 + 1

        # 3. Vertical extent: rows showing either edge, or the zone (which can
        #    hide the edges where it overlaps them). White rows don't count:
        #    bright fog or sky above the bar would stretch it.
        l_rows = into_dark[:, max(0, x0 - 1):x0 + 2].any(axis=1)
        r_rows = out_of_dark[:, max(0, rx - 1):rx + 2].any(axis=1)
        zone_rows = m["yellow"][:, x0:x1 + 1].mean(axis=1) >= 0.3
        rows = _longest_run(l_rows | r_rows | zone_rows, max_gap=max(3, int(0.03 * H)))
        if rows is None:
            return None
        top, bottom = rows
        height = bottom - top + 1

        # 4. Shape sanity checks: tall and narrow, edges along most of it.
        if height < d["bar_min_height_frac"] * H or height < d["bar_min_aspect"] * width:
            return None
        span = slice(top, bottom + 1)
        edge_score = float((l_rows[span].mean() + r_rows[span].mean()) / 2)
        if edge_score < d["bar_min_edge_score"]:
            return None
        return BarGeometry(x0, x1, top, bottom, edge_score)

    # -- target zone ----------------------------------------------------------
    def _find_zone(self, m: dict, bar: BarGeometry) -> Rect | None:
        H, W = m["yellow"].shape
        # The zone sticks out a few px past the bar, so search slightly outside
        # it - but not so far that lily pads beside the bar get included.
        pad = max(4, int(0.15 * bar.width))
        xa, xb = max(0, bar.x0 - pad), min(W, bar.x1 + pad + 1)
        ya, yb = max(0, bar.top - 4), min(H, bar.bottom + 5)
        mask = m["yellow"][ya:yb, xa:xb].astype(np.uint8)
        # Close small gaps so a patchy fill (+ outline) becomes one blob.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        # The zone is always about the same height relative to the bar.
        expected_h = self.d["zone_height_frac"] * bar.height
        tol = self.d["size_tolerance"]
        best, best_err = None, None
        for i in range(1, n):
            x, y, w, h = (int(v) for v in stats[i, :4])
            if w < 0.6 * bar.width or h < 3:
                continue
            # Trim thin slivers stuck to the top/bottom of the blob (the bar's
            # see-through outline over a lily pad, the fishing line): keep the
            # rows where the blob covers a good share of its own width.
            rows = _longest_run((labels[y:y + h, x:x + w] == i).mean(axis=1) >= 0.35, max_gap=4)
            if rows is None:
                continue
            h = rows[1] - rows[0] + 1
            err = abs(h - expected_h) / expected_h
            if err <= tol + 0.2 and (best_err is None or err < best_err):
                best, best_err = Rect(xa + x, ya + y + rows[0], w, h), err
        return best

    # -- white player box -----------------------------------------------------
    def _find_box(self, m: dict, bar: BarGeometry) -> Rect | None:
        d = self.d
        # Stay away from the outline on the left/right edges.
        inset = max(1, int(0.1 * bar.width))
        xa, xb = bar.x0 + inset, bar.x1 - inset + 1
        ya, yb = max(0, bar.top), bar.bottom + 1
        if xb - xa < 3:
            return None
        mask = m["white"][ya:yb, xa:xb].astype(np.uint8)
        # Opening erases anything thinner than 3 px: tick marks, outline slivers.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        # The zone's border line can cut across the box and split it in two;
        # a tall, thin closing joins the halves back up.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8))
        # The box is always about the same size relative to the bar's width.
        # This rejects bright fog or buildings showing through the bar.
        side = d["box_size_frac"] * bar.width
        lo, hi = max(3.0, (1 - d["size_tolerance"]) * side), (1 + d["size_tolerance"]) * side
        max_aspect = d["box_max_aspect"]

        def square_enough(w, h, area):
            return (lo <= w <= hi and lo <= h <= hi
                    and max(w / h, h / w) <= max_aspect
                    and area >= 0.5 * w * h)

        r = _largest_component(mask, square_enough)
        return Rect(r.x + xa, r.y + ya, r.w, r.h) if r else None

    # -- public API -----------------------------------------------------------
    def analyze(self, img: np.ndarray, locked: BarGeometry | None = None) -> MinigameReading:
        """
        Look for the bar in ``img`` and, if we know where it is, the zone and
        box inside it. ``locked`` is the geometry fixed at the start of the
        minigame, so positions are measured the same way every frame.
        """
        m = self._masks(img)
        reading = MinigameReading(masks=m)
        reading.bar = self._find_bar(m)
        if reading.bar is not None:          # only look inside a bar that's really there
            geom = locked or reading.bar
            reading.zone = self._find_zone(m, geom)
            reading.box = self._find_box(m, geom)
        return reading


# --------------------------------------------------------------------------
# Water (where to cast)
# --------------------------------------------------------------------------
def nearest_water(img: np.ndarray, point: tuple[int, int], d: dict,
                  margin: int) -> tuple[int, int] | None:
    """
    In Slayers 2 a cast click only works on water; clicking the dock does
    nothing. If the camera has turned, the calibrated cast spot can end up on
    the dock, so find the open water closest to ``point`` (image coords),
    at least ``margin`` px from anything that isn't water.
    Returns None if there's no water in ``img``.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    water = ((h >= d["water_h_min"]) & (h <= d["water_h_max"])
             & (s >= d["water_s_min"]) & (v >= d["water_v_min"])).astype(np.uint8)
    # Light wave streaks are less saturated; closing folds them into the water.
    water = cv2.morphologyEx(water, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if margin > 0:
        water = cv2.erode(water, np.ones((2 * margin + 1, 2 * margin + 1), np.uint8))
    px, py = point
    if 0 <= py < water.shape[0] and 0 <= px < water.shape[1] and water[py, px]:
        return point
    ys, xs = np.nonzero(water)
    if xs.size == 0:
        return None
    i = int(np.argmin((xs - px) ** 2 + (ys - py) ** 2))
    return int(xs[i]), int(ys[i])


# --------------------------------------------------------------------------
# Collect prompt
# --------------------------------------------------------------------------
def _load_gray(path):
    if path is None or not path.exists():
        return None
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None or not img.size:
        return None
    log.info("Loaded template %s (%dx%d)", path.name, img.shape[1], img.shape[0])
    return img


class PromptDetector:
    """
    Finds the collect prompt:   (T)  Metal Scraps
                                     Collect
    Other prompts in the game look exactly the same apart from the action
    word, e.g. "(T) Rare Fishing Rod / Purchase" right next to the fishing
    spot. So the word "Collect" must be found before the bot presses T:
      1. the "Collect" word template, confirmed by the T-circle template to
         its left (if that is calibrated too)
      2. OCR for "Collect" (if pytesseract + Tesseract are installed)
      3. ONLY if require_collect_word is false: the T circle alone
         (template, or its shape if there is no template)
    """

    OCR_MIN_INTERVAL_S = 0.4

    def __init__(self, cfg: dict, template_path=None, word_path=None):
        self.d = cfg["detection"]
        self.template = _load_gray(template_path)   # the white "T" circle
        self.word = _load_gray(word_path)           # the word "Collect"
        self._tess = self._init_ocr() if self.d["use_ocr"] else None
        self.scale: float | None = None   # prompt size (vs. the templates) last seen
        self._cache: dict = {}            # resized templates
        self._last_ocr_t = 0.0
        self._last_ocr_result: PromptMatch | None = None
        if not self.can_verify_word:
            log.warning("The word 'Collect' can't be checked (no word template, no OCR). "
                        + ("The bot will NOT press T. Run: python main.py --calibrate-collect"
                           if self.d["require_collect_word"] else
                           "require_collect_word is off: T may be pressed on ANY T prompt!"))

    @classmethod
    def from_config(cls, cfg: dict) -> "PromptDetector":
        from config import resolve_path
        return cls(cfg, resolve_path(cfg["collect_template"]),
                   resolve_path(cfg["collect_word_template"]))

    @property
    def can_verify_word(self) -> bool:
        return self.word is not None or self._tess is not None

    def _init_ocr(self):
        try:
            import pytesseract
        except ImportError:
            log.info("pytesseract not installed; OCR fallback disabled")
            return None
        if self.d.get("tesseract_cmd"):
            pytesseract.pytesseract.tesseract_cmd = self.d["tesseract_cmd"]
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            log.info("Tesseract program not found; OCR fallback disabled")
            return None
        log.info("OCR fallback enabled")
        return pytesseract

    @property
    def methods(self) -> list[str]:
        out = []
        if self.word is not None:
            out.append("word" + ("+circle" if self.template is not None else ""))
        if self._tess is not None:
            out.append("ocr")
        if not self.d["require_collect_word"]:
            out.append("circle-only (UNSAFE)")
        return out

    def find(self, img: np.ndarray, near: Rect | None = None) -> PromptMatch | None:
        """
        ``near`` is where the prompt was last seen. Pass it while holding T to
        check the prompt is still there: only that neighbourhood is searched
        and a slightly lower score is accepted (the hold-progress ring and
        the button-press animation change the prompt a little).
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self.word is not None:
            hit = self._match_word(gray, near)
            if hit:
                return hit
        if self._tess is not None:
            hit = self._match_ocr(img, keep=near is not None)
            if hit:
                return hit
        if self.d["require_collect_word"]:
            return None
        # Unsafe fallback: any T circle counts.
        if self.template is not None:
            return self._match_circle_template(gray, near)
        if self.d["use_circle_fallback"]:
            return self._match_circle(img)
        return None

    def best_score(self, img: np.ndarray) -> float | None:
        """Best raw score of the main template (word, else circle), for debug views."""
        tpl = self.word if self.word is not None else self.template
        if tpl is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        peaks = self._search(gray, tpl, self._scales(), -1.0, limit=1)
        return peaks[0][0] if peaks else None

    # -- prompt size ------------------------------------------------------------
    # The prompt is drawn in the 3D world, so it gets bigger or smaller as the
    # camera zooms in or out. Search a range of sizes, trying the size that
    # worked last time first (fast), then the whole range.
    def _scales(self, around: float | None = None) -> list[float]:
        lo, hi, step = (self.d["prompt_scale_min"], self.d["prompt_scale_max"],
                        self.d["prompt_scale_step"])
        if around is not None:
            return [round(s, 3) for s in (around - step, around, around + step) if lo <= s <= hi]
        return [round(lo + i * step, 3) for i in range(int(round((hi - lo) / step)) + 1)]

    def _resized(self, tpl: np.ndarray, scale: float) -> np.ndarray:
        key = (id(tpl), round(scale, 3))
        if key not in self._cache:
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            self._cache[key] = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=interp)
        return self._cache[key]

    # -- template helpers -----------------------------------------------------
    def _peaks(self, gray: np.ndarray, tpl: np.ndarray, scales, threshold: float,
               limit: int = 4) -> list[tuple[float, Rect, float]]:
        """Up to ``limit`` separate matches per scale scoring >= threshold, best first,
        as (score, rect, scale)."""
        out = []
        for scale in scales:
            t = self._resized(tpl, scale)
            th, tw = t.shape
            if th > gray.shape[0] or tw > gray.shape[1] or th < 4 or tw < 4:
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            for _ in range(limit):
                _, score, _, (x, y) = cv2.minMaxLoc(res)
                if score < threshold:
                    break
                out.append((float(score), Rect(x, y, tw, th), scale))
                # blank out this match so the next-best one elsewhere can be found
                res[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1
        out.sort(key=lambda p: -p[0])
        return out

    COARSE_MIN_PIXELS = 400_000   # search bigger areas at half resolution first

    def _search(self, gray, tpl, scales, threshold, limit=4) -> list[tuple[float, Rect, float]]:
        """
        Same as _peaks, but ~4x faster on big areas: find candidates at half
        resolution, then confirm each one at full resolution.
        """
        if gray.size < self.COARSE_MIN_PIXELS:
            return self._peaks(gray, tpl, scales, threshold, limit)
        small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        step = self.d["prompt_scale_step"]
        out = []
        for _, r, half in self._peaks(small, tpl, [s / 2 for s in scales], threshold - 0.25,
                                      max(limit, 6)):
            s = half * 2
            th, tw = (int(v * (s + step)) + 1 for v in tpl.shape)
            x0, y0 = max(0, 2 * r.x - 8), max(0, 2 * r.y - 8)
            window = gray[y0:y0 + th + 16, x0:x0 + tw + 16]
            for score, rr, sc in self._peaks(window, tpl, (s - step / 2, s, s + step / 2),
                                             threshold, limit=1):
                out.append((score, Rect(rr.x + x0, rr.y + y0, rr.w, rr.h), sc))
        out.sort(key=lambda p: -p[0])
        return out

    def _near_crop(self, gray, near: Rect | None):
        if near is None:
            return gray, 0, 0
        # The caught item can drift, so its prompt moves: look well around it.
        pad = max(near.w, near.h, int(self.d["prompt_follow_px"]))
        ox, oy = max(0, near.x - pad), max(0, near.y - pad)
        return gray[oy:near.y + near.h + pad, ox:near.x + near.w + pad], ox, oy

    # -- 1. the word "Collect" (+ the T circle to its left) -------------------
    def _match_word(self, gray, near: Rect | None):
        crop, ox, oy = self._near_crop(gray, near)
        need = self.d["word_keep_threshold"] if near else self.d["word_threshold"]
        attempts = ([self._scales(self.scale)] if self.scale else []) + [self._scales()]
        for scales in attempts:
            for score, r, scale in self._search(crop, self.word, scales, need):
                rect = Rect(r.x + ox, r.y + oy, r.w, r.h)
                # While holding T we only need "still there"; otherwise confirm the key circle.
                if (near is None and self.template is not None
                        and not self._circle_left_of(gray, rect, scale)):
                    continue
                self.scale = scale
                return PromptMatch(rect, score, "word")
        return None

    def _circle_left_of(self, gray, word: Rect, scale: float) -> bool:
        ch, cw = (int(v * scale) for v in self.template.shape)
        x0, x1 = max(0, word.x - int(3.5 * cw)), word.x + word.w // 3
        y0, y1 = max(0, word.y - 2 * ch), word.y + word.h + ch
        return bool(self._peaks(gray[y0:y1, x0:x1], self.template, self._scales(scale),
                                self.d["template_keep_threshold"], limit=1))

    # -- 3. unsafe: T circle alone --------------------------------------------
    def _match_circle_template(self, gray, near: Rect | None):
        crop, ox, oy = self._near_crop(gray, near)
        need = self.d["template_keep_threshold"] if near else self.d["template_threshold"]
        peaks = self._search(crop, self.template, self._scales(), need, limit=1)
        if not peaks:
            return None
        score, r, self.scale = peaks[0]
        return PromptMatch(Rect(r.x + ox, r.y + oy, r.w, r.h), score, "circle-template")

    # -- 2. white circle with a dark "T" --------------------------------------
    def _match_circle(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        s, v = hsv[:, :, 1], hsv[:, :, 2]
        white = ((v >= 200) & (s <= 60)).astype(np.uint8)
        contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w < 12 or h < 12 or w * h > 0.05 * white.size:
                continue
            # Fill the blob (so the dark "T" counts as inside), then find the
            # biggest circle that fits in it. This ignores glows or sparkles
            # that touch the circle and would spoil a plain roundness test.
            filled = np.zeros((h + 2, w + 2), np.uint8)
            cv2.drawContours(filled, [c], -1, 1, thickness=cv2.FILLED, offset=(1 - x, 1 - y))
            dist = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
            _, r, _, (px, py) = cv2.minMaxLoc(dist)
            if r < 6:
                continue
            cx, cy = px - 1 + x, py - 1 + y
            # The circle must hold a dark glyph, roughly centred.
            x0, y0 = int(max(0, cx - r)), int(max(0, cy - r))
            patch = v[y0:int(cy + r) + 1, x0:int(cx + r) + 1]
            yy, xx = np.mgrid[y0:y0 + patch.shape[0], x0:x0 + patch.shape[1]]
            inner = (xx - cx) ** 2 + (yy - cy) ** 2 <= (0.75 * r) ** 2
            dark = inner & (patch < 110)
            dark_frac = dark.sum() / max(1, inner.sum())
            if not 0.04 <= dark_frac <= 0.5:
                continue
            off = math.hypot(xx[dark].mean() - cx, yy[dark].mean() - cy)
            if off > 0.35 * r:
                continue
            score = 1.0 - off / r
            if best is None or score > best.score:
                ri = int(round(r))
                best = PromptMatch(Rect(int(cx) - ri, int(cy) - ri, 2 * ri, 2 * ri), score, "circle")
        return best

    # -- 3. OCR ---------------------------------------------------------------
    def _match_ocr(self, img, keep):
        now = time.monotonic()
        if now - self._last_ocr_t < self.OCR_MIN_INTERVAL_S:
            return self._last_ocr_result if keep else None
        self._last_ocr_t = now
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        inverted = 255 - gray       # dark text on light works best for Tesseract
        result = None
        try:
            data = self._tess.image_to_data(inverted, config="--psm 11",
                                            output_type=self._tess.Output.DICT)
            for i, word in enumerate(data["text"]):
                if "ollect" in word.lower() and float(data["conf"][i]) >= 40:
                    result = PromptMatch(
                        Rect(data["left"][i] // 2, data["top"][i] // 2,
                             data["width"][i] // 2, data["height"][i] // 2),
                        float(data["conf"][i]) / 100, "ocr")
                    break
        except Exception as e:  # never let OCR problems stop the bot
            log.warning("OCR failed: %s", e)
        self._last_ocr_result = result
        return result
