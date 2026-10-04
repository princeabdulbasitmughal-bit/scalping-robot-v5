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
    ma_trend_filter.is_signal_blocked(signal: str) -> bool   signal="BUY"|"SELL"
    ma_trend_filter.get_ema() -> float
    ma_trend_filter.info() -> dict
"""

import logging

logger = logging.getLogger(__name__)

_EMA_PERIOD = 50
_EMA_ALPHA = 2.0 / (_EMA_PERIOD + 1)


class MATrendFilter:
    """
    EMA-50 trend alignment filter.
    Warm-up: first 50 ticks are used to initialise the EMA (SMA seed),
    no blocks are issued during warm-up.
    """

    def __init__(self, period: int = _EMA_PERIOD):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self._ema: float = 0.0
        self._tick_count: int = 0
        self._seed_prices: list = []
        self._warmed_up: bool = False
        self._last_price: float = 0.0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def update(self, price: float) -> None:
        """Feed each tick price."""
        try:
            self._last_price = price
            self._tick_count += 1

            if not self._warmed_up:
                self._seed_prices.append(price)
                if len(self._seed_prices) >= self.period:
                    # Seed EMA with SMA of first `period` prices
                    self._ema = sum(self._seed_prices) / len(self._seed_prices)
                    self._warmed_up = True
                    self._seed_prices = []  # free memory
            else:
                self._ema = self.alpha * price + (1 - self.alpha) * self._ema
        except Exception as exc:
            logger.debug(f"[WAVE59] update error: {exc}")

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def get_ema(self) -> float:
        return self._ema

class BlockResult(int):
    def __new__(cls, blocked: bool, reason: str = ""):
        obj = super().__new__(cls, 1 if blocked else 0)
        obj.blocked = bool(blocked)
        obj.reason = reason
        return obj

    def __iter__(self):
        yield self.blocked
        yield self.reason

    def __bool__(self):
        return self.blocked

    def __repr__(self):
        return f"BlockResult({self.blocked}, '{self.reason}')"


    def is_signal_blocked(self, signal: str):
        """
        Returns BlockResult (behaves as both bool and (blocked, reason) tuple).
        During warm-up period (<50 ticks), never blocks.
        """
        try:
            if not self._warmed_up or self._ema == 0.0:
                return BlockResult(False, "warmup_or_zero_ema")

            price = self._last_price
            ema = self._ema

            if signal == "BUY" and price < ema:
                logger.info(
                    f"[WAVE59] MA TREND BLOCK: BUY rejected — price {price:.3f} "
                    f"< EMA50 {ema:.3f} (bearish trend)"
                )
                return BlockResult(True, "price_below_ema")
            if signal == "SELL" and price > ema:
                logger.info(
                    f"[WAVE59] MA TREND BLOCK: SELL rejected — price {price:.3f} "
                    f"> EMA50 {ema:.3f} (bullish trend)"
                )
                return BlockResult(True, "price_above_ema")
            return BlockResult(False, "trend_aligned")
        except Exception as exc:
            logger.debug(f"[WAVE59] is_signal_blocked error: {exc}")
            return BlockResult(False, f"error:{exc}")

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            trend = "NEUTRAL"
            if self._warmed_up and self._ema > 0:
                trend = "BULLISH" if self._last_price > self._ema else "BEARISH"
            return {
                "wave": 59,
                "name": "MATrendFilter",
                "ema50": round(self._ema, 3) if self._ema else None,
                "last_price": round(self._last_price, 3),
                "trend": trend,
                "warmed_up": self._warmed_up,
                "tick_count": self._tick_count,
            }
        except Exception:
            return {"wave": 59, "error": "info_failed"}


# Module-level singleton
ma_trend_filter = MATrendFilter()
