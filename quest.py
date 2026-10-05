"""
Quest mode: keeps doing Angler Runo's crate quest with the fish you have.

The loop, as the game plays it:
  1. Hold T on "Angler Runo / Chat". Click through his lines until the quest
     choice shows: "Ill fill your crates(Lv 45)" right away, or for Lv 60,
     "Anything bigger?" first, then "Ill land the good catch(Lv 60)".
  2. The quest list appears on the left, e.g. "The Good Catch 0/7" with one
     line per fish ("Coral crated 0/3") and "Return to Runo 0/1".
  3. Hold T on "Fish Crate / Load": the fish you have go into the crate.
     If some are still missing afterwards, you're out of fish: send an alert
     and pause.
  4. Talk to him again, click "The crate is loaded", click through his lines.
  5. Wait out the quest cooldown (10 s) and start over.

Everything is found by reading the screen with Windows' text recognition
(see ocr.py), so it needs no calibration images. T is only pressed when the
prompt on screen says "Chat" under the NPC's name or "Load" under the crate's.
The character never moves: stand between Angler Runo and his crate.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ocr import Ocr, TextLine, simplify, white_text
from window import primary_monitor_rect

log = logging.getLogger(__name__)

CRATED = re.compile(r"(.+?)\s*crated\s*(\d+)\s*/\s*(\d+)", re.I)
LEVEL = re.compile(r"\(?\s*lv\.?\s*(\d+)\s*\)?", re.I)
PROMPT_GRACE_S = 30     # prompts vanish for a few seconds after accepting / loading; only then complain


@dataclass
class Dialogue:
    open: bool
    body: list[TextLine] = field(default_factory=list)
    options: list[TextLine] = field(default_factory=list)

    def key(self) -> tuple:
        return (self.open, tuple(simplify(l.text) for l in self.body),
                tuple(simplify(l.text) for l in self.options))

    def option(self, *words: str) -> TextLine | None:
        for line in self.options:
            s = simplify(line.text)
            if all(simplify(w) in s for w in words):
                return line
        return None


@dataclass
class Tracker:
    active: bool                     # a crate quest is in the quest list
    title: str = ""
    missing: list[tuple[str, int, int]] = field(default_factory=list)   # (fish, have, need)

    def key(self) -> tuple:
        return self.active, tuple(self.missing)


def t_circles(img: np.ndarray, screen_h: int) -> list[tuple[int, int, int, int]]:
    """
    Boxes of the white "T" key circles of interaction prompts: white, round,
    with the dark letter inside (the chat-bubble icon next to it is solid white).
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] > 215) & (hsv[..., 1] < 40)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (0.010 * screen_h <= h <= 0.06 * screen_h and 0.8 <= w / h <= 1.25):
            continue
        perimeter = cv2.arcLength(c, True)
        roundness = 4 * np.pi * cv2.contourArea(c) / (perimeter * perimeter) if perimeter else 0
        inner = cv2.cvtColor(img[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4], cv2.COLOR_BGR2GRAY)
        if roundness > 0.75 and (inner < 120).mean() > 0.08:
            found.append((x, y, w, h))
    return found


def _short(missing) -> str:
    return ", ".join(f"{name} {have}/{need}" for name, have, need in missing)


def _counts(missing) -> list[tuple[str, int, int]]:
    """Compare quest lists by fish and numbers, ignoring OCR slips in spacing/punctuation."""
    return sorted((simplify(n), have, need) for n, have, need in missing)


