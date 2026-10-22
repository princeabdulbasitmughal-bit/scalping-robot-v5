"""
wave271_trade_vwap_slippage_drift_guard.py
------------------------------------------
Guard: Execution VWAP vs Midpoint Execution Drift & Slippage Escalation Guard

Monitors institutional execution slippage, VWAP arrival displacement, and broker fill degradation
(Berkowitz, Logue & Noser 1988; Almgren & Chriss 2000; Kissell 2013):
    Fill Slippage (bps):        S_{fill} = (|P_{exec} - P_{mid}| / P_{mid}) * 10^4
    Volume-Weighted Slippage:   S_{VWAP} = sum(S_i * v_i) / sum(v_i) over rolling N=15 execution fills
    Acute Single-Fill Blowout:  S_{fill} >= ACUTE_SLIPPAGE_BPS (5.00 bps)

Under optimal liquidity routing and competitive ECN execution:
    - Limit/market fills execute closely around prevailing midquote (S_{VWAP} <= 1.20 bps).
    - Execution friction is tightly controlled within expected half-spread parameters.

During broker routing degradation, hidden queue depletion, or predatory adverse selection:
    - Executions experience severe, persistent slippage penalties:
        1) Elevated Mean VWAP Slippage Persistence:
           S_{VWAP} >= MAX_MEAN_SLIPPAGE_BPS (default: 2.50 bps) over rolling N >= MIN_FILLS (10 fills).
        2) Acute Single-Fill Slippage Blowout:
           S_{fill} >= ACUTE_SLIPPAGE_BPS (default: 5.00 bps).

Continuing to trade during severe execution slippage rapidly destroys scalping edge and guarantees
catastrophic negative execution expectancy.

When elevated VWAP slippage or an acute slippage blowout is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests executions via record_execution(exec_price, mid_price, volume=1.0, ts=None) or
  direct slippage via record_slippage(slippage_bps, volume=1.0, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 execution fills.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices/volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_execution(exec_price, mid_price, volume=1.0, ts=None)                                 -> None
  record_slippage(slippage_bps, volume=1.0, ts=None)                                           -> None
  update(exec_price, mid_price=None, volume=1.0, ts=None)                                      -> None   (alias)
  get_slippage_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 15                   # 15 execution fills rolling window
MIN_FILLS: int = 10                     # 10 fills minimum for rolling VWAP slippage
MAX_MEAN_SLIPPAGE_BPS: float = 2.50     # 2.50 bps maximum acceptable mean slippage
ACUTE_SLIPPAGE_BPS: float = 5.00        # 5.00 bps acute single-fill slippage blowout
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_fills_history: Deque[Tuple[float, float]] = collections.deque(maxlen=WINDOW_SIZE)  # (slippage_bps, volume)
_latest_single_slippage_bps: float = 0.0
_latest_mean_slippage_bps: float = 0.50
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_slippage(
    slippage_bps: float,
    volume: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed fill slippage in basis points and trade volume.
    """
    global _latest_single_slippage_bps, _latest_mean_slippage_bps, _blocked_until

    if not (_is_valid_numeric(slippage_bps) and _is_valid_positive(volume)):
        return

    s = max(0.0, float(slippage_bps))
    v = float(volume)

    with _lock:
        _latest_single_slippage_bps = s

        # Condition 2: Acute Single-Fill Slippage Blowout
        if s >= ACUTE_SLIPPAGE_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _fills_history.append((s, v))
            return

        _fills_history.append((s, v))

        if len(_fills_history) >= MIN_FILLS:
            total_vol = sum(vol for _, vol in _fills_history)
            if total_vol > 0.0:
                vwap_slip = sum(slip * vol for slip, vol in _fills_history) / total_vol
                _latest_mean_slippage_bps = vwap_slip

                # Condition 1: Elevated Mean VWAP Slippage Persistence
                if vwap_slip >= MAX_MEAN_SLIPPAGE_BPS:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def record_execution(
    exec_price: float,
    mid_price: float,
    volume: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest executed fill price and decision midquote, calculate basis point slippage.
    """
    if not (_is_valid_positive(exec_price) and _is_valid_positive(mid_price) and _is_valid_positive(volume)):
        return

    ep = float(exec_price)
    mp = float(mid_price)
    vol = float(volume)

    if mp <= 0.0:
        return

    slippage_bps = (abs(ep - mp) / mp) * 10000.0
    record_slippage(slippage_bps, volume=vol, ts=ts)


def update(
    exec_price: float,
    mid_price: Optional[float] = None,
    volume: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_execution or record_slippage."""
    if mid_price is None:
        record_slippage(exec_price, volume=volume, ts=ts)
    else:
        record_execution(exec_price, mid_price, volume=volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by VWAP slippage guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_slippage_metrics() -> Dict[str, Any]:
    """Return dictionary of current slippage metrics."""
    with _lock:
        return {
            "latest_single_slippage_bps": round(_latest_single_slippage_bps, 4),
            "latest_mean_slippage_bps": round(_latest_mean_slippage_bps, 4),
            "sample_count": len(_fills_history),
            "max_mean_slippage_bps": MAX_MEAN_SLIPPAGE_BPS,
            "acute_slippage_bps": ACUTE_SLIPPAGE_BPS,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_slippage_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _fills_history, _latest_single_slippage_bps, _latest_mean_slippage_bps, _blocked_until
    with _lock:
        _fills_history.clear()
        _latest_single_slippage_bps = 0.0
        _latest_mean_slippage_bps = 0.50
        _blocked_until = 0.0
