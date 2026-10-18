"""
Wave 59: MA Trend Filter
==========================
Computes Exponential Moving Average (EMA-50) on live tick prices.
Enforces trend alignment:
  - Only take BUY signals when price > EMA50
  - Only take SELL signals when price < EMA50
Signals that go against the EMA trend are blocked.

API:
    ma_trend_filter.update(price: float)
    ma_trend_filter.is_signal_blocked(signal: str) -> BlockResult   signal="BUY"|"SELL"
    ma_trend_filter.get_ema() -> float
    ma_trend_filter.info() -> dict
"""

import math
import logging
import threading
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_EMA_PERIOD = 50
_EMA_ALPHA = 2.0 / (_EMA_PERIOD + 1)


class BlockResult(int):
    """
    Subscriptable result object that behaves as:
    - bool: `if res:` evaluates to `blocked`
    - tuple: `res[0]` is blocked (bool), `res[1]` is reason (str)
    - iterator: `blocked, reason = res`
    - int: `int(res)` is 1 if blocked else 0
    """
    def __new__(cls, blocked: bool, reason: str = ""):
        obj = super().__new__(cls, 1 if blocked else 0)
        obj.blocked = bool(blocked)
        obj.reason = str(reason)
        return obj

    def __iter__(self):
        yield self.blocked
        yield self.reason

    def __getitem__(self, index):
        if index == 0:
            return self.blocked
        elif index == 1:
            return self.reason
        raise IndexError(f"BlockResult index out of range: {index}")

    def __bool__(self):
        return self.blocked

    def __repr__(self):
        return f"BlockResult({self.blocked}, '{self.reason}')"


class MATrendFilter:
    """
    EMA-50 trend alignment filter.
    Warm-up: first `period` ticks are used to initialise the EMA (SMA seed),
    no blocks are issued during warm-up.
    Thread-safe with RLock and fully subscriptable BlockResult.
    """

    def __init__(self, period: int = _EMA_PERIOD):
        try:
            p = int(period)
            self.period = p if p >= 2 else _EMA_PERIOD
        except (ValueError, TypeError):
            self.period = _EMA_PERIOD

        self.alpha = 2.0 / (self.period + 1)
        self._ema: float = 0.0
        self._tick_count: int = 0
        self._seed_prices: list[float] = []
        self._warmed_up: bool = False
        self._last_price: float = 0.0
        self._total_blocks: int = 0
        self._lock = threading.RLock()

    @property
    def is_warmed_up(self) -> bool:
        """True if EMA has been seeded with period ticks."""
        with self._lock:
            return self._warmed_up

    def reset(self) -> None:
        """Thread-safe reset of internal filter state."""
        with self._lock:
            self._ema = 0.0
            self._tick_count = 0
            self._seed_prices.clear()
            self._warmed_up = False
            self._last_price = 0.0
            self._total_blocks = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def update(self, price: Any) -> None:
        """Feed each tick price."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        try:
            with self._lock:
                self._last_price = p
                self._tick_count += 1

                if not self._warmed_up:
                    self._seed_prices.append(p)
                    if len(self._seed_prices) >= self.period:
                        # Seed EMA with SMA of first `period` prices
                        self._ema = sum(self._seed_prices) / len(self._seed_prices)
                        self._warmed_up = True
                        self._seed_prices.clear()  # free memory
                else:
                    self.alpha = 2.0 / (self.period + 1)
                    self._ema = self.alpha * p + (1 - self.alpha) * self._ema
        except Exception as exc:
            logger.debug(f"[WAVE59] update error: {exc}")

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def get_ema(self) -> float:
        with self._lock:
            return round(self._ema, 4)

    def is_signal_blocked(self, signal: Any, price: Optional[float] = None) -> BlockResult:
        """
        Returns BlockResult (behaves as both bool, 2-tuple, and subscriptable [0]/[1]).
        During warm-up period (<period ticks), never blocks.
        """
        try:
            sig = str(signal).strip().upper() if signal is not None else ""
            if sig not in ("BUY", "SELL"):
                return BlockResult(False, "non_directional_signal")

            with self._lock:
                if not self._warmed_up or self._ema <= 0.0:
                    return BlockResult(False, "warmup_or_zero_ema")

                current_p = float(price) if price is not None and math.isfinite(float(price)) and float(price) > 0 else self._last_price
                ema = self._ema

            if sig == "BUY" and current_p < ema:
                with self._lock:
                    self._total_blocks += 1
                logger.info(
                    f"[WAVE59] MA TREND BLOCK: BUY rejected — price {current_p:.3f} "
                    f"< EMA50 {ema:.3f} (bearish trend)"
                )
                return BlockResult(True, "price_below_ema")

            if sig == "SELL" and current_p > ema:
                with self._lock:
                    self._total_blocks += 1
                logger.info(
                    f"[WAVE59] MA TREND BLOCK: SELL rejected — price {current_p:.3f} "
                    f"> EMA50 {ema:.3f} (bullish trend)"
                )
                return BlockResult(True, "price_above_ema")

            return BlockResult(False, "trend_aligned")
        except Exception as exc:
            logger.debug(f"[WAVE59] is_signal_blocked error: {exc}")
            return BlockResult(True, f"error:{exc}")  # fail-closed

    def is_entry_blocked(self, signal: Any, price: Optional[float] = None) -> bool:
        """Boolean alias for is_signal_blocked."""
        return bool(self.is_signal_blocked(signal, price=price))

    def is_blocked(self, signal: Any, price: Optional[float] = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(signal, price=price)

    def is_trading_allowed(self, signal: Any, price: Optional[float] = None) -> Tuple[bool, str]:
        """Returns (allowed: bool, reason: str)."""
        res = self.is_signal_blocked(signal, price=price)
        return (not res.blocked, "" if not res.blocked else res.reason)

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            with self._lock:
                warmed = self._warmed_up
                ema = self._ema
                price = self._last_price
                tick_count = self._tick_count
                total_blocks = self._total_blocks
            trend = "NEUTRAL"
            if warmed and ema > 0:
                trend = "BULLISH" if price > ema else "BEARISH"
            return {
                "wave": 59,
                "name": "MATrendFilter",
                "period": self.period,
                "ema50": round(ema, 3) if ema > 0 else None,
                "last_price": round(price, 3) if price > 0 else None,
                "trend": trend,
                "warmed_up": warmed,
                "tick_count": tick_count,
                "total_blocks": total_blocks,
            }
        except Exception:
            return {"wave": 59, "name": "MATrendFilter", "error": "info_failed"}


# Module-level singleton
ma_trend_filter = MATrendFilter()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(signal: Any, price: Optional[float] = None) -> bool:
    return ma_trend_filter.is_entry_blocked(signal, price=price)

def is_blocked(signal: Any, price: Optional[float] = None) -> bool:
    return ma_trend_filter.is_blocked(signal, price=price)

def update(price: Any) -> None:
    ma_trend_filter.update(price)

def get_ema() -> float:
    return ma_trend_filter.get_ema()

def reset() -> None:
    ma_trend_filter.reset()
