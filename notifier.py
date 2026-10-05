"""
Discord webhook notifications, so you can check on the bot while you're away.

Sends a message for each catch (with a close-up of the item), when the bot
starts / pauses / stops, a status update every N minutes, and alerts when
something looks wrong: nothing hooked for a while, Roblox not focused (crashed
or disconnected?), many casts without a bite, or an error.

Everything is sent from a background thread, so a slow or broken network can
never hold up the minigame. Only Python's standard library is used.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import cv2
import numpy as np

from config import VERSION

log = logging.getLogger(__name__)

WEBHOOK_PREFIXES = tuple(f"https://{host}/api/webhooks/" for host in
                         ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"))
REPO_URL = "https://github.com/telmuad/slayers2-fisher"
GREEN, BLUE, ORANGE, RED, GREY = 0x4CD07D, 0x4AA3FF, 0xFF8A4C, 0xFF5C5C, 0x9AA4B2


def valid_webhook(url: str) -> bool:
    return url.startswith(WEBHOOK_PREFIXES) and len(url) > len("https://discord.com/api/webhooks/") + 10


@dataclass
class Message:
    title: str
    description: str = ""
    color: int = BLUE
    fields: list[tuple[str, str]] = field(default_factory=list)
    image: np.ndarray | None = None
    ping: bool = False          # mention the user (alerts only)


def to_jpeg(img: np.ndarray, max_width: int = 1280) -> bytes:
    if img.shape[1] > max_width:
        f = max_width / img.shape[1]
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes() if ok else b""


def post(url: str, msg: Message, username: str, ping_id: str = "", timeout: float = 15) -> None:
    """Send one message. Raises urllib.error.HTTPError / URLError on failure."""
    embed = {"title": msg.title, "color": msg.color,
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "footer": {"text": f"Slayers 2 Auto-Fisher {VERSION}"}}
    if msg.description:
        embed["description"] = msg.description
    if msg.fields:
        embed["fields"] = [{"name": n, "value": v, "inline": True} for n, v in msg.fields]
    payload = {"username": username or "Slayers 2 Fisher", "embeds": [embed],
               "allowed_mentions": {"users": [ping_id] if msg.ping and ping_id else []}}
    if msg.ping and ping_id:
        payload["content"] = f"<@{ping_id}>"
    jpeg = to_jpeg(msg.image) if msg.image is not None else b""
    headers = {"User-Agent": f"Slayers2Fisher/{VERSION} (+{REPO_URL})"}
    if jpeg:
        embed["image"] = {"url": "attachment://screenshot.jpg"}
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; "
                f"filename=\"screenshot.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() \
            + jpeg + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def duration(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


class Notifier:
    """
    The bot calls the event methods (cheap, never block); a background thread
    sends the messages and every few seconds checks for "looks stuck" alerts.
    """

    def __init__(self, cfg: dict, screenshot=None):
        self.n = cfg["notifications"]
        self.url = str(self.n["webhook_url"]).strip()
        self.enabled = valid_webhook(self.url)
        self.screenshot = screenshot      # () -> BGR image of the Roblox screen, or None
        self.bot = None                   # set by the bot: status + state for the alerts
        self._queue: queue.Queue[Message | None] = queue.Queue(maxsize=50)
        self._broken = False
        self._reset_session()
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
            self._thread.start()
        elif self.url:
            log.warning("Notifications are off: the webhook URL doesn't look like a Discord webhook")

    @staticmethod
    def configured(cfg: dict) -> bool:
        return valid_webhook(str(cfg["notifications"]["webhook_url"]).strip())

    def _reset_session(self):
        now = time.time()
        self.session_start = now
        self.last_progress = now          # last time a fish was hooked (or the bot started)
        self.next_summary = now + 60 * float(self.n["summary_every_min"])
        self.idle_alerted = self.focus_alerted = self.recast_alerted = False
        self.over = False                 # stopped: no more status updates or alerts

    # -- events (called from the bot thread / hotkey thread) ------------------------
    def started(self):
        self._reset_session()
        if self.n["on_start_stop"]:
            self._send(Message("Started", "Fishing.", GREEN, self._stat_fields()))

    def paused(self, reason: str):
        if self.n["on_start_stop"]:
            self._send(Message("Paused", f"Paused ({reason}).", ORANGE, self._stat_fields()))

    def stopped(self, reason: str):
        self.over = True
        if self.n["on_start_stop"]:
            self._send(Message("Stopped", f"The bot stopped ({reason}).", RED, self._stat_fields()))

    def hooked(self):
        self.last_progress = time.time()
        self.idle_alerted = self.recast_alerted = False

    def caught(self, picture: np.ndarray | None, in_zone: float | None):
        if not self.n["on_catch"]:
            return
        fields = self._stat_fields()
        if in_zone is not None:
            fields.insert(0, ("Box in the zone", f"{in_zone:.0f}%"))
        self._send(Message("Caught something!", "", GREEN, fields,
                           picture if self.n["catch_picture"] else None))

    def no_prompt(self, in_zone: float | None):
        if self.n["on_no_prompt"]:
            text = "No Collect prompt: it went straight to your inventory, or the fish escaped."
            fields = ([("Box in the zone", f"{in_zone:.0f}%")] if in_zone is not None else []) + self._stat_fields()
            self._send(Message("Minigame over", text, GREY, fields))

    def no_bite(self, in_a_row: int):
        limit = int(self.n["alert_recasts"])
        if limit and in_a_row >= limit and not self.recast_alerted:
            self.recast_alerted = True
            self._alert(f"{in_a_row} casts in a row without a bite. Is the cast landing on water, "
                        "and is your character still at the fishing spot?")

    def quest_done(self, count: int):
        self.hooked()                     # handing in counts as progress for the idle alert
        if self.n["on_quest"]:
            self._send(Message("Quest complete!", f"Quests handed in this session: {count}", GREEN,
                               self._stat_fields(quests=True)))

    def out_of_items(self, quest: str, missing: list[tuple[str, int, int]]):
        lines = "\n".join(f"- {name}: {have}/{need}" for name, have, need in missing)
        self._alert(f"Out of fish for {quest or 'the quest'}. Still needed:\n{lines}\n\n"
                    "The bot has paused. Catch more, then press start again.", quests=True)

    def quest_problem(self, text: str):
        self._alert(text, quests=True)

    def error(self, text: str):
        self._alert(f"The bot hit an error and paused:\n```{text[-900:]}```")

    def test(self) -> None:
        """Send a test message now (raises on failure). Used by Settings."""
        post(self.url, Message("Test message", "Notifications are working.", BLUE,
                               image=self._grab() if self.n["screenshots"] else None),
             self.n["username"], str(self.n["ping_user_id"]).strip())

    def close(self, timeout: float = 5.0):
        """Send what's still queued (up to ``timeout`` seconds), then stop."""
        if self._thread:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            self._thread.join(timeout)

    # -- internals --------------------------------------------------------------------
    def _alert(self, text: str, quests: bool = False):
        self._send(Message("Needs a look", text, RED, self._stat_fields(quests),
                           self._grab() if self.n["screenshots"] else None, ping=True))

    def _grab(self):
        try:
            return self.screenshot() if self.screenshot else None
        except Exception:
            return None

    def _stat_fields(self, quests: bool | None = None) -> list[tuple[str, str]]:
        if self.bot is None:
            return []
        s = self.bot.status.snapshot()
        if quests or (quests is None and getattr(self.bot, "cfg", {}).get("mode") == "quests"):
            return [("Quests done", str(s.quests)), ("Running for", duration(time.time() - self.session_start))]
        hours = max((time.time() - self.session_start) / 3600, 1e-6)
        rate = f"{s.minigames / hours:.0f}" if hours > 0.05 else "-"
        return [("Collected", str(s.catches)), ("Fish hooked", str(s.minigames)),
                ("Hooked per hour", rate), ("Running for", duration(time.time() - self.session_start))]

    def _send(self, msg: Message):
        if not self.enabled or self._broken:
            return
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            log.warning("Notification queue full - dropping '%s'", msg.title)

    def _run(self):
        while True:
            try:
                msg = self._queue.get(timeout=2.0)
            except queue.Empty:
                msg = ""
            if msg is None:
                # Closing: flush the rest, then stop.
                while not self._queue.empty():
                    rest = self._queue.get_nowait()
                    if rest is not None:
                        self._deliver(rest)
                return
            if msg:
                self._deliver(msg)
            try:
                self._watch()
            except Exception:
                log.exception("Notification check failed")

    def _deliver(self, msg: Message):
        for attempt in range(3):
            try:
                post(self.url, msg, self.n["username"], str(self.n["ping_user_id"]).strip())
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:            # rate limited: wait as long as Discord asks
                    try:
                        wait = float(json.loads(e.read() or b"{}").get("retry_after", 2))
                    except (ValueError, AttributeError):
                        wait = 2.0
                    time.sleep(min(wait, 30) + 0.2)
                    continue
                if e.code in (401, 403, 404):
                    self._broken = True
                    log.warning("Discord rejected the webhook (HTTP %d) - notifications are off "
                                "until the URL is fixed in Settings", e.code)
                    return
                log.warning("Notification failed (HTTP %d)", e.code)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log.warning("Notification failed (%s)", getattr(e, "reason", e))
            time.sleep(2 * (attempt + 1))

    def _watch(self):
        """Periodic checks: status updates and "looks stuck" alerts."""
        bot = self.bot
        if bot is None or self.over or not bot.running.is_set():
            return
        now = time.time()
        every = 60 * float(self.n["summary_every_min"])
        if every and now >= self.next_summary:
            self.next_summary = now + every
            s = bot.status.snapshot()
            self._send(Message("Status", f"{s.state}: {s.detail}" if s.detail else s.state, BLUE,
                               self._stat_fields(), self._grab() if self.n["screenshots"] else None))
        unfocused = bot.unfocused_since
        focus_limit = 60 * float(self.n["alert_unfocused_min"])
        if unfocused is None:
            self.focus_alerted = False
        elif focus_limit and now - unfocused >= focus_limit and not self.focus_alerted:
            self.focus_alerted = True
            self._alert(f"Roblox hasn't been the focused window for {duration(now - unfocused)}, "
                        "so the bot is waiting. Did Roblox crash or disconnect, or did another "
                        "window take focus?")
        idle_limit = 60 * float(self.n["alert_idle_min"])
        if (idle_limit and unfocused is None and now - self.last_progress >= idle_limit
                and not self.idle_alerted):
            self.idle_alerted = True
            self._alert(f"Nothing hooked for {duration(now - self.last_progress)} while running. "
                        "Check the screenshot: disconnected, moved, or a menu in the way?")
