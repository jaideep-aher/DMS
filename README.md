# Driver Monitoring System (DMS)

Web app: **browser** MediaPipe Face Mesh → **EAR / MAR / head pose** → **WebSocket** batches to **FastAPI** → **Claude** (Anthropic) contextual alerts + threshold fallback. Deployed on **Railway**.

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
│  │ + session memory │                    │ summary → Claude API      │  │
│  └────────┬─────────┘                    │ or threshold fallback     │  │
│           │                               └───────────┬───────────────┘  │
│           │  {type: alert, v:1}                       │                  │
│           ▼                                           ▼                  │
│  ┌──────────────────┐                    ┌───────────────────────────┐  │
│  │ AlertManager     │◄───────────────────│ Anthropic (Claude)        │  │
│  │ cooldown + log   │   (HTTP outbound)    │ claude-sonnet-4-…       │  │
│  └──────────────────┘                    └───────────────────────────┘  │
│  GET /api/status   GET /api/alerts   Static SPA (Tailwind + Chart.js)     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Local development

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."   # optional; threshold fallback works without it
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`, allow the camera. Toggle **Demo mode** to simulate dropping EAR and yawns without being tired.

## Railway deployment checklist (≤10 steps)

1. Sign in at [railway.app](https://railway.app) and click **New Project**.
2. Choose **Deploy from GitHub** and authorize the Railway GitHub app if prompted.
3. Select the **DMS** repository and branch **`main`**.
4. Railway should detect the **Dockerfile** (see `railway.json`); confirm build type is **Docker** under service **Settings → Build**.
5. Open **Settings → Networking** and click **Generate Domain** (HTTPS required for camera on most browsers).
6. Under **Variables**, add **`ANTHROPIC_API_KEY`** with your Anthropic API key (Claude). Leave blank only if you accept threshold-only alerts.
7. Trigger a **Deploy** (or push to `main`); wait until the deployment shows **Success**.
8. Open the public URL, grant **camera** permission, confirm the dashboard loads and the status line shows the pipeline running.
9. Optionally open browser devtools → **Network** → confirm **WebSocket** to `/ws/metrics` is **101** and messages flow.
10. Optional: call `GET https://<your-domain>/api/status` and `GET /api/alerts?session_id=<id from hello message>` while a tab is connected.

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
3. Add **Secrets**: Colab **Secrets** (key icon) → `ANTHROPIC_API_KEY`, or set `os.environ` in the key cell.
4. Run the **video** cell: upload an MP4 or set `VIDEO_PATH` to a Drive path after mounting.
5. After the stats cell, download **`benchmark_log.json`** and **`benchmark_plots.png`** from the Colab file browser.

### Reading metrics for your resume

- Open **`benchmark_log.json`**: field **`summary.pct_fewer_alerts_than_baseline`** is the headline **“X% fewer alerts than fixed EAR threshold”** (Claude debounced engine vs. mean EAR < 0.21 for ~1s window).
- **`claude_severity_counts`** supports bullets about severity mix.
- For a honest **false-alert** claim you need **labels** (e.g. NTHU / UTA annotations): match alert timestamps to ground-truth drowsy segments; the notebook comments describe this gap.

### Resume bullet template (fill placeholders)

- Built an end-to-end **driver monitoring** web app: **MediaPipe** face mesh in the browser, **FastAPI** + **WebSockets**, **Claude**-based contextual safety alerts with **threshold fallback** when the API is unavailable.
- Shipped on **Railway** with Docker; added **Chart.js** live EAR/MAR trends and a **demo mode** for fatigue simulation.
- Benchmarked offline on **`[N clips / dataset]`**: contextual engine emitted **`__%`** fewer alerts than a **fixed EAR < 0.21 / 1s** baseline on the same video; severity distribution: **`[mild / moderate / severe counts]`** (refine with labeled data for false-positive rate).

## Project layout

```
server/
  main.py           # FastAPI, WebSocket, static mount
  alert_engine.py   # Signal features, Claude, threshold fallback
  alert_manager.py  # Cooldown + alert history
  buffer.py         # Rolling buffer with server timestamps
  models.py         # Pydantic schemas
static/
  index.html        # Tailwind (CDN) layout
  js/               # vision, websocket, context, charts, alerts_ui
benchmark.ipynb     # Colab: video → metrics → Claude vs baseline
```

## API quick reference

| Endpoint | Purpose |
|----------|---------|
| `WS /ws/metrics` | Client sends `{type:"metrics_batch",v:1,samples:[...],context?:{...}}`; server sends `hello`, then `{type:"alert",v:1,...}`. |
| `GET /api/status?session_id=` | Rolling buffer summary. |
| `GET /api/alerts?session_id=` | Alert history for the active session. |

## License

See repository root for license terms if added. Third-party: MediaPipe, Anthropic, Tailwind CDN, Chart.js — follow their licenses.
