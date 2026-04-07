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
    gaze_yaw_norm: Optional[float] = Field(
        None,
        description="Horizontal eye direction ~[-1,1] from iris vs eye corners (0=center)",
    )
    gaze_pitch_norm: Optional[float] = Field(
        None,
        description="Vertical eye direction ~[-1,1] from iris vs eyelids (0=center)",
    )
    gaze_region: Optional[str] = Field(
        None,
        description="Coarse attention zone: forward, left, right, down, up, away, unknown",
    )


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
    gaze_region_mode: Optional[str] = Field(
        None, description="Most common gaze_region in buffer (when present)"
    )
    gaze_forward_frac: Optional[float] = Field(
        None, description="Fraction of samples tagged forward among those with gaze_region"
    )
    gaze_yaw_avg: Optional[float] = None
    gaze_pitch_avg: Optional[float] = None


class StatusResponse(BaseModel):
    sessions: list[BufferSummary]


class AlertRecord(BaseModel):
    severity: str
    alert_text: str
    reasoning: Optional[str] = None
    timestamp: float = Field(..., description="Unix time seconds")
    id: Optional[int] = Field(None, description="Database row id when persisted")


class AlertsResponse(BaseModel):
    session_id: str
    alerts: list[AlertRecord]


class TripOut(BaseModel):
    """Persisted trip (monitoring session)."""

    id: str
    started_at: str
    ended_at: Optional[str] = None
    distance_miles: Optional[float] = None
    route_json: Optional[str] = None
    alert_count: int = 0


class TripsListResponse(BaseModel):
    trips: list[TripOut]
    count: int
