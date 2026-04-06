from __future__ import annotations

import time
from collections import deque

from server.models import BufferSummary, MetricSample


class RollingSignalBuffer:
    """In-memory rolling buffer of metric samples (default ~30s at 200ms batch cadence)."""

    def __init__(self, maxlen: int = 90) -> None:
        self._items: deque[tuple[MetricSample, float]] = deque(maxlen=maxlen)

    def extend(self, samples: list[MetricSample]) -> None:
        now = time.time()
        for s in samples:
            self._items.append((s, now))

    def recent(self, window_sec: float) -> list[tuple[MetricSample, float]]:
        """Samples received within the last ``window_sec`` seconds (server clock)."""
        cutoff = time.time() - window_sec
        return [(s, t) for s, t in self._items if t >= cutoff]

    def all_samples(self) -> list[MetricSample]:
        return [s for s, _ in self._items]

    def summary(self, session_id: str) -> BufferSummary:
        if not self._items:
            return BufferSummary(session_id=session_id, count=0)

        samples = self.all_samples()
        n = len(samples)
        ear_l = sum(x.ear_left for x in samples) / n
        ear_r = sum(x.ear_right for x in samples) / n
        mar = sum(x.mar for x in samples) / n
        yaw = sum(x.yaw for x in samples) / n
        pitch = sum(x.pitch for x in samples) / n
        roll = sum(x.roll for x in samples) / n
        latest_ts = samples[-1].timestamp

        return BufferSummary(
            session_id=session_id,
            count=n,
            ear_left_avg=ear_l,
            ear_right_avg=ear_r,
            mar_avg=mar,
            yaw_avg=yaw,
            pitch_avg=pitch,
            roll_avg=roll,
            latest_timestamp=latest_ts,
        )
