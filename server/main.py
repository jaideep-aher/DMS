from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server.alert_engine import AlertEngine
from server.alert_manager import AlertManager
from server.buffer import RollingSignalBuffer
from server.models import AlertsResponse, DrivingContext, MetricBatch, StatusResponse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger(__name__)

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

app = FastAPI(title="Driver Monitoring System", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, RollingSignalBuffer] = {}
alert_engine = AlertEngine()
alert_manager = AlertManager()


@app.get("/api/status")
async def api_status(session_id: Optional[str] = None) -> StatusResponse:
    if session_id:
        buf = _sessions.get(session_id)
        if buf is None:
            return StatusResponse(sessions=[])
        return StatusResponse(sessions=[buf.summary(session_id)])
    summaries = [buf.summary(sid) for sid, buf in _sessions.items()]
    return StatusResponse(sessions=summaries)


@app.get("/api/alerts")
async def api_alerts(session_id: str) -> AlertsResponse:
    if not session_id or session_id not in _sessions:
        return AlertsResponse(session_id=session_id or "", alerts=[])
    return AlertsResponse(session_id=session_id, alerts=alert_manager.get_alerts(session_id))


async def _run_alert_pipeline(
    websocket: WebSocket,
    session_id: str,
    buffer: RollingSignalBuffer,
    context: Optional[DrivingContext],
) -> None:
    try:
        result = await alert_engine.evaluate(session_id, buffer, context)
        if not result:
            return
        severity = result.get("severity", "none")
        if severity == "none":
            return
        rec = alert_manager.commit_alert(
            session_id,
            severity,
            str(result.get("alert_text", "")),
            result.get("reasoning"),
        )
        if rec is None:
            return
        await websocket.send_json(
            {
                "type": "alert",
                "v": 1,
                "severity": rec.severity,
                "alert_text": rec.alert_text,
                "timestamp": rec.timestamp,
                "reasoning": rec.reasoning,
            }
        )
    except Exception:
        logger.exception("Alert pipeline failed for session %s", session_id)


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    sid = str(uuid.uuid4())
    _sessions[sid] = RollingSignalBuffer(maxlen=90)
    try:
        await websocket.send_json({"type": "hello", "v": 1, "session_id": sid})
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
            try:
                raw = json.loads(text)
                batch = MetricBatch.model_validate(raw)
            except (json.JSONDecodeError, ValidationError):
                continue
            buf = _sessions.get(sid)
            if buf is None:
                break
            if batch.samples:
                buf.extend(batch.samples)
                asyncio.create_task(
                    _run_alert_pipeline(websocket, sid, buf, batch.context)
                )
    finally:
        _sessions.pop(sid, None)
        alert_manager.drop_session(sid)
        alert_engine.drop_session(sid)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def _port() -> int:
    return int(os.environ.get("PORT", "8000"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=_port(), reload=False)
