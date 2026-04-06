from collections import deque
from typing import Dict, Optional
from server.models import MetricFrame, BufferSummary


class RollingBuffer:
    def __init__(self, maxlen: int = 90):
        self.maxlen = maxlen
        self._data: deque = deque(maxlen=maxlen)

    def add(self, frame: MetricFrame):
        self._data.append(frame)

    def add_batch(self, frames: list[MetricFrame]):
        for f in frames:
            self._data.append(f)

    def summarize(self, session_id: str) -> BufferSummary:
        frames = list(self._data)
        n = len(frames)
        if n == 0:
            return BufferSummary(
                session_id=session_id,
                frame_count=0,
                duration_seconds=0.0,
                avg_ear=None,
                avg_mar=None,
                avg_yaw=None,
                avg_pitch=None,
                drowsy_frames=0,
                yawn_frames=0,
                distracted_frames=0,
            )

        duration = (frames[-1].timestamp - frames[0].timestamp) / 1000.0

        avg_ear = sum(f.ear for f in frames) / n
        avg_mar = sum(f.mar for f in frames) / n
        avg_yaw = sum(f.yaw for f in frames) / n
        avg_pitch = sum(f.pitch for f in frames) / n

        drowsy = sum(1 for f in frames if f.ear < 0.25)
        yawn = sum(1 for f in frames if f.mar > 0.6)
        distracted = sum(1 for f in frames if abs(f.yaw) > 20 or abs(f.pitch) > 20)

        return BufferSummary(
            session_id=session_id,
            frame_count=n,
            duration_seconds=round(duration, 2),
            avg_ear=round(avg_ear, 4),
            avg_mar=round(avg_mar, 4),
            avg_yaw=round(avg_yaw, 2),
            avg_pitch=round(avg_pitch, 2),
            drowsy_frames=drowsy,
            yawn_frames=yawn,
            distracted_frames=distracted,
        )


class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, RollingBuffer] = {}

    def get_or_create(self, session_id: str) -> RollingBuffer:
        if session_id not in self._sessions:
            self._sessions[session_id] = RollingBuffer()
        return self._sessions[session_id]

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)

    def all_summaries(self) -> list[BufferSummary]:
        return [buf.summarize(sid) for sid, buf in self._sessions.items()]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
