"""
Per-client abuse limits: sliding RPM (in-memory), daily + lifetime (DB-backed).

Uses HMAC fingerprints — raw IPs are not stored. Tune via env:
  RATE_LIMIT_ENABLED, RATE_LIMIT_RPM, RATE_LIMIT_DAILY, RATE_LIMIT_LIFETIME, RATE_LIMIT_SECRET
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request, WebSocket

from server import crud
from server.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# --- Tunables (env) ---
def _enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes")


def _rpm_limit() -> int:
    return max(1, int(os.environ.get("RATE_LIMIT_RPM", "90")))


def _daily_limit() -> int:
    return max(1, int(os.environ.get("RATE_LIMIT_DAILY", "8000")))


def _lifetime_limit() -> int:
    return max(1, int(os.environ.get("RATE_LIMIT_LIFETIME", "500000")))


def _global_units_daily() -> int:
    """Max aggregate API+WS units per UTC day across all clients; 0 = unlimited."""
    raw = os.environ.get("GLOBAL_UNITS_DAILY", "2000000").strip()
    try:
        n = int(raw)
    except ValueError:
        return 0
    return n if n > 0 else 0


def _global_units_lifetime() -> int:
    """Max aggregate units all-time across all clients; 0 = unlimited."""
    raw = os.environ.get("GLOBAL_UNITS_LIFETIME", "0").strip()
    try:
        n = int(raw)
    except ValueError:
        return 0
    return n if n > 0 else 0


def _secret() -> bytes:
    s = os.environ.get("RATE_LIMIT_SECRET", "").strip()
    if not s:
        s = "dev-insecure-change-for-production"
        logger.warning(
            "RATE_LIMIT_SECRET unset; using default (set a long random secret in production)"
        )
    return s.encode()


def client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def client_ip_from_websocket(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


def fingerprint(ip: str) -> str:
    return hmac.new(_secret(), ip.encode("utf-8"), hashlib.sha256).hexdigest()


# --- Sliding window RPM (per process) ---
_rpm_lock = asyncio.Lock()
_rpm_events: dict[str, deque[float]] = {}
_MAX_TRACKED_KEYS = 8000
_RPM_WINDOW_SEC = 60.0


def _prune_rpm_keys() -> None:
    if len(_rpm_events) <= _MAX_TRACKED_KEYS:
        return
    # Drop oldest half of keys (by insertion order undefined — drop arbitrary)
    keys = list(_rpm_events.keys())
    for k in keys[: len(keys) // 2]:
        _rpm_events.pop(k, None)


async def _check_rpm(fp: str) -> bool:
    now = time.monotonic()
    cutoff = now - _RPM_WINDOW_SEC
    async with _rpm_lock:
        dq = _rpm_events.setdefault(fp, deque())
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _rpm_limit():
            return False
        dq.append(now)
        _prune_rpm_keys()
    return True


_per_fp_db_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _lock_for(fp: str) -> asyncio.Lock:
    return _per_fp_db_lock[fp]


async def enforce_rate_limit(request: Request) -> None:
    """Raises HTTPException 429 if over limit. Call for /api routes."""
    if not _enabled():
        return
    ip = client_ip_from_request(request)
    fp = fingerprint(ip)
    if not await _check_rpm(fp):
        raise HTTPException(
            status_code=429,
            detail="Too many requests per minute. Try again shortly.",
        )

    async with _lock_for(fp):
        async with AsyncSessionLocal() as db:
            ok, reason = await crud.check_increment_usage(
                db,
                fp,
                _daily_limit(),
                _lifetime_limit(),
                global_daily_max=_global_units_daily(),
                global_lifetime_max=_global_units_lifetime(),
            )
    if not ok:
        msg = {
            "daily": "Daily usage limit reached. Try again tomorrow.",
            "lifetime": "Usage limit reached for this network.",
            "global_daily": "Service daily capacity reached. Try again tomorrow.",
            "global_lifetime": "Service capacity limit reached.",
        }.get(reason, "Rate limit exceeded.")
        raise HTTPException(status_code=429, detail=msg)


async def enforce_websocket_batch(websocket: WebSocket) -> bool:
    """
    Returns True if this batch may proceed, False if connection should close.
    If False, sends a JSON error frame first (best-effort).
    """
    if not _enabled():
        return True
    ip = client_ip_from_websocket(websocket)
    fp = fingerprint(ip)
    if not await _check_rpm(fp):
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "v": 1,
                    "code": "rate_limit",
                    "message": "Too many messages per minute.",
                }
            )
        except Exception:
            pass
        return False

    async with _lock_for(fp):
        async with AsyncSessionLocal() as db:
            ok, reason = await crud.check_increment_usage(
                db,
                fp,
                _daily_limit(),
                _lifetime_limit(),
                global_daily_max=_global_units_daily(),
                global_lifetime_max=_global_units_lifetime(),
            )
    if not ok:
        msg = {
            "daily": "Daily limit reached.",
            "lifetime": "Lifetime usage limit reached for this network.",
            "global_daily": "Service daily capacity reached.",
            "global_lifetime": "Service capacity limit reached.",
        }.get(reason, "Rate limit exceeded.")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "v": 1,
                    "code": "rate_limit",
                    "message": msg,
                }
            )
        except Exception:
            pass
        return False
    return True