class QuestRunner:
    def __init__(self, bot):
        self.bot = bot
        self.q = bot.cfg["quests"]
        # The screen Roblox is on: the calibrated one, else the main screen
        # (quest mode works without the fishing calibration).
        self.mon = tuple(bot.cfg.get("monitor") or primary_monitor_rect())
        self._ocr: Ocr | None = None
        self.intent = "accept"          # what the current conversation is for: accept / turn_in
        self.cooldown_until = 0.0
        self.clicks = 0                 # clicks in the current conversation
        self.problem_sent: str | None = None
        self.turned_in = False          # clicked "The crate is loaded" in this conversation
        self.accepted = False           # clicked the quest choice in this conversation
        self.prompt_missing_since: float | None = None

    @property
    def ocr(self) -> Ocr:
        if self._ocr is None:
            self._ocr = Ocr()
        return self._ocr

    # -- reading the screen ---------------------------------------------------------
    def _grab(self, fx0, fy0, fx1, fy1):
        left, top, w, h = self.mon
        x0, y0 = left + int(w * fx0), top + int(h * fy0)
        return self.bot.capture.grab([x0, y0, int(w * (fx1 - fx0)), int(h * (fy1 - fy0))]), x0, y0

    def _lines(self, region, scale=1.0, white=False) -> list[TextLine]:
        img, x0, y0 = self._grab(*region)
        lines = self.ocr.read(white_text(img) if white else img, scale)
        for l in lines:                 # to screen coordinates
            l.x += x0
            l.y += y0
        return lines

    def read_dialogue(self) -> Dialogue:
        left, top, w, h = self.mon
        lines = self._lines((0.2, 0.66, 0.92, 1.0))
        npc = simplify(self.q["npc_name"])
        header = [l for l in lines if npc in simplify(l.text) and l.h >= 0.018 * h]
        if not header:
            return Dialogue(False)
        hy = header[0].y
        below = [l for l in lines if l.y > hy and l is not header[0] and len(simplify(l.text)) >= 2]
        options = [l for l in lines if l.center[0] > left + 0.6 * w and l is not header[0]
                   and len(simplify(l.text)) >= 3]
        body = [l for l in below if l not in options]
        return Dialogue(True, body, options)

    def read_tracker(self) -> Tracker:
        lines = self._lines((0.0, 0.25, 0.2, 0.85), scale=2.0, white=True)
        texts = [l.text for l in lines]
        active = any("returnto" in simplify(t) or "crated" in simplify(t) for t in texts)
        missing = []
        title = ""
        for t in texts:
            m = CRATED.search(t)
            if m:
                have, need = int(m.group(2)), int(m.group(3))
                if have < need:
                    name = re.sub(r"^[^A-Za-z0-9]+", "", m.group(1)).strip()
                    missing.append((name, have, need))
            elif re.search(r"\d+\s*/\s*\d+\s*$", t) and "return" not in t.lower() and not title:
                title = re.sub(r"\s*\d+\s*/\s*\d+\s*$", "", t).strip()
        return Tracker(active, title, missing)

    def read_prompt(self) -> str | None:
        """
        Which T prompt is showing: "chat" (the NPC), "load" (the crate) or None.
        Text recognition over a big patch of game world is unreliable, so find
        the white T circle first, then read only the label next to it.
        """
        img, _, _ = self._grab(0.2, 0.1, 0.8, 0.9)
        npc, crate = simplify(self.q["npc_name"]), simplify(self.q["crate_name"])
        for x, y, w, h in t_circles(img, self.mon[3]):
            label = img[max(0, y - h // 2): y + h + h // 2, x + w: x + w + 10 * w]
            for variant in (label, white_text(label, 150, 60)):
                text = "".join(simplify(l.text) for l in self.ocr.read(variant, 2.0))
                if npc in text and "chat" in text:
                    return "chat"
                if crate in text and "load" in text:
                    return "load"
        return None

    def _stable(self, read, tries: int = 4, gap: float = 0.3):
        """Read twice in a row with the same result (text can still be fading or typing in)."""
        last = read()
        for _ in range(tries):
            self.bot._sleep(gap)
            now = read()
            if now.key() == last.key():
                return now
            last = now
        return last

    # -- actions ----------------------------------------------------------------------
    def _click(self, line: TextLine):
        self.bot._guard()
        self.bot.inp.move_to(*line.center)
        self.bot._sleep(0.08)
        self.bot._guard()
        self.bot.inp.click(0.06)
        self.clicks += 1
        self.bot._sleep(0.9)

    def _press_t(self, seconds: float):
        self.bot._guard()
        self.bot.inp.key_down("t")
        try:
            self.bot._sleep(seconds)
        finally:
            self.bot.inp.key_up("t")

    def _no_prompt(self, text: str):
        """The prompt we need isn't showing. Normal for a few seconds; a problem after that."""
        now = time.time()
        if self.prompt_missing_since is None:
            self.prompt_missing_since = now
        if now - self.prompt_missing_since >= PROMPT_GRACE_S:
            self._problem(text)
        else:
            self.bot.status.set("Quest", "Waiting for the prompt to show")
        self.bot._sleep(1.0)

    def _problem(self, text: str):
        """Tell the user once (log + Discord alert) until things change."""
        self.bot.status.set("Quest", text)
        if self.problem_sent != text:
            self.problem_sent = text
            log.warning("Quest: %s", text)
            self.bot.notify.quest_problem(text)

    # -- the loop -----------------------------------------------------------------------
    def step(self) -> None:
        """One action. The bot calls this over and over while quest mode runs."""
        d = self._stable(self.read_dialogue)
        if d.open:
            self._dialogue(d)
            return
        if self.clicks:                  # a conversation just ended
            self._conversation_over()
        if time.time() < self.cooldown_until:
            left = self.cooldown_until - time.time()
            self.bot.status.set("Quest", f"Cooldown, {left:.0f} s")
            self.bot._sleep(min(left, 1.0))
            return
        t = self._stable(self.read_tracker)
        if not t.active:
            self._talk("accept")
        elif t.missing:
            self._load(t)
        else:
            self._talk("turn_in")

    def _talk(self, intent: str):
        what = "start the quest" if intent == "accept" else "hand in the crate"
        prompt = self.read_prompt()
        if prompt == "load" and intent == "accept":
            # The crate takes fish, so a quest is running after all: the quest
            # list was just misread. Look again rather than raise an alarm.
            self.bot._sleep(1.0)
            return
        if prompt != "chat":
            self._no_prompt(f"Can't see the '{self.q['npc_name']} / Chat' prompt to {what}. "
                            "Stand next to him (and his crate), with nothing in the way.")
            return
        self.problem_sent, self.prompt_missing_since = None, None
        self.intent, self.clicks = intent, 0
        self.bot.status.set("Quest", f"Talking to {self.q['npc_name']} to {what}")
        self._press_t(0.3)
        self.bot._sleep(1.0)

    def _load(self, t: Tracker):
        if self.read_prompt() != "load":
            self._no_prompt(f"Can't see the '{self.q['crate_name']} / Load' prompt. Stand next to "
                            "the crate, with nothing in the way.")
            return
        self.problem_sent, self.prompt_missing_since = None, None
        self.bot.status.set("Quest", "Loading the crate")
        self._press_t(float(self.q["load_hold_s"]))
        self.bot._sleep(1.2)
        after = self._stable(self.read_tracker)
        if after.active and after.missing and _counts(after.missing) == _counts(t.missing):
            self.bot.notify.out_of_items(after.title or t.title, after.missing)
            log.info("Out of fish for the quest: %s", after.missing)
            self.bot.status.set("Paused", f"Out of fish for the quest ({_short(after.missing)} missing). "
                                          "Catch more, then press start.")
            self.bot.pause("out of fish", notify=False)     # the alert above already says so
        elif after.active and not after.missing:
            log.info("Crate loaded")

    def _dialogue(self, d: Dialogue):
        self.bot.status.set("Quest", "In dialogue")
        if self.clicks > int(self.q["max_dialogue_clicks"]):
            close = d.option("close")
            self._problem("The conversation went on longer than expected; closing it.")
            if close:
                self._click(close)
            return
        loaded = d.option("crate", "loaded")
        if loaded:
            self.intent = "turn_in"
            self._click(loaded)
            self.turned_in = True
            return
        if self.intent == "accept" and d.options:
            want = d.option(f"lv{int(self.q['level'])}")
            if want:
                log.info("Quest: accepting '%s'", want.text)
                self.accepted = True
                self._click(want)
                return
            levels = [int(m.group(1)) for l in d.options for m in [LEVEL.search(l.text)] if m]
            bigger = d.option("bigger")
            if bigger and (not levels or max(levels) < int(self.q["level"])):
                self._click(bigger)
                return
        if d.options:
            if d.body and not d.option("close"):
                self._click(d.body[0])
                return
            close = d.option("close")
            if close:
                if self.intent == "accept":
                    self._problem(f"No 'Lv {self.q['level']}' quest in {self.q['npc_name']}'s choices "
                                  "(still on cooldown, or your level is too low?). Trying again soon.")
                    self.cooldown_until = time.time() + 15
                self._click(close)
            return
        if d.body:
            self._click(d.body[0])       # just talking: click the text to go on
        else:
            self.bot._sleep(0.3)

    def _conversation_over(self):
        if self.turned_in:
            self.turned_in = False
            self.bot.status.add("quests")
            self.cooldown_until = time.time() + float(self.q["cooldown_s"])
            n = self.bot.status.snapshot().quests
            log.info("Quest complete (%d this session)", n)
            self.bot.notify.quest_done(n)
        if self.accepted:
            self.accepted = False
            log.info("Quest accepted")
        self.clicks = 0
        self.intent = "accept"
