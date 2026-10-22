"""
wave261_trade_clustering_dispersion_entropy_guard.py
----------------------------------------------------
Guard: Trade Arrival Dispersion & Shannon Entropy Guard

Monitors temporal clustering, arrival concentration, and information entropy of high-frequency trade flow
(Shannon 1948; Dacorogna et al. 2001; Boffetta et al. 2002):
    Rolling Window:             W = 20.0 seconds, divided into K = 10 equal bins (Delta t = 2.0s)
    Bin Counts:                 c_k = count(trades in bin k),  N_{total} = sum_{k=1}^K c_k
    Arrival Probabilities:      p_k = c_k / N_{total}
    Shannon Arrival Entropy:    H = - sum_{k: p_k > 0} p_k * ln(p_k)
    Normalized Entropy:         H_{norm} = H / ln(K) in [0.0, 1.0]
    Max Concentration:          p_{max} = max_{k}(p_k)

Under steady Poisson or orderly independent market order arrival:
    - Trades are uniformly distributed across temporal bins: H_{norm} ~ 0.75 - 1.00.
    - No single time bin captures an overwhelming share: p_{max} <= 0.40.

During algorithmic sweeps, predatory stop-loss triggers, or liquidity vacuums:
    - Order flow aggressively concentrates into narrow sub-second bursts:
        1) Temporal Entropy Collapse:
           H_{norm} <= MIN_NORMALIZED_ENTROPY (default: 0.35) with N_{total} >= MIN_TRADES (15 trades).
        2) Acute Single-Bin Concentration:
           p_{max} >= MAX_BIN_CONCENTRATION (default: 0.80) with N_{total} >= ACUTE_MIN_TRADES (10 trades).

Entering trades during temporal entropy collapse guarantees execution into an aggressive predatory
liquidity vacuum.

When entropy collapse or acute concentration is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival timestamps via record_trade(ts=None, volume=1.0) or
  direct metrics via record_entropy(normalized_entropy, max_concentration=None, sample_count=None, ts=None).
- Divides rolling WINDOW_SECONDS = 20.0s into NUM_BINS = 10 bins.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive trade counts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(ts=None, volume=1.0)                                                            -> None
  record_entropy(normalized_entropy, max_concentration=None, sample_count=None, ts=None)        -> None
  update(ts=None, volume=1.0)                                                                  -> None   (alias)
  get_entropy_metrics(now_ts=None)                                                             -> dict
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
WINDOW_SECONDS: float = 20.0            # 20.0s rolling observation window
NUM_BINS: int = 10                      # 10 bins (2.0s per bin)
MIN_TRADES: int = 15                    # 15 trades minimum for entropy evaluation
MIN_NORMALIZED_ENTROPY: float = 0.35    # Normalized entropy <= 0.35 indicates extreme clustering
MAX_BIN_CONCENTRATION: float = 0.80     # 80% of trades in one bin indicates acute burst
ACUTE_MIN_TRADES: int = 10              # 10 trades minimum for acute single-bin trigger
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trades: Deque[Tuple[float, float]] = collections.deque()  # (ts, volume)
_latest_normalized_entropy: float = 1.0
_latest_max_concentration: float = 0.10
_last_trade_ts: Optional[float] = None
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


def _purge_old_trades(now_ts: float) -> None:
    """Remove trades older than WINDOW_SECONDS from the rolling deque."""
    cutoff = now_ts - WINDOW_SECONDS
    while _trades and _trades[0][0] < cutoff:
        _trades.popleft()


def record_entropy(
    normalized_entropy: float,
    max_concentration: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed normalized Shannon entropy and max bin concentration.
    """
    global _latest_normalized_entropy, _latest_max_concentration, _last_trade_ts, _blocked_until

    if not _is_valid_numeric(normalized_entropy):
        return

    h_norm = max(0.0, min(1.0, float(normalized_entropy)))
    conc = float(max_concentration) if (max_concentration is not None and _is_valid_numeric(max_concentration)) else 0.10
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 20
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_normalized_entropy = h_norm
        _latest_max_concentration = conc
        _last_trade_ts = now

        # Condition 2: Acute Single-Bin Concentration
        if conc >= MAX_BIN_CONCENTRATION and n >= ACUTE_MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Temporal Entropy Collapse
        if h_norm <= MIN_NORMALIZED_ENTROPY and n >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade(ts: Optional[float] = None, volume: float = 1.0) -> None:
    """
    Ingest a single trade arrival timestamp and volume, and evaluate temporal entropy.
    """
    global _latest_normalized_entropy, _latest_max_concentration, _last_trade_ts, _blocked_until

    if not _is_valid_positive(volume):
        return

    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _last_trade_ts = now
        _purge_old_trades(now)
        _trades.append((now, float(volume)))

        n_trades = len(_trades)
        if n_trades < ACUTE_MIN_TRADES:
            return

        # Distribute into NUM_BINS temporal bins across [now - WINDOW_SECONDS, now]
        bin_width = WINDOW_SECONDS / float(NUM_BINS)
        bin_counts = [0] * NUM_BINS
        window_start = now - WINDOW_SECONDS

        for t_trade, _ in _trades:
            rel_t = t_trade - window_start
            bin_idx = int(rel_t / bin_width)
            if bin_idx < 0:
                bin_idx = 0
            elif bin_idx >= NUM_BINS:
                bin_idx = NUM_BINS - 1
            bin_counts[bin_idx] += 1

        total_in_bins = sum(bin_counts)
        if total_in_bins == 0:
            return

        max_count = max(bin_counts)
        max_conc = max_count / float(total_in_bins)
        _latest_max_concentration = max_conc

        # Condition 2: Acute Single-Bin Concentration
        if max_conc >= MAX_BIN_CONCENTRATION and total_in_bins >= ACUTE_MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Compute Shannon entropy
        h = 0.0
        for c in bin_counts:
            if c > 0:
                p = c / float(total_in_bins)
                h -= p * math.log(p)

        max_h = math.log(NUM_BINS)
        h_norm = h / max_h if max_h > 0.0 else 1.0
        _latest_normalized_entropy = h_norm

        # Condition 1: Temporal Entropy Collapse
        if h_norm <= MIN_NORMALIZED_ENTROPY and total_in_bins >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(ts: Optional[float] = None, volume: float = 1.0) -> None:
    """Module alias for record_trade."""
    if ts is not None and not _is_valid_numeric(ts):
        return
    record_trade(ts=ts, volume=volume)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by entropy guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_entropy_metrics(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Return dictionary of current entropy and dispersion metrics."""
    with _lock:
        if now_ts is not None and _is_valid_numeric(now_ts):
            now = float(now_ts)
        elif _last_trade_ts is not None and _last_trade_ts < 1_000_000_000.0:
            now = _last_trade_ts
        else:
            now = time.time()
        _purge_old_trades(now)
        return {
            "normalized_entropy": round(_latest_normalized_entropy, 4),
            "max_concentration": round(_latest_max_concentration, 4),
            "trade_count_window": len(_trades),
            "window_seconds": WINDOW_SECONDS,
            "num_bins": NUM_BINS,
            "min_normalized_entropy": MIN_NORMALIZED_ENTROPY,
            "max_bin_concentration": MAX_BIN_CONCENTRATION,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_entropy_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _trades, _latest_normalized_entropy, _latest_max_concentration, _last_trade_ts, _blocked_until
    with _lock:
        _trades.clear()
        _latest_normalized_entropy = 1.0
        _latest_max_concentration = 0.10
        _last_trade_ts = None
        _blocked_until = 0.0
