from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from server.buffer import RollingSignalBuffer
from server.models import DrivingContext, MetricSample

SYSTEM_PROMPT = """You are a driver safety co-pilot. Given physiological signals and driving context, assess drowsiness severity (none/mild/moderate/severe) and produce a short natural spoken alert. Be specific — reference time driving, road type, suggest concrete actions like 'pull over at next exit' or 'open your window'. Respond ONLY as JSON: {severity, alert_text, reasoning}"""


@dataclass
class _DebounceState:
    last_summary_hash: str = ""
    last_llm_at: float = 0.0


class AlertEngine:
    """
    Builds a compact signal summary, calls Claude when the snapshot changes or every 30s.
    """

    MODEL = "claude-sonnet-4-20250514"
    WINDOW_SHORT_SEC = 8.0
    MAR_YAWN_THRESHOLD = 0.42
    EAR_LOW_THRESHOLD = 0.19
    PITCH_NOD_DEG = 12.0

    def __init__(self) -> None:
        self._debounce: dict[str, _DebounceState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client: Any = None
        self._client_failed = False

    def _get_client(self) -> Any:
        if self._client_failed:
            return None
        if self._client is not None:
            return self._client
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        try:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=key)
        except Exception:
            self._client_failed = True
            self._client = None
            return None
        return self._client

    def _debounce_key(self, summary: str, ctx: Optional[DrivingContext]) -> str:
        ctx_s = ctx.model_dump_json() if ctx else "{}"
        raw = summary + "|" + ctx_s
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def should_call_llm(self, session_id: str, summary_key: str) -> bool:
        now = time.time()
        st = self._debounce.setdefault(session_id, _DebounceState())
        if summary_key != st.last_summary_hash:
            return True
        if now - st.last_llm_at >= 30.0:
            return True
        return False

    def mark_llm_called(self, session_id: str, summary_key: str) -> None:
        st = self._debounce.setdefault(session_id, _DebounceState())
        st.last_summary_hash = summary_key
        st.last_llm_at = time.time()

    def drop_session(self, session_id: str) -> None:
        self._debounce.pop(session_id, None)
        self._locks.pop(session_id, None)

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def build_signal_summary(
        self,
        buffer: RollingSignalBuffer,
        context: Optional[DrivingContext],
    ) -> str:
        recent = buffer.recent(self.WINDOW_SHORT_SEC)
        if not recent:
            samples = buffer.all_samples()
            if not samples:
                return "No face metrics in buffer yet."
            recent = [(s, 0.0) for s in samples[-20:]]

        samples_only: list[MetricSample] = [s for s, _ in recent]
        n = len(samples_only)
        ears = [(s.ear_left + s.ear_right) / 2 for s in samples_only]
        ear_avg = sum(ears) / n
        mar_vals = [s.mar for s in samples_only]
        mar_max = max(mar_vals)
        mar_avg = sum(mar_vals) / n
        pitch_vals = [s.pitch for s in samples_only]
        pitch_min = min(pitch_vals)
        pitch_max = max(pitch_vals)
        pitch_swing = pitch_max - pitch_min

        yawns = self._count_yawn_events(mar_vals)
        nodding = pitch_min < -self.PITCH_NOD_DEG or pitch_swing > 18.0
        eyes_low = ear_avg < self.EAR_LOW_THRESHOLD

        parts = [
            f"EAR avg {ear_avg:.2f} last ~{self.WINDOW_SHORT_SEC:.0f}s",
            f"MAR avg {mar_avg:.2f}, peak {mar_max:.2f}",
        ]
        if yawns:
            parts.append(f"{yawns} yawn-like mouth opening(s) detected")
        if nodding:
            parts.append("head nodding or large pitch swing")
        if eyes_low:
            parts.append("eyes trending closed (low EAR)")

        if context:
            mins = max(0, context.session_elapsed_sec) // 60
            parts.append(
                f"{context.road_type} road at ~{context.speed_mph:.0f} mph, "
                f"~{mins} min in session, local time {context.time_of_day} ({context.daypart})"
            )
        else:
            parts.append("driving context not provided")

        return ", ".join(parts)

    def _count_yawn_events(self, mar_series: list[float]) -> int:
        """Rough count of distinct high-MAR excursions (proxy for yawns)."""
        if len(mar_series) < 3:
            return 0
        events = 0
        in_spike = False
        for v in mar_series:
            if v >= self.MAR_YAWN_THRESHOLD:
                if not in_spike:
                    events += 1
                    in_spike = True
            else:
                if v < self.MAR_YAWN_THRESHOLD * 0.75:
                    in_spike = False
        return min(events, 5)

    def _parse_llm_json(self, text: str) -> Optional[dict[str, Any]]:
        t = text.strip()
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        try:
            data = json.loads(t)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    async def evaluate(
        self,
        session_id: str,
        buffer: RollingSignalBuffer,
        context: Optional[DrivingContext],
    ) -> Optional[dict[str, Any]]:
        async with self._session_lock(session_id):
            summary = self.build_signal_summary(buffer, context)
            key = self._debounce_key(summary, context)
            if not self.should_call_llm(session_id, key):
                return None

            client = self._get_client()
            if client is None:
                self.mark_llm_called(session_id, key)
                return self._heuristic_fallback(summary, context)

            user_content = f"Signal summary:\n{summary}\n\nRespond with JSON only."
            try:
                msg = await client.messages.create(
                    model=self.MODEL,
                    max_tokens=256,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
            except Exception:
                self.mark_llm_called(session_id, key)
                return self._heuristic_fallback(summary, context)

            text = ""
            for block in msg.content:
                if hasattr(block, "text"):
                    text += block.text
            parsed = self._parse_llm_json(text)
            self.mark_llm_called(session_id, key)
            if not parsed:
                return self._heuristic_fallback(summary, context)
            sev = str(parsed.get("severity", "none")).lower()
            if sev not in ("none", "mild", "moderate", "severe"):
                sev = "none"
            return {
                "severity": sev,
                "alert_text": str(parsed.get("alert_text", "") or "Stay alert.").strip(),
                "reasoning": parsed.get("reasoning"),
            }

    def _heuristic_fallback(
        self,
        summary: str,
        context: Optional[DrivingContext],
    ) -> dict[str, Any]:
        """When API is unavailable, avoid blocking product demo."""
        sev = "none"
        alert = "Keep your eyes on the road."
        if "eyes trending closed" in summary.lower():
            sev = "moderate"
            alert = "Your eyes look heavy — consider a short break or fresh air."
        elif "yawn-like" in summary.lower():
            sev = "mild"
            alert = "Possible fatigue detected — sit up straight and take a deep breath."
        if context and context.road_type == "highway" and sev != "none":
            alert += " If symptoms continue, plan to exit when safe."
        return {"severity": sev, "alert_text": alert, "reasoning": "heuristic_fallback"}
