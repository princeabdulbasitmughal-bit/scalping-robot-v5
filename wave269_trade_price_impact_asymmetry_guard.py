"""
wave269_trade_price_impact_asymmetry_guard.py
----------------------------------------------
Guard: Trade Price Impact Asymmetry & Adverse Selection Drift Guard

Monitors directional disparity in post-trade price impact between buyer-initiated and seller-initiated trades
(Glosten & Milgrom 1985; Hasbrouck 1991; Bouchaud et al. 2009):
    Trade Impact (bps):         I_k = (|P_{post} - P_k| / P_k) * 10^4
    Mean Buy / Sell Impact:     \\bar{I}_{buy}, \\bar{I}_{sell} over rolling N=15 trades each
    Combined Mean Impact:       \\bar{I}_{comb} = (\\bar{I}_{buy} + \\bar{I}_{sell}) / 2.0
    Impact Asymmetry Ratio:     A_{impact} = |\\bar{I}_{buy} - \\bar{I}_{sell}| / (\\bar{I}_{buy} + \\bar{I}_{sell} + 10^{-4})

Under balanced, symmetrical continuous double-auction conditions:
    - Price response to buy and sell market orders is roughly equivalent: A_{impact} <= 0.35.
    - Market makers price bilateral inventory risk symmetrically without adverse skew.

During informed toxic trading, aggressive directional sweeping, or one-sided price runs:
    - One side produces overwhelming permanent price displacement while the opposite side creates near-zero impact:
        1) Severe Price Impact Asymmetry Persistence:
           A_{impact} >= MAX_IMPACT_ASYMMETRY (default: 0.70) with \\bar{I}_{comb} >= MIN_COMBINED_IMPACT_BPS (2.00 bps)
           over total samples N >= MIN_TOTAL_SAMPLES (12 trades).
        2) Acute Single-Sided Impact Shock:
           Single trade impact I_k >= ACUTE_IMPACT_BPS (default: 4.50 bps).

Trading against extreme price impact asymmetry guarantees severe adverse selection, wide fills,
and immediate negative markouts.

When severe impact asymmetry or an acute impact shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade impact via record_trade_impact(sign, impact_bps, ts=None) or
  direct asymmetry via record_asymmetry(asymmetry_ratio, mean_impact_bps=None, sample_count=None, ts=None).
- Maintains separate rolling histories of buy and sell trade impacts (WINDOW_SIZE = 15 each).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive impacts, or zero signs are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_impact(sign, impact_bps, ts=None)                                               -> None
  record_asymmetry(asymmetry_ratio, mean_impact_bps=None, sample_count=None, ts=None)          -> None
  update(sign, impact_bps=None, ts=None)                                                       -> None   (alias)
  get_impact_metrics()                                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 15                   # 15 trade impacts per side
MIN_TOTAL_SAMPLES: int = 12             # 12 total trade impacts minimum for asymmetry evaluation
MAX_IMPACT_ASYMMETRY: float = 0.70      # 70% impact asymmetry threshold
MIN_COMBINED_IMPACT_BPS: float = 2.00   # 2.00 bps minimum combined impact
ACUTE_IMPACT_BPS: float = 4.50          # 4.50 bps acute single-trade impact threshold
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_buy_impacts: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_sell_impacts: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_asymmetry: float = 0.0
_latest_combined_impact: float = 1.0
_latest_single_impact: float = 0.0
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
    """Validate value is a finite numeric float or int (not bool)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_asymmetry(
    asymmetry_ratio: float,
    mean_impact_bps: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed impact asymmetry ratio and mean impact.
    """
    global _latest_asymmetry, _latest_combined_impact, _blocked_until

    if not _is_valid_numeric(asymmetry_ratio):
        return

    a = max(0.0, min(1.0, float(asymmetry_ratio)))
    m = float(mean_impact_bps) if (mean_impact_bps is not None and _is_valid_positive(mean_impact_bps)) else 2.5
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 15

    with _lock:
        _latest_asymmetry = a
        _latest_combined_impact = m

        # Condition 1: Severe Price Impact Asymmetry Persistence
        if a >= MAX_IMPACT_ASYMMETRY and m >= MIN_COMBINED_IMPACT_BPS and n >= MIN_TOTAL_SAMPLES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade_impact(
    sign: int,
    impact_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade sign (+1 buy, -1 sell) and its observed price impact in basis points.
    """
    global _latest_single_impact, _latest_asymmetry, _latest_combined_impact, _blocked_until

    if not (_is_valid_numeric(sign) and _is_valid_positive(impact_bps)):
        return

    s_val = int(sign)
    if s_val == 0:
        return
    is_buy = s_val > 0
    imp = float(impact_bps)

    with _lock:
        _latest_single_impact = imp

        # Condition 2: Acute Single-Sided Impact Shock
        if imp >= ACUTE_IMPACT_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            if is_buy:
                _buy_impacts.append(imp)
            else:
                _sell_impacts.append(imp)
            return

        if is_buy:
            _buy_impacts.append(imp)
        else:
            _sell_impacts.append(imp)

        total_samples = len(_buy_impacts) + len(_sell_impacts)
        if total_samples >= MIN_TOTAL_SAMPLES and len(_buy_impacts) >= 3 and len(_sell_impacts) >= 3:
            mean_buy = statistics.mean(_buy_impacts)
            mean_sell = statistics.mean(_sell_impacts)
            comb = (mean_buy + mean_sell) / 2.0
            asym = abs(mean_buy - mean_sell) / (mean_buy + mean_sell + 1e-4)

            _latest_combined_impact = comb
            _latest_asymmetry = asym

            # Condition 1: Severe Price Impact Asymmetry Persistence
            if asym >= MAX_IMPACT_ASYMMETRY and comb >= MIN_COMBINED_IMPACT_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    sign: int,
    impact_bps: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_trade_impact or record_asymmetry."""
    if impact_bps is None:
        record_asymmetry(sign, ts=ts)
    else:
        record_trade_impact(sign, impact_bps, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by price impact asymmetry guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_impact_metrics() -> Dict[str, Any]:
    """Return dictionary of current price impact metrics."""
    with _lock:
        mean_buy = statistics.mean(_buy_impacts) if _buy_impacts else 0.0
        mean_sell = statistics.mean(_sell_impacts) if _sell_impacts else 0.0
        return {
            "asymmetry_ratio": round(_latest_asymmetry, 4),
            "combined_impact_bps": round(_latest_combined_impact, 4),
            "mean_buy_impact": round(mean_buy, 4),
            "mean_sell_impact": round(mean_sell, 4),
            "buy_samples": len(_buy_impacts),
            "sell_samples": len(_sell_impacts),
            "max_impact_asymmetry": MAX_IMPACT_ASYMMETRY,
            "min_combined_impact_bps": MIN_COMBINED_IMPACT_BPS,
            "acute_impact_bps": ACUTE_IMPACT_BPS,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_impact_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _buy_impacts, _sell_impacts, _latest_asymmetry
    global _latest_combined_impact, _latest_single_impact, _blocked_until
    with _lock:
        _buy_impacts.clear()
        _sell_impacts.clear()
        _latest_asymmetry = 0.0
        _latest_combined_impact = 1.0
        _latest_single_impact = 0.0
        _blocked_until = 0.0
