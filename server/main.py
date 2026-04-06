import os
import json
import uuid
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from server.models import MetricBatch, MetricFrame, StatusResponse
from server.buffer import SessionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Driver Monitoring System")
store = SessionStore()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(
        active_sessions=store.active_count,
        sessions=store.all_summaries(),
    )


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    buf = store._sessions.get(session_id)
    if buf is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return buf.summarize(session_id)


@app.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    buf = store.get_or_create(session_id)
    logger.info(f"WS connected: session={session_id}")

    # Send session id to client
    await websocket.send_json({"type": "connected", "session_id": session_id})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "msg": "invalid json"})
                continue

            # Accept either a single frame dict or a batch {frames: [...]}
            if isinstance(data, list):
                frames = data
            elif "frames" in data:
                frames = data["frames"]
            else:
                frames = [data]

            parsed = []
            for f in frames:
                try:
                    parsed.append(MetricFrame(**f))
                except Exception as e:
                    logger.warning(f"Bad frame: {e}")

            if parsed:
                buf.add_batch(parsed)

            summary = buf.summarize(session_id)
            await websocket.send_json({
                "type": "ack",
                "session_id": session_id,
                "frame_count": summary.frame_count,
                "drowsy_frames": summary.drowsy_frames,
                "yawn_frames": summary.yawn_frames,
                "distracted_frames": summary.distracted_frames,
                "avg_ear": summary.avg_ear,
                "avg_mar": summary.avg_mar,
            })

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: session={session_id}")
        store.remove(session_id)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server.main:app", host="0.0.0.0", port=port, reload=False)
