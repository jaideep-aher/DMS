from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server.alert_engine import AlertEngine
from server.alert_manager import AlertManager
from server.buffer import RollingSignalBuffer
from server.distraction_monitor import DistractionMonitor
from server import crud
from server.database import AsyncSessionLocal, init_db
from server.models import (
    AlertRecord,
    AlertsResponse,
    DrivingContext,
    MetricBatch,
    StatusResponse,
    TripOut,
    TripsListResponse,
)
from server.rate_limit import enforce_rate_limit, enforce_websocket_batch

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger(__name__)

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

# Active WebSocket trips: trip_id -> rolling metric buffer
_sessions: dict[str, RollingSignalBuffer] = {}
# Derived odometer + route samples from driving context batches
_trip_progress: dict[str, dict[str, Any]] = {}

alert_engine = AlertEngine()
alert_manager = AlertManager()
distraction_monitor = DistractionMonitor()


def _accumulate_progress(trip_id: str, ctx: DrivingContext) -> None:
    st = _trip_progress.setdefault(
        trip_id,
        {"last_elapsed": 0.0, "miles": 0.0, "route": []},
    )
    elapsed = float(ctx.session_elapsed_sec)
    dt = max(0.0, elapsed - st["last_elapsed"])
    if dt > 0:
        st["miles"] += float(ctx.speed_mph) * (dt / 3600.0)
    st["last_elapsed"] = max(st["last_elapsed"], elapsed)
    r = st["route"]
    if len(r) < 500:
        r.append(
            {
                "t": ctx.session_elapsed_sec,
                "mph": round(ctx.speed_mph, 1),
                "road": ctx.road_type,
            }
        )


def _trip_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import server.sql_models  # noqa: F401 — register ORM tables

    await init_db()
    yield
    from server.database import engine

    await engine.dispose()


app = FastAPI(title="Driver Monitoring System", version="0.7.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api"):
        await enforce_rate_limit(request)
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/trips", response_model=TripsListResponse)
async def api_trips(limit: int = 50, offset: int = 0) -> TripsListResponse:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    async with AsyncSessionLocal() as db:
        rows = await crud.list_trips(db, limit=limit, offset=offset)
    trips = [
        TripOut(
            id=t.id,
            started_at=_trip_iso(t.started_at) or "",
            ended_at=_trip_iso(t.ended_at),
            distance_miles=t.distance_miles,
            route_json=t.route_json,
            alert_count=t.alert_count or 0,
        )
        for t in rows
    ]
    return TripsListResponse(trips=trips, count=len(trips))


@app.get("/api/trips/{trip_id}", response_model=TripOut)
async def api_trip_detail(trip_id: str) -> TripOut:
    async with AsyncSessionLocal() as db:
        t = await crud.get_trip(db, trip_id)
    if t is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Trip not found")
    return TripOut(
        id=t.id,
        started_at=_trip_iso(t.started_at) or "",
        ended_at=_trip_iso(t.ended_at),
        distance_miles=t.distance_miles,
        route_json=t.route_json,
        alert_count=t.alert_count or 0,
    )


@app.get("/api/status")
async def api_status(session_id: Optional[str] = None) -> StatusResponse:
    if session_id:
        buf = _sessions.get(session_id)
        if buf is None:
            return StatusResponse(sessions=[])
        return StatusResponse(sessions=[buf.summary(session_id)])
    summaries = [buf.summary(sid) for sid, buf in _sessions.items()]
    return StatusResponse(sessions=summaries)


@app.get("/api/alerts", response_model=AlertsResponse)
async def api_alerts(
    session_id: Optional[str] = None,
    trip_id: Optional[str] = None,
) -> AlertsResponse:
    tid = (trip_id or session_id or "").strip()
    if not tid:
        return AlertsResponse(session_id="", alerts=[])
    async with AsyncSessionLocal() as db:
        rows = await crud.list_alerts_for_trip(db, tid)
    alerts = [
        AlertRecord(
            id=r.id,
            severity=r.severity,
            alert_text=r.alert_text,
            reasoning=r.reasoning,
            timestamp=r.created_at.timestamp(),
        )
        for r in rows
    ]
    return AlertsResponse(session_id=tid, alerts=alerts)


