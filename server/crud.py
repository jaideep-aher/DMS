"""Async CRUD for trips and alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from server.sql_models import AlertRow, Trip


async def create_trip(session: AsyncSession, trip_id: str) -> Trip:
    t = Trip(id=trip_id, started_at=datetime.now(timezone.utc), alert_count=0)
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


async def finalize_trip(
    session: AsyncSession,
    trip_id: str,
    *,
    distance_miles: Optional[float],
    route_json: Optional[str],
) -> None:
    await session.execute(
        update(Trip)
        .where(Trip.id == trip_id)
        .values(
            ended_at=datetime.now(timezone.utc),
            distance_miles=distance_miles,
            route_json=route_json,
        )
    )
    await session.commit()


async def add_alert_for_trip(
    session: AsyncSession,
    trip_id: str,
    severity: str,
    alert_text: str,
    reasoning: Optional[str],
    created_at: datetime,
) -> AlertRow:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise ValueError(f"Unknown trip {trip_id}")
    row = AlertRow(
        trip_id=trip_id,
        severity=severity,
        alert_text=alert_text,
        reasoning=reasoning,
        created_at=created_at,
    )
    session.add(row)
    trip.alert_count = (trip.alert_count or 0) + 1
    await session.commit()
    await session.refresh(row)
    return row


async def list_trips(session: AsyncSession, *, limit: int = 50, offset: int = 0) -> Sequence[Trip]:
    result = await session.execute(
        select(Trip)
        .order_by(Trip.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def get_trip(session: AsyncSession, trip_id: str) -> Optional[Trip]:
    result = await session.execute(select(Trip).where(Trip.id == trip_id))
    return result.scalar_one_or_none()


async def list_alerts_for_trip(
    session: AsyncSession, trip_id: str, *, limit: int = 2000
) -> Sequence[AlertRow]:
    result = await session.execute(
        select(AlertRow)
        .where(AlertRow.trip_id == trip_id)
        .order_by(AlertRow.created_at.asc())
        .limit(limit)
    )
    return result.scalars().all()


def route_points_to_json(points: list[dict[str, Any]]) -> str:
    return json.dumps(points, separators=(",", ":"))
