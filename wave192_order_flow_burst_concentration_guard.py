"""
wave192_order_flow_burst_concentration_guard.py
------------------------------------------------
Guard: Order Flow Burst Volume Concentration (Herfindahl-Hirschman Index) Guard

Monitors the concentration of executed trade sizes within rolling burst execution windows using the
normalized Herfindahl-Hirschman Index (HHI):
    s_i = V_i / sum_{j=1}^N V_j
    HHI = sum_{i=1}^N s_i^2

In healthy continuous markets where liquidity is supported by multiple diverse independent participants,
trade volume is smoothly distributed across many small-to-medium retail and institutional sizes:
    HHI <= 0.25 (for N >= 10 trades)

When a single dominant institutional whale order, large iceberg fill, or predatory block cross sweeps
the book, a single execution captures the overwhelming bulk of total turnover in the burst window:
    HHI >= MAX_HHI (default: 0.50)

In this highly concentrated regime, counter-party diversity is non-existent. A single massive participant
is monopolizing price discovery and liquidity extraction, subjecting limit scalpers to extreme
unilateral adverse selection.

When volume concentration exceeds MAX_HHI, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s) until diversified multi-participant liquidity resumes.

Logic:
- Ingests trade execution volumes (volume > 0.0).
- Maintains a rolling window of WINDOW_SIZE = 20 trade volumes.
- Requires at least MIN_SAMPLES = 10 trade volumes before evaluation.
- Computes trade volume shares s_i = V_i / V_total and Herfindahl index HHI = sum(s_i^2).
- If HHI >= MAX_HHI (0.50):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(volume, ts=None)                            -> None
  update(volume, ts=None)                                  -> None   (alias)
  get_hhi()                                                -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_HHI: float = 0.50                 # HHI >= 0.50 indicates severe whale volume concentration
WINDOW_SIZE: int = 20                 # Rolling window of trade volumes
MIN_SAMPLES: int = 10                 # Minimum trade samples before evaluating HHI
COOLDOWN_SECONDS: float = 45.0        # Block duration on volume concentration surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_hhi: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(volume, ts=None) -> None:
    """Record an executed trade volume and evaluate Herfindahl volume concentration."""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return

    v = float(volume)

    global _latest_hhi, _blocked_until
    with _lock:
        _volumes.append(v)

        if len(_volumes) < MIN_SAMPLES:
            return

        total_vol = sum(_volumes)
        if total_vol <= 0.0:
            return

        hhi = sum((x / total_vol) ** 2 for x in _volumes)
        _latest_hhi = hhi

        if hhi >= MAX_HHI:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if whale volume concentration has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_hhi() -> float:
    """Return the most recently computed Herfindahl-Hirschman volume concentration index."""
    with _lock:
        return _latest_hhi


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the volume concentration guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "hhi": _latest_hhi,
            "sample_count": len(_volumes),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_hhi_threshold": MAX_HHI,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset volume history, HHI metrics, and active blocks."""
    global _latest_hhi, _blocked_until
    with _lock:
        _volumes.clear()
        _latest_hhi = 0.0
        _blocked_until = 0.0
