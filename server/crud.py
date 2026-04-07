"""Async CRUD for trips, alerts, and usage / global budget."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from server.sql_models import AlertRow, GlobalBudget, Trip, UsageLedger

logger = logging.getLogger(__name__)

# Serialize all GlobalBudget row updates (activity + OpenAI USD) across workers' processes
# this process only; multi-replica Railway needs Redis or DB row locks for strict correctness.
_global_budget_row_lock = asyncio.Lock()


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


async def _ensure_global_budget(session: AsyncSession) -> GlobalBudget:
    row = await session.get(GlobalBudget, 1)
    if row is None:
        now = datetime.now(timezone.utc)
        row = GlobalBudget(
            id=1,
            activity_lifetime=0,
            activity_day_utc=None,
            activity_daily=0,
            openai_usd_lifetime=0.0,
            openai_day_utc=None,
            openai_usd_daily=0.0,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
    return row


def _openai_price_per_million() -> tuple[float, float]:
    inp = float(os.environ.get("OPENAI_PRICE_INPUT_PER_MILLION", "0.15"))
    out = float(os.environ.get("OPENAI_PRICE_OUTPUT_PER_MILLION", "0.60"))
    return inp, out


def _openai_budget_caps() -> tuple[float, float]:
    life = float(os.environ.get("OPENAI_BUDGET_USD_LIFETIME", "50"))
    daily = float(os.environ.get("OPENAI_BUDGET_USD_DAILY", "10"))
    return life, daily


def _usd_from_usage(usage: Any) -> float:
    if usage is None:
        return 0.0
    pt = int(getattr(usage, "prompt_tokens", None) or 0)
    ct = int(getattr(usage, "completion_tokens", None) or 0)
    pin, pout = _openai_price_per_million()
    return (pt / 1_000_000.0) * pin + (ct / 1_000_000.0) * pout


async def openai_may_call_llm() -> bool:
    """
    True if another Chat Completions call is allowed under global USD caps.
    Uses token-pricing env defaults (gpt-4o-mini–class); actual spend is recorded after the call.
    """
    async with _global_budget_row_lock:
        from server.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            g = await _ensure_global_budget(session)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            life_cap, daily_cap = _openai_budget_caps()

            if float(g.openai_usd_lifetime) >= life_cap:
                logger.info("OpenAI lifetime budget reached (%.4f / %.2f USD)", g.openai_usd_lifetime, life_cap)
                return False
            daily_spent = float(g.openai_usd_daily) if g.openai_day_utc == today else 0.0
            if daily_spent >= daily_cap:
                logger.info("OpenAI daily budget reached (%.4f / %.2f USD)", daily_spent, daily_cap)
                return False

            return True


async def openai_record_usage(usage: Any) -> None:
    """Add actual token cost from a completion response to global OpenAI USD counters."""
    cost = _usd_from_usage(usage)
    if cost <= 0:
        return
    async with _global_budget_row_lock:
        from server.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            g = await _ensure_global_budget(session)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            now = datetime.now(timezone.utc)

            if g.openai_day_utc != today:
                g.openai_day_utc = today
                g.openai_usd_daily = 0.0

            g.openai_usd_lifetime = float(g.openai_usd_lifetime) + cost
            g.openai_usd_daily = float(g.openai_usd_daily) + cost
            g.updated_at = now
            await session.commit()
            logger.info(
                "OpenAI usage recorded: +$%.6f (lifetime $%.4f)",
                cost,
                g.openai_usd_lifetime,
            )


async def check_increment_usage(
    session: AsyncSession,
    fingerprint: str,
    daily_max: int,
    lifetime_max: int,
    *,
    global_daily_max: int = 0,
    global_lifetime_max: int = 0,
) -> tuple[bool, str]:
    """
    Increment usage by 1 if under per-IP and optional global activity caps (UTC day).
    Returns (allowed, "") or (False, reason) where reason is
    daily|lifetime|global_daily|global_lifetime.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    async with _global_budget_row_lock:
        g = await _ensure_global_budget(session)

        if g.activity_day_utc != today:
            g.activity_day_utc = today
            g.activity_daily = 0

        if global_daily_max > 0 and int(g.activity_daily) >= global_daily_max:
            return False, "global_daily"
        if global_lifetime_max > 0 and int(g.activity_lifetime) >= global_lifetime_max:
            return False, "global_lifetime"

        row = await session.get(UsageLedger, fingerprint)
        if row is None:
            if 1 > lifetime_max:
                return False, "lifetime"
            if 1 > daily_max:
                return False, "daily"
            session.add(
                UsageLedger(
                    fingerprint=fingerprint,
                    lifetime_total=1,
                    day_utc=today,
                    day_total=1,
                    updated_at=now,
                )
            )
            g.activity_lifetime = int(g.activity_lifetime) + 1
            g.activity_daily = int(g.activity_daily) + 1
            g.updated_at = now
            await session.commit()
            return True, ""

        if row.day_utc != today:
            row.day_utc = today
            row.day_total = 0

        if row.lifetime_total >= lifetime_max:
            return False, "lifetime"
        if row.day_total >= daily_max:
            return False, "daily"

        row.lifetime_total = int(row.lifetime_total) + 1
        row.day_total = int(row.day_total) + 1
        row.updated_at = now
        g.activity_lifetime = int(g.activity_lifetime) + 1
        g.activity_daily = int(g.activity_daily) + 1
        g.updated_at = now
        await session.commit()
        return True, ""