async def _run_alert_pipeline(
    websocket: WebSocket,
    trip_id: str,
    buffer: RollingSignalBuffer,
    context: Optional[DrivingContext],
) -> None:
    try:
        result = await alert_engine.evaluate(trip_id, buffer, context)
        if not result:
            return
        severity = result.get("severity", "none")
        if severity == "none":
            return
        rec = alert_manager.commit_alert(
            trip_id,
            severity,
            str(result.get("alert_text", "")),
            result.get("reasoning"),
        )
        if rec is None:
            return
        async with AsyncSessionLocal() as db:
            try:
                created = datetime.fromtimestamp(rec.timestamp, tz=timezone.utc)
                row = await crud.add_alert_for_trip(
                    db,
                    trip_id,
                    rec.severity,
                    rec.alert_text,
                    rec.reasoning,
                    created,
                )
                rec = AlertRecord(
                    id=row.id,
                    severity=rec.severity,
                    alert_text=rec.alert_text,
                    reasoning=rec.reasoning,
                    timestamp=rec.timestamp,
                )
            except Exception:
                logger.exception("Failed to persist alert for trip %s", trip_id)
        await websocket.send_json(
            {
                "type": "alert",
                "v": 1,
                "severity": rec.severity,
                "alert_text": rec.alert_text,
                "timestamp": rec.timestamp,
                "reasoning": rec.reasoning,
                "id": rec.id,
                "category": "fatigue",
            }
        )
    except Exception:
        logger.exception("Alert pipeline failed for trip %s", trip_id)


async def _run_distraction_pipeline(
    websocket: WebSocket,
    trip_id: str,
    buffer: RollingSignalBuffer,
    context: Optional[DrivingContext],
) -> None:
    try:
        result = distraction_monitor.evaluate(trip_id, buffer, context)
        if not result:
            return
        severity = str(result.get("severity", "mild")).lower()
        if severity == "none":
            return
        text = str(result.get("alert_text", "") or "").strip()
        reasoning = result.get("reasoning")
        category = str(result.get("category", "distraction"))
        ts = time.time()
        rec = AlertRecord(
            severity=severity,
            alert_text=text,
            reasoning=reasoning,
            timestamp=ts,
        )
        async with AsyncSessionLocal() as db:
            try:
                created = datetime.fromtimestamp(ts, tz=timezone.utc)
                row = await crud.add_alert_for_trip(
                    db,
                    trip_id,
                    rec.severity,
                    rec.alert_text,
                    rec.reasoning,
                    created,
                )
                rec = AlertRecord(
                    id=row.id,
                    severity=rec.severity,
                    alert_text=rec.alert_text,
                    reasoning=rec.reasoning,
                    timestamp=rec.timestamp,
                )
            except Exception:
                logger.exception("Failed to persist distraction alert for trip %s", trip_id)
                return
        await websocket.send_json(
            {
                "type": "alert",
                "v": 1,
                "severity": rec.severity,
                "alert_text": rec.alert_text,
                "timestamp": rec.timestamp,
                "reasoning": rec.reasoning,
                "id": rec.id,
                "category": category,
            }
        )
    except Exception:
        logger.exception("Distraction pipeline failed for trip %s", trip_id)


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    trip_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as db:
        await crud.create_trip(db, trip_id)

    _sessions[trip_id] = RollingSignalBuffer(maxlen=90)
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "v": 1,
                "session_id": trip_id,
                "trip_id": trip_id,
            }
        )
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break
            if msg.get("type") != "websocket.receive":
                continue
            text = msg.get("text")
            if not text:
                continue
            if not await enforce_websocket_batch(websocket):
                break
            try:
                raw = json.loads(text)
                batch = MetricBatch.model_validate(raw)
            except (json.JSONDecodeError, ValidationError):
                continue
            buf = _sessions.get(trip_id)
            if buf is None:
                break
            if batch.context:
                _accumulate_progress(trip_id, batch.context)
            if batch.samples:
                buf.extend(batch.samples)
                asyncio.create_task(
                    _run_alert_pipeline(websocket, trip_id, buf, batch.context)
                )
                asyncio.create_task(
                    _run_distraction_pipeline(websocket, trip_id, buf, batch.context)
                )
    finally:
        prog = _trip_progress.pop(trip_id, None)
        miles = prog["miles"] if prog else None
        route_json = crud.route_points_to_json(prog["route"]) if prog and prog.get("route") else "[]"
        try:
            async with AsyncSessionLocal() as db:
                await crud.finalize_trip(
                    db,
                    trip_id,
                    distance_miles=miles if miles is not None else None,
                    route_json=route_json,
                )
        except Exception:
            logger.exception("Failed to finalize trip %s", trip_id)

        _sessions.pop(trip_id, None)
        alert_manager.drop_session(trip_id)
        alert_engine.drop_session(trip_id)
        distraction_monitor.drop_session(trip_id)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def _port() -> int:
    return int(os.environ.get("PORT", "8000"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=_port(), reload=False)
