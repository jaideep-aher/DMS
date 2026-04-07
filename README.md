# Driver Monitoring System (DMS)

Web app: **browser** MediaPipe Face Mesh → **EAR / MAR / head pose** → **WebSocket** batches to **FastAPI** → **OpenAI** contextual alerts + threshold fallback. Deployed on **Railway**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                                 │
│  ┌──────────────┐   getUserMedia    ┌─────────────────────────────────┐   │
│  │ Video +      │ ───────────────► │ MediaPipe Face Mesh (CDN)       │   │
│  │ Canvas mesh  │                  │ EAR, MAR, pose (client-side)    │   │
│  └──────────────┘                  └────────────┬────────────────────┘   │
│                                                 │ metrics + context      │
│                                                 ▼                        │
│                                        WebSocket (JSON v1)               │
└────────────────────────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  RAILWAY / FastAPI (Python 3.11)                                         │
│  ┌──────────────────┐   rolling buffer   ┌───────────────────────────┐  │
│  │ /ws/metrics      │ ─────────────────► │ AlertEngine               │  │
│  │ + PostgreSQL     │                    │ summary → OpenAI API      │  │
│  └────────┬─────────┘                    │ or threshold fallback     │  │
│           │                               └───────────┬───────────────┘  │
│           │  {type: alert, v:1}                       │                  │
│           ▼                                           ▼                  │
│  ┌──────────────────┐                    ┌───────────────────────────┐  │
│  │ AlertManager     │◄───────────────────│ OpenAI Chat Completions   │  │
│  │ cooldown + log   │   (HTTP outbound)    │ default: gpt-4o-mini      │  │
│  └──────────────────┘                    └───────────────────────────┘  │
│  GET /api/trips … /api/alerts … /api/status   Static SPA (Tailwind + Chart.js) │
└─────────────────────────────────────────────────────────────────────────┘
```

## Local development

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."   # optional; threshold fallback works without it
# optional: export OPENAI_MODEL="gpt-4o"   # default is gpt-4o-mini
# optional: unset DATABASE_URL → SQLite file at ./data/dms.db (created automatically)
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`, allow the camera. Toggle **Demo mode** to simulate dropping EAR and yawns without being tired.

## Railway deployment checklist

