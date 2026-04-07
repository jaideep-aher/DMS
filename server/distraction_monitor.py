"""Visual distraction heuristics: gaze region + head pose over a short server window."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Optional

from server.buffer import RollingSignalBuffer
from server.models import DrivingContext, MetricSample


class DistractionMonitor:
    """
    Flags sustained attention off the forward road scene using per-sample ``gaze_region``
    (from iris + head pose on the client) or head yaw/pitch fallback when gaze is unknown.

    Uses a separate cooldown from drowsiness alerts so both can fire independently.
    """

    COOLDOWN_SEC = 22.0
    WINDOW_SEC = 2.8
    MIN_SAMPLES = 6
    MIN_SPEED_MPH = 12.0
    OFF_FORWARD_FRACTION = 0.52

    def __init__(self) -> None:
        self._last_alert_at: dict[str, float] = {}

    def drop_session(self, session_id: str) -> None:
        self._last_alert_at.pop(session_id, None)

    def _head_only_region(self, s: MetricSample) -> GazeRegion:
        y, p = s.yaw, s.pitch
        if p > 11.0:
            return "down"
        if p < -9.0:
            return "up"
        if y < -13.0:
            return "left"
        if y > 13.0:
            return "right"
        if abs(y) > 9.0 or abs(p) > 7.0:
            return "away"
        return "forward"

    def _effective_region(self, s: MetricSample) -> str:
        g = (s.gaze_region or "").strip().lower()
        if g in ("forward", "left", "right", "down", "up", "away"):
            return g
        return self._head_only_region(s)

    def evaluate(
        self,
        session_id: str,
        buffer: RollingSignalBuffer,
        context: Optional[DrivingContext],
    ) -> Optional[dict[str, Any]]:
        now = time.time()
        last = self._last_alert_at.get(session_id, 0.0)
        if now - last < self.COOLDOWN_SEC:
            return None

        speed = float(context.speed_mph) if context else 0.0
        if speed < self.MIN_SPEED_MPH:
            return None

        recent = buffer.recent(self.WINDOW_SEC)
        if len(recent) < self.MIN_SAMPLES:
            return None

        samples: list[MetricSample] = [s for s, _ in recent]
        regions = [self._effective_region(s) for s in samples]
        off = sum(1 for r in regions if r != "forward")
        frac = off / len(regions)
        if frac < self.OFF_FORWARD_FRACTION:
            return None

        counts = Counter(regions)
        counts.pop("forward", None)
        if not counts:
            return None
        dominant, _n = counts.most_common(1)[0]

        sev = "mild"
        reasoning = "distraction_gaze"

        if dominant == "down" and frac >= 0.62:
            sev = "moderate"
            alert = (
                "Eyes appear directed down — keep your view on the road; "
                "avoid phone or console tasks while moving."
            )
        elif dominant in ("left", "right"):
            side = "left" if dominant == "left" else "right"
            alert = (
                f"Sustained gaze toward your {side} — check mirrors briefly, "
                "then return attention to the road ahead."
            )
            reasoning = "distraction_mirror_or_side"
        elif dominant == "away":
            alert = "Head and eyes off the forward path — re-center on the lane and traffic."
            reasoning = "distraction_away"
        elif dominant == "up":
            alert = "Head tilted up for a while — bring your focus back to the road scene."
            reasoning = "distraction_up"
        else:
            alert = "Attention seems off the forward road — eyes on the path ahead."
            reasoning = "distraction_generic"

        if context and context.road_type == "highway" and sev == "moderate":
            alert += " At highway speed, delay any secondary tasks until stopped."

        self._last_alert_at[session_id] = now
        return {"severity": sev, "alert_text": alert, "reasoning": reasoning, "category": "distraction"}
