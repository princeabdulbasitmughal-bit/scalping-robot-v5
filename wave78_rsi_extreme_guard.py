"""
wave78_rsi_extreme_guard.py
---------------------------
Blocks entry when RSI-14 is in extreme overbought (> 80) or oversold (< 20)
territory, avoiding chasing exhausted price moves.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed on insufficient data or corrupted inputs
- time.monotonic() for cooldown timer
- Warmup: requires period+1 prices before blocking is active
"""

import math
import threading
import time

_lock = threading.RLock()

# RSI parameters
_period = 14
_overbought = 80.0
_oversold = 20.0
_cooldown_sec = 60.0

# Rolling state
_prices = []          # list of close prices
_avg_gain = None      # Wilder's smoothed average gain
_avg_loss = None      # Wilder's smoothed average loss
_rsi = None           # last computed RSI value
_blocked_until = 0.0  # monotonic timestamp


def _is_valid_price(v):
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def update(close: float) -> None:
    """Feed a new close price and update RSI state."""
    global _avg_gain, _avg_loss, _rsi, _blocked_until

    if not _is_valid_price(close):
        return

    with _lock:
        _prices.append(float(close))

        # Need period+1 prices for the first SMA seed
        if len(_prices) < _period + 1:
            return

        if _avg_gain is None:
            # Seed: simple average of first `_period` changes
            changes = [_prices[i] - _prices[i - 1] for i in range(1, _period + 1)]
            gains = [max(0.0, c) for c in changes]
            losses = [max(0.0, -c) for c in changes]
            _avg_gain = sum(gains) / _period
            _avg_loss = sum(losses) / _period
        else:
            change = _prices[-1] - _prices[-2]
            gain = max(0.0, change)
            loss = max(0.0, -change)
            # Wilder's smoothing: alpha = 1/period
            alpha = 1.0 / _period
            _avg_gain = (1 - alpha) * _avg_gain + alpha * gain
            _avg_loss = (1 - alpha) * _avg_loss + alpha * loss

        if _avg_loss == 0.0:
            _rsi = 100.0
        else:
            rs = _avg_gain / _avg_loss
            _rsi = 100.0 - (100.0 / (1.0 + rs))

        # Trigger cooldown on extreme RSI
        if _rsi > _overbought or _rsi < _oversold:
            _blocked_until = time.monotonic() + _cooldown_sec


def is_entry_blocked() -> bool:
    """Return True if RSI is extreme (overbought/oversold) and cooldown active."""
    with _lock:
        # Warmup: not enough data yet -> fail-closed
        if _avg_gain is None:
            return True
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_rsi() -> float:
    """Return last RSI value or -1.0 if not yet computed."""
    with _lock:
        return _rsi if _rsi is not None else -1.0


def reset() -> None:
    """Reset all state (e.g. on new trading session)."""
    global _prices, _avg_gain, _avg_loss, _rsi, _blocked_until
    with _lock:
        _prices = []
        _avg_gain = None
        _avg_loss = None
        _rsi = None
        _blocked_until = 0.0
