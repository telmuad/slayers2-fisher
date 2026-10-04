"""
Minigame controller: decides each frame whether to hold the left mouse button.

Physics we assume: holding pushes the white box up, releasing lets it fall.
A plain "below target -> hold, above -> release" rule overshoots, because the
box keeps moving after you change the input. So instead:

  1. Measure the box and zone positions as a fraction of the bar's height
     (0 = bottom, 1 = top) and estimate how fast each is moving.
  2. Predict where the box will end up: the further of
       - where it will be ``prediction_s`` seconds from now (reaction time), and
       - where it would come to a stop: braking * speed * |speed|
         (twice the speed needs four times the room to stop).
     The braking coefficient is *learned while playing*: every time we act
     against the box's motion at speed, we measure how far it actually
     travels and average that in. This is the "D" of a PD controller.
  3. error = predicted target - predicted box. Errors inside the dead zone
     count as zero.
  4. Turn the error into a duty cycle: hover_duty + gain * error, clamped to
     0..1. 1 = hold constantly, 0 = release, 0.5 = hold half the time.
  5. Feather the button with that duty cycle (PWM) over short periods,
     like a player tapping to hover.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

MIN_LEARN_SPEED = 0.3   # only learn braking from moves faster than this (bar heights/s)
LEARN_RATE = 0.35       # how much each measurement moves the learned braking value
MAX_BRAKING = 0.5


@dataclass
class ControlState:
    """Snapshot of the controller's last decision (for the UI / debug images)."""
    box_pos: float | None = None
    target_pos: float | None = None
    box_vel: float = 0.0
    error: float = 0.0
    duty: float = 0.0
    hold: bool = False
    braking: float = 0.0


class _Tracker:
    """Position + smoothed velocity of one thing on the bar."""

    def __init__(self, smoothing: float):
        self.smoothing = smoothing
        self.pos: float | None = None
        self.vel = 0.0
        self.t = 0.0

    def update(self, pos: float, t: float) -> None:
        if self.pos is not None and t > self.t:
            raw = (pos - self.pos) / (t - self.t)
            a = self.smoothing
            self.vel = a * self.vel + (1 - a) * raw
        self.pos, self.t = pos, t

    def predict(self, t: float, ahead: float) -> float | None:
        if self.pos is None:
            return None
        return self.pos + self.vel * ((t - self.t) + ahead)


class MinigameController:
    def __init__(self, cfg: dict):
        self.c = cfg["controller"]
        # Learned stopping distance per speed^2. Kept between minigames.
        self.braking = float(self.c["braking"])
        self.reset()

    def reset(self) -> None:
        smoothing = self.c["velocity_smoothing"]
        self.box = _Tracker(smoothing)
        self.zone = _Tracker(smoothing)
        self.state = ControlState(braking=self.braking)
        self._pwm_start = None
        self._last_hold = False
        self._brake_event = None     # (direction, start pos, start speed) while braking

    # -- prediction -----------------------------------------------------------
    def _predict_box(self, t: float) -> float | None:
        b = self.box
        if b.pos is None:
            return None
        v = b.vel
        reaction = v * ((t - b.t) + self.c["prediction_s"])
        stopping = self.braking * v * abs(v)
        # Slow moves are dominated by reaction time, fast ones by stopping distance.
        return b.pos + (reaction if abs(reaction) >= abs(stopping) else stopping)

    def _learn_braking(self, hold: bool) -> None:
        """
        When we act against the box's motion while it moves fast (release
        while it rises, hold while it falls), watch how far it goes while its
        speed drops. distance / (v_start^2 - v_now^2) is the braking value.
        """
        if not self.c["auto_braking"]:
            return
        v, p = self.box.vel, self.box.pos
        if self._brake_event is None:
            if hold != self._last_hold:
                if not hold and v > MIN_LEARN_SPEED:
                    self._brake_event = (1, p, v)
                elif hold and v < -MIN_LEARN_SPEED:
                    self._brake_event = (-1, p, -v)
            return
        direction, p0, v0 = self._brake_event
        speed = v * direction                       # > 0 while still moving the same way
        still_braking = hold == (direction < 0)
        if still_braking and speed > 0:
            return
        # Braking ended (stopped, or we switched input): measure if speed dropped enough.
        self._brake_event = None
        dropped = v0 * v0 - max(0.0, speed) ** 2
        if dropped >= 0.5 * v0 * v0:
            k = (p - p0) * direction / dropped
            if 0.0 <= k <= MAX_BRAKING:
                self.braking += LEARN_RATE * (k - self.braking)

    # -- main entry -------------------------------------------------------------
    def update(self, box_pos: float | None, zone_pos: float | None, t: float) -> bool:
        """
        Feed this frame's measurements (either may be None if not detected)
        and get back True = hold left click, False = release.
        """
        c = self.c
        if box_pos is not None:
            self.box.update(box_pos, t)
        elif self.box.pos is not None and t - self.box.t > c["box_lost_hold_s"]:
            # Box lost for too long: stop guessing, let go.
            self.state.hold = self._last_hold = False
            self._brake_event = None
            return False
        if zone_pos is not None:
            self.zone.update(zone_pos, t)

        box = self._predict_box(t)
        target = self.zone.predict(t, c["prediction_s"])
        if box is None or target is None:
            # Nothing to aim at yet. Holding is the safe default at the start,
            # since the box begins at the very bottom.
            hold = box is not None and box < 0.5
            self.state = ControlState(box_pos=self.box.pos, hold=hold, braking=self.braking)
            self._last_hold = hold
            return hold

        error = target + c["target_offset"] - box
        dz = c["dead_zone"]
        effective = 0.0 if abs(error) <= dz else error - dz * (1 if error > 0 else -1)
        duty = min(1.0, max(0.0, c["hover_duty"] + c["gain"] * effective))

        # Pulse-width modulation: hold for the first `duty` share of each period.
        if self._pwm_start is None:
            self._pwm_start = t
        period = max(0.02, c["pwm_period_s"])
        phase = ((t - self._pwm_start) % period) / period
        hold = duty >= 1.0 or (duty > 0.0 and phase < duty)

        self._learn_braking(hold)
        self._last_hold = hold
        self.state = ControlState(box_pos=self.box.pos, target_pos=self.zone.pos,
                                  box_vel=self.box.vel, error=error, duty=duty, hold=hold,
                                  braking=self.braking)
        return hold
