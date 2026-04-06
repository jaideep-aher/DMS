from pydantic import BaseModel
from typing import List, Optional


class MetricFrame(BaseModel):
    timestamp: float
    ear: float          # Eye Aspect Ratio (average both eyes)
    ear_left: float
    ear_right: float
    mar: float          # Mouth Aspect Ratio
    pitch: float        # head pose degrees
    yaw: float
    roll: float


class MetricBatch(BaseModel):
    session_id: str
    frames: List[MetricFrame]


class BufferSummary(BaseModel):
    session_id: str
    frame_count: int
    duration_seconds: float
    avg_ear: Optional[float]
    avg_mar: Optional[float]
    avg_yaw: Optional[float]
    avg_pitch: Optional[float]
    drowsy_frames: int      # EAR < 0.25
    yawn_frames: int        # MAR > 0.6
    distracted_frames: int  # |yaw| > 20 or |pitch| > 20


class StatusResponse(BaseModel):
    active_sessions: int
    sessions: List[BufferSummary]
