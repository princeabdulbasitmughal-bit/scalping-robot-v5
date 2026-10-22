"""
wave221_fill_latency_sniping_compression_guard.py
---------------------------------------------------
Guard: Fill Latency Sniping & High-Frequency Latency Compression Guard

Monitors execution latency compression and adverse fill timing (Biais, Foucault & Moinas 2015;
Budish, Cramton & Shim 2015) to detect aggressive HFT sniping and stale-quote exploitation:
    Execution Latency:     tau_{exec} (ms from submission/update to fill)
    Sniped Fill Threshold: tau_{exec} <= 35.0 ms
    Sniped Fill Ratio:     R_{sniped} = N(tau <= 35 ms) / N in rolling 20 executions
    Mean Fill Latency:     tau_{bar} = mean(tau_{1..N})

In normal retail or institutional algorithmic execution:
    - Order execution latencies exhibit natural variance across network jitter and processing queues:
      tau_{bar} >= 80 - 150 ms, with R_{sniped} < 0.25.

During toxic sniping regimes (adverse selection arms race):
    - Sub-millisecond and ultra-fast colocation algorithms target resting quotes the instant
      correlated signals move elsewhere, yielding compressed, hyper-fast fills before cancellation
      messages can arrive:
        1) Latency Compression Shock:
           R_{sniped} >= MAX_SNIPED_FILL_RATIO (default: 0.60 or 60% of fills sniped in <= 35ms) AND
           tau_{bar} <= MAX_MEAN_LATENCY_MS (default: 50.0 ms).
        2) Ultra-Fast Snipe Burst:
           Burst of >= 4 fills with tau_{exec} <= 15.0 ms within <= 2.0 seconds.

Executing new scalping entries while latency arbitrageurs are actively sniping fills results in
systematic execution against adverse market moves and severe negative alpha.

When fill latency compression / sniping is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests fill latency via record_execution_latency(latency_ms, ts=None)
  or record_fill(order_id, latency_ms, slippage_bps=0.0, ts=None).
- Maintains rolling window of WINDOW_SIZE = 20 execution latencies.
- Requires MIN_SAMPLES = 10 fills before evaluating sniped fill ratio.
- Evaluates sniped fill ratio R_{sniped}, mean latency, and 2.0s rapid snipe bursts.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative latencies are rejected.

Aliases (required):
  is_entry_blocked()                                                  -> bool
  is_blocked()                                                        -> bool   (alias)
  record_execution_latency(latency_ms, ts=None)                       -> None
  record_fill(order_id, latency_ms, slippage_bps=0.0, ts=None)        -> None
  update(latency_ms, ts=None)                                         -> None   (alias)
  get_latency_metrics()                                               -> dict
  get_status()                                                        -> dict
  reset()                                                             -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 10
SNIPE_LATENCY_THRESHOLD_MS: float = 35.0  # <= 35 ms indicates high-speed snipe fill
MAX_SNIPED_FILL_RATIO: float = 0.60       # 60% of rolling fills sniped
MAX_MEAN_LATENCY_MS: float = 50.0         # 50 ms mean execution latency
BURST_WINDOW_SEC: float = 2.0             # 2.0 seconds rapid burst window
BURST_SNIPE_THRESHOLD_MS: float = 15.0    # <= 15 ms ultra-fast snipe
BURST_SNIPE_COUNT: int = 4                # 4 ultra-fast snipes in <= 2.0s triggers burst block
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latencies = collections.deque(maxlen=WINDOW_SIZE)
_burst_events = collections.deque()       # (ts, latency_ms)
_latest_mean_latency_ms: float = 100.0
_latest_sniped_ratio: float = 0.0
_latest_burst_snipes: int = 0
_blocked_until: float = 0.0


def _is_valid_latency(val: Any) -> bool:
    """Validate latency is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _prune_burst_events(now: float) -> None:
    """Remove burst events older than BURST_WINDOW_SEC."""
    cutoff = now - BURST_WINDOW_SEC
    while _burst_events and _burst_events[0][0] < cutoff:
        _burst_events.popleft()


def record_execution_latency(
    latency_ms: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest an execution fill latency measurement and evaluate sniping compression.
    """
    global _latest_mean_latency_ms, _latest_sniped_ratio, _latest_burst_snipes, _blocked_until

    if not _is_valid_latency(latency_ms):
        return

    lat = float(latency_ms)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        _latencies.append(lat)
        _burst_events.append((now, lat))
        _prune_burst_events(now)

        # Check Burst Condition (last 2.0s)
        burst_snipes = sum(1 for e in _burst_events if e[1] <= BURST_SNIPE_THRESHOLD_MS)
        _latest_burst_snipes = burst_snipes
        if burst_snipes >= BURST_SNIPE_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        n = len(_latencies)
        if n < MIN_SAMPLES:
            return

        mean_lat = sum(_latencies) / float(n)
        sniped_count = sum(1 for l in _latencies if l <= SNIPE_LATENCY_THRESHOLD_MS)
        sniped_ratio = sniped_count / float(n)

        _latest_mean_latency_ms = mean_lat
        _latest_sniped_ratio = sniped_ratio

        # Check Ratio & Mean Latency Condition
        if sniped_ratio >= MAX_SNIPED_FILL_RATIO and mean_lat <= MAX_MEAN_LATENCY_MS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_fill(
    order_id: str,
    latency_ms: float,
    slippage_bps: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """
    Record fill event with order ID, latency, and optional slippage.
    """
    record_execution_latency(latency_ms, ts)


def update(latency_ms: float, ts: Optional[float] = None) -> None:
    """Alias for record_execution_latency()."""
    record_execution_latency(latency_ms, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to fill latency compression."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_latency_metrics() -> Dict[str, float]:
    """Return latest calculated mean latency and sniped fill ratio."""
    with _lock:
        return {
            "mean_latency_ms": _latest_mean_latency_ms,
            "sniped_fill_ratio": _latest_sniped_ratio,
            "burst_snipes": float(_latest_burst_snipes),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the fill latency sniping guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_latency_ms": _latest_mean_latency_ms,
            "sniped_fill_ratio": _latest_sniped_ratio,
            "burst_snipes": _latest_burst_snipes,
            "sample_count": len(_latencies),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "snipe_latency_threshold_ms": SNIPE_LATENCY_THRESHOLD_MS,
            "max_sniped_fill_ratio": MAX_SNIPED_FILL_RATIO,
            "max_mean_latency_ms": MAX_MEAN_LATENCY_MS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset execution latency history, burst events, metrics, and active cooldown blocks."""
    global _latest_mean_latency_ms, _latest_sniped_ratio, _latest_burst_snipes, _blocked_until
    with _lock:
        _latencies.clear()
        _burst_events.clear()
        _latest_mean_latency_ms = 100.0
        _latest_sniped_ratio = 0.0
        _latest_burst_snipes = 0
        _blocked_until = 0.0
