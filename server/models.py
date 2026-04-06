from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    ear_left: float = Field(..., description="Left eye aspect ratio")
    ear_right: float = Field(..., description="Right eye aspect ratio")
    mar: float = Field(..., description="Mouth aspect ratio")
    yaw: float = Field(..., description="Head yaw (degrees)")
    pitch: float = Field(..., description="Head pitch (degrees)")
    roll: float = Field(..., description="Head roll (degrees)")
    timestamp: float = Field(..., description="Client time in ms (performance.now or epoch)")


class MetricBatch(BaseModel):
    session_id: Optional[str] = None
    samples: list[MetricSample] = Field(default_factory=list)


class BufferSummary(BaseModel):
    session_id: str
    count: int
    ear_left_avg: Optional[float] = None
    ear_right_avg: Optional[float] = None
    mar_avg: Optional[float] = None
    yaw_avg: Optional[float] = None
    pitch_avg: Optional[float] = None
    roll_avg: Optional[float] = None
    latest_timestamp: Optional[float] = None


class StatusResponse(BaseModel):
    sessions: list[BufferSummary]
