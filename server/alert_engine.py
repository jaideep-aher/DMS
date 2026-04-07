from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from server.buffer import RollingSignalBuffer
from server.models import DrivingContext, MetricSample

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a driver safety co-pilot. Given physiological signals and driving context, assess drowsiness severity (none/mild/moderate/severe) and produce a short natural spoken alert. Be specific — reference time driving, road type, suggest concrete actions like 'pull over at next exit' or 'open your window'. Respond ONLY as JSON: {severity, alert_text, reasoning}"""


@dataclass
class _DebounceState:
    last_summary_hash: str = ""
    last_llm_at: float = 0.0


@dataclass(frozen=True)
class SignalFeatures:
    """Aggregated physiology features from the rolling buffer (recent window)."""

    ear_avg: float
    mar_avg: float
    mar_max: float
    yawn_count: int
    nodding: bool
    eyes_low: bool
    fraction_ear_below_drowsy: float
    sample_count: int


class AlertEngine:
    """
    Builds a compact signal summary, calls OpenAI Chat Completions when the snapshot
    changes or every 30s. Falls back to threshold-based alerts if the API is unavailable
    or returns invalid JSON.
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    WINDOW_SHORT_SEC = 8.0
    MAR_YAWN_THRESHOLD = 0.42
    EAR_LOW_THRESHOLD = 0.19
    EAR_DROWSY_THRESHOLD = 0.21
    PITCH_NOD_DEG = 12.0

    def __init__(self) -> None:
        self._debounce: dict[str, _DebounceState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client: Any = None
        self._client_failed = False

    def _model_name(self) -> str:
        return os.environ.get("OPENAI_MODEL", self.DEFAULT_MODEL).strip() or self.DEFAULT_MODEL

    def _get_client(self) -> Any:
        if self._client_failed:
            return None
        if self._client is not None:
            return self._client
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=key)
        except Exception as exc:
            logger.warning("OpenAI client init failed: %s", exc)
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

    def extract_features(
        self,
        buffer: RollingSignalBuffer,
    ) -> Optional[SignalFeatures]:
        """Compute numeric features from the recent server-time window (or last samples)."""
        recent = buffer.recent(self.WINDOW_SHORT_SEC)
        if not recent:
            samples = buffer.all_samples()
            if not samples:
                return None
            recent = [(s, 0.0) for s in samples[-20:]]

        samples_only: list[MetricSample] = [s for s, _ in recent]
        n = len(samples_only)
        ears = [(s.ear_left + s.ear_right) / 2 for s in samples_only]
        ear_avg = sum(ears) / n
        below = sum(1 for e in ears if e < self.EAR_DROWSY_THRESHOLD)
        frac_drowsy = below / n if n else 0.0
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

        return SignalFeatures(
            ear_avg=ear_avg,
            mar_avg=mar_avg,
            mar_max=mar_max,
            yawn_count=yawns,
            nodding=nodding,
            eyes_low=eyes_low,
            fraction_ear_below_drowsy=frac_drowsy,
            sample_count=n,
        )

    def build_signal_summary(
        self,
        buffer: RollingSignalBuffer,
        context: Optional[DrivingContext],
    ) -> str:
        feats = self.extract_features(buffer)
        if feats is None:
            return "No face metrics in buffer yet."

        parts = [
            f"EAR avg {feats.ear_avg:.2f} last ~{self.WINDOW_SHORT_SEC:.0f}s",
            f"MAR avg {feats.mar_avg:.2f}, peak {feats.mar_max:.2f}",
        ]
        if feats.yawn_count:
            parts.append(f"{feats.yawn_count} yawn-like mouth opening(s) detected")
        if feats.nodding:
            parts.append("head nodding or large pitch swing")
        if feats.eyes_low:
            parts.append("eyes trending closed (low EAR)")
        if feats.fraction_ear_below_drowsy >= 0.5:
            parts.append(
                f"EAR below {self.EAR_DROWSY_THRESHOLD:.2f} in "
                f"{feats.fraction_ear_below_drowsy:.0%} of recent samples"
            )

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

    def threshold_based_alert(
        self,
        features: SignalFeatures,
        context: Optional[DrivingContext],
    ) -> dict[str, Any]:
        """
        Deterministic severity when OpenAI is down or returns unusable output.
        Aligns with benchmark-style EAR < 0.21 predominance plus MAR/yaw hints.
        """
        sev = "none"
        alert = "Stay alert and keep scanning the road ahead."
        reasoning = "threshold_fallback"

        if features.fraction_ear_below_drowsy >= 0.65 or features.eyes_low:
            sev = "moderate"
            alert = (
                "Sustained low eye openness — pull over when safe, stretch, "
                "or take a short break."
            )
        elif features.fraction_ear_below_drowsy >= 0.4:
            sev = "mild"
            alert = "Your eyes may be fatiguing — open a window and blink deliberately."
        elif features.yawn_count >= 1:
            sev = "mild"
            alert = "Possible fatigue or yawning — sit tall and consider a break soon."
        elif features.nodding:
            sev = "mild"
            alert = "Head pose shifting — check posture and stay engaged with the road."

        if context and context.road_type == "highway" and sev != "none":
            alert += " On the highway, use the next safe exit if drowsiness continues."

        return {"severity": sev, "alert_text": alert, "reasoning": reasoning}

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

            feats = self.extract_features(buffer)
            if feats is None:
                return None

            client = self._get_client()
            if client is None:
                logger.info("No OpenAI client; using threshold fallback for session %s", session_id)
                self.mark_llm_called(session_id, key)
                return self.threshold_based_alert(feats, context)

            user_content = f"Signal summary:\n{summary}\n\nRespond with JSON only."
            try:
                resp = await client.chat.completions.create(
                    model=self._model_name(),
                    max_tokens=256,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                )
            except Exception as exc:
                logger.warning("OpenAI API error for session %s: %s", session_id, exc)
                self.mark_llm_called(session_id, key)
                return self.threshold_based_alert(feats, context)

            text = (resp.choices[0].message.content or "").strip()
            parsed = self._parse_llm_json(text)
            self.mark_llm_called(session_id, key)
            if not parsed:
                logger.warning("OpenAI returned non-JSON for session %s; threshold fallback", session_id)
                return self.threshold_based_alert(feats, context)

            sev = str(parsed.get("severity", "none")).lower()
            if sev not in ("none", "mild", "moderate", "severe"):
                sev = "none"
            return {
                "severity": sev,
                "alert_text": str(parsed.get("alert_text", "") or "Stay alert.").strip(),
                "reasoning": parsed.get("reasoning"),
            }
