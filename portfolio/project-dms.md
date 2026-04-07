# Portfolio entry: Driver Monitoring System

Paste into your personal site (Next.js, Astro, Framer, or static HTML). Live app: **https://dms.aher.dev/**

---

## Short headline (hero / card title)

**Driver Monitoring System** — real-time in-cabin psychophysiology & gaze-adjacent inference

---

## One-liner (subtitle)

Browser-side MediaPipe vision, dual-path alert policy (LLM + deterministic), async PostgreSQL trip ledger, WebSocket telemetry — deployed on Railway.

---

## Body copy (dense / “heavy project” tone)

End-to-end driver-monitoring prototype with **edge-local perception** (MediaPipe Face Mesh, refined iris topology, EAR/MAR, PnP head pose via OpenCV.js with geometric fallback) and a **FastAPI** control plane. Metrics egress uses a versioned **WebSocket** schema; server-side **rolling temporal buffers** feed debounced **OpenAI Chat Completions** plus orthogonal **distraction heuristics** (gaze-region voting, independent cooldown namespace). Persistence through **SQLAlchemy 2.0 async** against **PostgreSQL** (TLS to `asyncpg`) with SQLite fallback; trip entities carry route polylines, odometer integration, and append-only alert history for analytics backfills. **Docker** + **Railway** deployment with co-located static hosting for single-origin camera policy compliance.

---

## Tech tags (chips)

`FastAPI` · `WebSockets` · `SQLAlchemy 2.0` · `asyncpg` · `PostgreSQL` · `MediaPipe` · `OpenCV.js` · `OpenAI API` · `Docker` · `Railway` · `Pydantic v2` · `Uvicorn`

---

## Links

- **Live:** https://dms.aher.dev/
- **About (technical):** https://dms.aher.dev/about.html

---

## JSX example (Next.js / React)

```tsx
<article className="project-card">
  <h3>Driver Monitoring System</h3>
  <p className="muted">
    In-cabin DMS prototype — browser vision, dual alert topologies, async trip persistence.
  </p>
  <a href="https://dms.aher.dev/" target="_blank" rel="noopener noreferrer">
    Live demo
  </a>
  {" · "}
  <a href="https://dms.aher.dev/about.html" target="_blank" rel="noopener noreferrer">
    Technical overview
  </a>
</article>
```

---

## JSON (CMS / headless)

```json
{
  "slug": "driver-monitoring-system",
  "title": "Driver Monitoring System",
  "year": "2026",
  "role": "Design & full-stack implementation",
  "summary": "Real-time DMS stack: MediaPipe in-browser, FastAPI + WebSockets, SQLAlchemy async persistence, dual fatigue/distraction policies, Railway deployment.",
  "links": {
    "live": "https://dms.aher.dev/",
    "about": "https://dms.aher.dev/about.html"
  },
  "tags": [
    "FastAPI",
    "WebSockets",
    "PostgreSQL",
    "MediaPipe",
    "OpenAI",
    "Railway"
  ]
}
```
