from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    ear_left: float = Field(..., description="Left eye aspect ratio")
    ear_right: float = Field(..., description="Right eye aspect ratio")
    mar: float = Field(..., description="Mouth aspect ratio")
    yaw: float = Field(..., description="Head yaw (degrees)")
    pitch: float = Field(..., description="Head pitch (degrees)")
    roll: float = Field(..., description="Head roll (degrees)")
    timestamp: float = Field(..., description="Client time in ms (performance.now or epoch)")


Daypart = Literal["morning", "afternoon", "evening", "night"]


class DrivingContext(BaseModel):
    speed_mph: float = Field(..., ge=0, le=120)
    road_type: Literal["city", "suburban", "highway"]
    session_elapsed_sec: int = Field(..., ge=0)
    time_of_day: str = Field(..., description="Local time label e.g. 23:42")
    daypart: Daypart


class MetricBatch(BaseModel):
    type: Literal["metrics_batch"] = "metrics_batch"
    v: int = 1
    session_id: Optional[str] = None
    samples: list[MetricSample] = Field(default_factory=list)
    context: Optional[DrivingContext] = None


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


class AlertRecord(BaseModel):
    severity: str
    alert_text: str
    reasoning: Optional[str] = None
    timestamp: float = Field(..., description="Unix time seconds")


class AlertsResponse(BaseModel):
    session_id: str
    alerts: list[AlertRecord]
