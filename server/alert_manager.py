from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from server.models import AlertRecord


@dataclass
class EscalationState:
    last_severity: str = "none"
    elevated_streak: int = 0


class AlertManager:
    """Per-session cooldown, alert history, and coarse escalation tracking."""

    COOLDOWN_SEC = 15.0
    MAX_ALERTS = 20

    def __init__(self) -> None:
        self._last_push_at: dict[str, float] = {}
        self._history: dict[str, deque[AlertRecord]] = {}
        self._escalation: dict[str, EscalationState] = {}

    def _history_deque(self, session_id: str) -> deque[AlertRecord]:
        if session_id not in self._history:
            self._history[session_id] = deque(maxlen=self.MAX_ALERTS)
        return self._history[session_id]

    def record_escalation(self, session_id: str, severity: str) -> None:
        esc = self._escalation.setdefault(session_id, EscalationState())
        elevated = severity in ("moderate", "severe")
        if elevated:
            if severity == esc.last_severity or severity == "severe":
                esc.elevated_streak += 1
            else:
                esc.elevated_streak = 1
        else:
            esc.elevated_streak = 0
        esc.last_severity = severity

    def should_emit_to_client(self, session_id: str) -> bool:
        now = time.time()
        last = self._last_push_at.get(session_id, 0.0)
        return now - last >= self.COOLDOWN_SEC

    def commit_alert(
        self,
        session_id: str,
        severity: str,
        alert_text: str,
        reasoning: Optional[str] = None,
    ) -> Optional[AlertRecord]:
        """
        Persist an alert and return it for WebSocket delivery if the 15s cooldown has elapsed.

        Returns ``None`` when suppressed by cooldown (duplicate chatter).
        """
        if not self.should_emit_to_client(session_id):
            return None
        now = time.time()
        self._last_push_at[session_id] = now
        rec = AlertRecord(
            severity=severity,
            alert_text=alert_text,
            reasoning=reasoning,
            timestamp=now,
        )
        self._history_deque(session_id).append(rec)
        self.record_escalation(session_id, severity)
        return rec

    def get_alerts(self, session_id: str) -> list[AlertRecord]:
        return list(self._history_deque(session_id))

    def drop_session(self, session_id: str) -> None:
        self._last_push_at.pop(session_id, None)
        self._history.pop(session_id, None)
        self._escalation.pop(session_id, None)
