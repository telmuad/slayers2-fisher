"""
Text recognition with the OCR engine built into Windows 10/11 (no install).

Used by the quest helper to read prompts ("Angler Runo / Chat"), dialogue and
the dialogue's answer buttons by their words, so it works at any screen size
without calibration images.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class TextLine:
    text: str
    x: int          # bounding box in the image that was read (pixels)
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def simplify(text: str) -> str:
    """Lower case letters and digits only, so OCR slips in spacing and punctuation don't matter."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


class Ocr:
    def __init__(self):
        # Loaded here, not at the top, so fishing works even without these packages.
        import winrt.windows.foundation  # noqa: F401  (needed to await the engine's results)
        import winrt.windows.foundation.collections  # noqa: F401
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        engine = None
        if OcrEngine.is_language_supported(Language("en-US")):
            engine = OcrEngine.try_create_from_language(Language("en-US"))
        self.engine = engine or OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError("Windows text recognition isn't available. Add English under "
                               "Windows Settings > Time & language > Language.")
        self._loop = asyncio.new_event_loop()

    def read(self, img_bgr: np.ndarray, scale: float = 1.0) -> list[TextLine]:
        """Lines of text in the image, with boxes in the image's own pixels."""
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        img = img_bgr
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]
        if w < 40 or h < 40:      # the engine needs some size; pad tiny crops
            img = cv2.copyMakeBorder(img, 0, max(0, 40 - h), 0, max(0, 40 - w), cv2.BORDER_CONSTANT)
            h, w = img.shape[:2]
        bgra = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2BGRA))
        bitmap = SoftwareBitmap.create_copy_from_buffer(bgra.tobytes(), BitmapPixelFormat.BGRA8, w, h)
        result = self._loop.run_until_complete(self._recognize(bitmap))
        lines = []
        for line in result.lines:
            rects = [wd.bounding_rect for wd in line.words]
            if not rects:
                continue
            x0 = min(r.x for r in rects); y0 = min(r.y for r in rects)
            x1 = max(r.x + r.width for r in rects); y1 = max(r.y + r.height for r in rects)
            lines.append(TextLine(line.text, int(x0 / scale), int(y0 / scale),
                                  int((x1 - x0) / scale), int((y1 - y0) / scale)))
        return lines

    async def _recognize(self, bitmap):
        return await self.engine.recognize_async(bitmap)


def white_text(img_bgr: np.ndarray, v_min: int = 165, s_max: int = 70) -> np.ndarray:
    """
    Keep only white / light-grey text, as black on white. Game UI drawn straight
    over the world (the quest list over grass) is unreadable otherwise. Coloured
    text drops out, e.g. the quest list's green, struck-through finished lines.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = (hsv[..., 2] >= v_min) & (hsv[..., 1] <= s_max)
    return cv2.cvtColor(np.where(mask, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def find_line(lines: list[TextLine], *wanted: str) -> TextLine | None:
    """The first line containing any of ``wanted`` (compared with simplify())."""
    keys = [simplify(w) for w in wanted]
    for line in lines:
        s = simplify(line.text)
        if any(k and k in s for k in keys):
            return line
    return None
