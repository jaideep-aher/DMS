"""SQLAlchemy ORM: trips (sessions) and alert log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.database import Base

if TYPE_CHECKING:
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Trip(Base):
    """
    One monitoring session (maps 1:1 to former WebSocket ``session_id`` / client ``trip_id``).
    """

    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    distance_miles: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    route_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    alerts: Mapped[List["AlertRow"]] = relationship(
        "AlertRow", back_populates="trip", cascade="all, delete-orphan"
    )


class AlertRow(Base):
    """Persistent alert event for a trip."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_text: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="alerts")
