from __future__ import annotations

from collections import deque

from server.models import BufferSummary, MetricSample


class RollingSignalBuffer:
    """In-memory rolling buffer of metric samples (default ~30s at 200ms batch cadence)."""

    def __init__(self, maxlen: int = 90) -> None:
        self._items: deque[MetricSample] = deque(maxlen=maxlen)

    def extend(self, samples: list[MetricSample]) -> None:
        for s in samples:
            self._items.append(s)

    def summary(self, session_id: str) -> BufferSummary:
        if not self._items:
            return BufferSummary(session_id=session_id, count=0)

        n = len(self._items)
        ear_l = sum(x.ear_left for x in self._items) / n
        ear_r = sum(x.ear_right for x in self._items) / n
        mar = sum(x.mar for x in self._items) / n
        yaw = sum(x.yaw for x in self._items) / n
        pitch = sum(x.pitch for x in self._items) / n
        roll = sum(x.roll for x in self._items) / n
        latest_ts = self._items[-1].timestamp

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
