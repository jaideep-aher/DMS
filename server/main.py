from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server.buffer import RollingSignalBuffer
from server.models import MetricBatch, StatusResponse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Driver Monitoring System", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> rolling buffer
_sessions: dict[str, RollingSignalBuffer] = {}


@app.get("/api/status")
async def api_status(session_id: Optional[str] = None) -> StatusResponse:
    if session_id:
        buf = _sessions.get(session_id)
        if buf is None:
            return StatusResponse(sessions=[])
        return StatusResponse(sessions=[buf.summary(session_id)])
    summaries = [buf.summary(sid) for sid, buf in _sessions.items()]
    return StatusResponse(sessions=summaries)


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    sid = str(uuid.uuid4())
    _sessions[sid] = RollingSignalBuffer(maxlen=90)
    try:
        await websocket.send_json({"type": "hello", "session_id": sid})
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
    finally:
        _sessions.pop(sid, None)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def _port() -> int:
    return int(os.environ.get("PORT", "8000"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=_port(), reload=False)