1. Sign in at [railway.app](https://railway.app) and click **New Project**.
2. Choose **Deploy from GitHub** and authorize the Railway GitHub app if prompted.
3. Select the **DMS** repository and branch **`main`**.
4. Railway should detect the **Dockerfile** (see `railway.json`); confirm build type is **Docker** under service **Settings → Build**.
5. Open **Settings → Networking** and click **Generate Domain** (HTTPS required for camera on most browsers).
6. Add a **PostgreSQL** database (New → Database → PostgreSQL). In your **web service** variables, add **`DATABASE_URL`** and paste the variable reference from the Postgres service (Railway injects `postgres://` or `postgresql://`; the app normalizes it for async SQLAlchemy). Without Postgres, the container would use ephemeral SQLite inside the image — trips and alerts would not survive redeploys.
7. Under **Variables**, add **`OPENAI_API_KEY`** with your OpenAI API key. Optional: **`OPENAI_MODEL`** (e.g. `gpt-4o-mini`, `gpt-4o`). Leave the key blank only if you accept threshold-only alerts.
8. Trigger a **Deploy** (or push to `main`); wait until the deployment shows **Success**.
9. Open the public URL, grant **camera** permission, confirm the dashboard loads and the status line shows the pipeline running.
10. Optionally open browser devtools → **Network** → confirm **WebSocket** to `/ws/metrics` is **101** and messages flow.
11. Optional: `GET /api/trips` after a session; `GET /api/alerts?session_id=<id from hello>` (or `trip_id=`) loads persisted alerts from the database.

## Colab benchmark (`benchmark.ipynb`)

### Where to get video clips

| Source | Notes |
|--------|--------|
| [NTHU-DDD dataset page](https://cv.cs.nthu.edu.tw/php/callforpaper/datasets/DDD/) | Driver drowsiness video; **license agreement** by email (see site). Not an instant public ZIP. |
| [UTA-RLDD](https://sites.google.com/view/utarldd/home) | Real-life drowsiness dataset; follow site instructions for access. |
| [UTA-RLDD cropped faces on Kaggle](https://www.kaggle.com/datasets/mathiasviborg/uta-rldd-videos-cropped-by-faces) | Downloadable after Kaggle login; good for face-forward clips. |
| Your own MP4 | Phone selfie / webcam recording — use Colab **upload** cell in the notebook. |

### How to run the notebook

1. Upload `benchmark.ipynb` to [Google Colab](https://colab.research.google.com/) (File → Upload notebook) or open from GitHub.
2. **Runtime → Run all** (or run cells top to bottom).
3. Add **Secrets**: Colab **Secrets** (key icon) → **`OPENAI_API_KEY`**, or set `os.environ` in the key cell. Optional secret **`OPENAI_MODEL`** (defaults to `gpt-4o-mini`).
4. Run the **video** cell: upload an MP4 or set `VIDEO_PATH` to a Drive path after mounting.
5. After the stats cell, download **`benchmark_log.json`** and **`benchmark_plots.png`** from the Colab file browser.

### Reading metrics for your resume

- Open **`benchmark_log.json`**: field **`summary.pct_fewer_alerts_than_baseline`** is the headline **“X% fewer alerts than fixed EAR threshold”** (OpenAI debounced engine vs. mean EAR < 0.21 for ~1s window).
- **`summary.avg_seconds_between_openai_alerts`** supports **cadence / escalation spacing** talking points.
- **`openai_severity_counts`** supports bullets about severity mix.
- For a honest **false-alert** claim you need **labels** (e.g. NTHU / UTA annotations): match alert timestamps to ground-truth drowsy segments; the notebook comments describe this gap.

### Resume bullet template (fill placeholders)

- Built an end-to-end **driver monitoring** web app: **MediaPipe** face mesh in the browser, **FastAPI** + **WebSockets**, **OpenAI**-based contextual safety alerts with **threshold fallback** when the API is unavailable.
- Shipped on **Railway** with Docker; added **Chart.js** live EAR/MAR trends and a **demo mode** for fatigue simulation.
- Benchmarked offline on **`[N clips / dataset]`**: contextual engine emitted **`__%`** fewer alerts than a **fixed EAR < 0.21 / 1s** baseline on the same video; severity distribution: **`[mild / moderate / severe counts]`** (refine with labeled data for false-positive rate).

## Project layout

```
server/
  main.py           # FastAPI, WebSocket, static mount, trip lifecycle
  database.py       # Async engine: DATABASE_URL (Postgres) or SQLite
  sql_models.py     # Trip + Alert ORM
  crud.py           # Trips and alert log persistence
  alert_engine.py   # Signal features, OpenAI, threshold fallback
  alert_manager.py  # Cooldown + in-session state
  buffer.py         # Rolling buffer with server timestamps
  models.py         # Pydantic schemas
static/
  index.html        # Tailwind (CDN) layout
  js/               # vision, websocket, context, charts, alerts_ui
benchmark.ipynb     # Colab: video → metrics → OpenAI vs baseline
```

## API quick reference

| Endpoint | Purpose |
|----------|---------|
| `WS /ws/metrics` | Client sends `{type:"metrics_batch",v:1,samples:[...],context?:{...}}`; server sends `hello` with `session_id` / `trip_id`, then `{type:"alert",v:1,...}` (optional `id` = DB row). |
| `GET /api/status?session_id=` | Rolling buffer summary for an active WebSocket. |
| `GET /api/alerts?session_id=` or `?trip_id=` | Alert log for that trip from the database. |
| `GET /api/trips` | Recent trips (`limit`, `offset`). |
| `GET /api/trips/{trip_id}` | One trip: start/end, distance, route JSON, alert count. |

## License

See repository root for license terms if added. Third-party: MediaPipe, OpenAI, Tailwind CDN, Chart.js — follow their licenses.
