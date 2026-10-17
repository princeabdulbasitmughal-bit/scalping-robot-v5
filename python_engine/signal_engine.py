"""Technical-indicator based signal generation for the paper/live trader."""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Optional, Sequence


class SignalEngine:
    """Compute Bollinger Bands, Wilder RSI, MACD, EMA and a confluence signal."""

    def __init__(self, config: Optional[dict] = None):
        self.config = dict(config) if config else {}
        self._lock = threading.RLock()
        self.bb_period = max(1, int(self.config.get("bb_period", 20)))
        self.bb_std = float(self.config.get("bb_std", 2.0))
        self.rsi_period = max(1, int(self.config.get("rsi_period", 14)))
        self.macd_fast = max(1, int(self.config.get("macd_fast", 12)))
        self.macd_slow = max(self.macd_fast + 1, int(self.config.get("macd_slow", 26)))
        self.macd_signal = max(1, int(self.config.get("macd_signal", 9)))
        self.ema_fast = max(1, int(self.config.get("ema_fast", 8)))
        self.ema_slow = max(1, int(self.config.get("ema_slow", 21)))

    def update_config(self, new_config: dict) -> None:
        """Thread-safe parameter update."""
        with self._lock:
            if not isinstance(new_config, dict):
                return
            self.config.update(new_config)
            self.bb_period = max(1, int(self.config.get("bb_period", self.bb_period)))
            self.bb_std = float(self.config.get("bb_std", self.bb_std))
            self.rsi_period = max(1, int(self.config.get("rsi_period", self.rsi_period)))
            self.macd_fast = max(1, int(self.config.get("macd_fast", self.macd_fast)))
            self.macd_slow = max(self.macd_fast + 1, int(self.config.get("macd_slow", self.macd_slow)))
            self.macd_signal = max(1, int(self.config.get("macd_signal", self.macd_signal)))
            self.ema_fast = max(1, int(self.config.get("ema_fast", self.ema_fast)))
            self.ema_slow = max(1, int(self.config.get("ema_slow", self.ema_slow)))

    def info(self) -> Dict[str, Any]:
        """Telemetry configuration status."""
        with self._lock:
            return {
                "bb_period": self.bb_period,
                "bb_std": self.bb_std,
                "rsi_period": self.rsi_period,
                "macd_fast": self.macd_fast,
                "macd_slow": self.macd_slow,
                "macd_signal": self.macd_signal,
                "ema_fast": self.ema_fast,
                "ema_slow": self.ema_slow,
            }

    @staticmethod
    def _prices(prices: Sequence[float]) -> List[float]:
        """Return finite numeric prices, raising a useful error for no data."""
        values = [float(price) for price in prices]
        if not values or not all(math.isfinite(price) for price in values):
            raise ValueError("prices must contain at least one finite numeric value")
        return values

    @staticmethod
    def _ema_series(prices: Sequence[float], period: int) -> List[float]:
        """EMA seeded with the first observation, matching common charting APIs."""
        period = max(1, int(period))
        alpha = 2.0 / (period + 1.0)
        result = [float(prices[0])]
        for price in prices[1:]:
            result.append((float(price) * alpha) + (result[-1] * (1.0 - alpha)))
        return result

    def compute_bb(self, prices: list) -> dict:
        values = self._prices(prices)
        period_values = values[-self.bb_period :]
        middle = sum(period_values) / len(period_values)
        variance = sum((price - middle) ** 2 for price in period_values) / len(period_values)
        deviation = math.sqrt(max(0.0, variance))
        upper = middle + (self.bb_std * deviation)
        lower = middle - (self.bb_std * deviation)
        width = (upper - lower) / abs(middle) if middle else 0.0
        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "width": width,
            "squeeze": width < 0.002,
        }

    def compute_rsi(self, prices: list) -> float:
        values = self._prices(prices)
        if len(values) <= self.rsi_period:
            return 50.0

        changes = [values[index] - values[index - 1] for index in range(1, len(values))]
        gains = [max(change, 0.0) for change in changes]
        losses = [max(-change, 0.0) for change in changes]
        avg_gain = sum(gains[: self.rsi_period]) / self.rsi_period
        avg_loss = sum(losses[: self.rsi_period]) / self.rsi_period
        for gain, loss in zip(gains[self.rsi_period :], losses[self.rsi_period :]):
            avg_gain = ((avg_gain * (self.rsi_period - 1)) + gain) / self.rsi_period
            avg_loss = ((avg_loss * (self.rsi_period - 1)) + loss) / self.rsi_period

        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0
        if avg_gain == 0.0:
            return 0.0
        relative_strength = avg_gain / avg_loss
        return max(0.0, min(100.0, 100.0 - (100.0 / (1.0 + relative_strength))))

    def compute_macd(self, prices: list) -> dict:
        values = self._prices(prices)
        fast_series = self._ema_series(values, self.macd_fast)
        slow_series = self._ema_series(values, self.macd_slow)
        macd_series = [fast - slow for fast, slow in zip(fast_series, slow_series)]
        signal_series = self._ema_series(macd_series, self.macd_signal)
        macd_line = macd_series[-1]
        signal_line = signal_series[-1]
        histogram = macd_line - signal_line
        cross = "NONE"
        if len(macd_series) >= 2:
            previous_difference = macd_series[-2] - signal_series[-2]
            current_difference = macd_line - signal_line
            if previous_difference <= 0.0 < current_difference:
                cross = "BUY"
            elif previous_difference >= 0.0 > current_difference:
                cross = "SELL"
        return {
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
            "cross": cross,
        }

    def compute_ema(self, prices: list, period: int) -> float:
        values = self._prices(prices)
        return self._ema_series(values, max(1, int(period)))[-1]

    def get_signal(self, prices: list) -> dict:
        """Return a deterministic confluence signal and its indicator diagnostics."""
        values = self._prices(prices)
        bb = self.compute_bb(values)
        rsi = self.compute_rsi(values)
        macd = self.compute_macd(values)
        fast_ema = self.compute_ema(values, self.ema_fast)
        slow_ema = self.compute_ema(values, self.ema_slow)
        current_price = values[-1]
        buy_score = 0
        sell_score = 0
        reasons: List[str] = []

        if current_price <= bb["lower"] and rsi < 35.0:
            buy_score += 2
            reasons.append("price at/below lower Bollinger Band with RSI below 35")
        if current_price >= bb["upper"] and rsi > 65.0:
            sell_score += 2
            reasons.append("price at/above upper Bollinger Band with RSI above 65")
        if bb["squeeze"]:
            reasons.append("Bollinger Band squeeze detected")

        if macd["cross"] == "BUY" and macd["histogram"] > 0.0:
            buy_score += 1
            reasons.append("MACD crossed BUY with positive histogram")
        elif macd["cross"] == "SELL" and macd["histogram"] < 0.0:
            sell_score += 1
            reasons.append("MACD crossed SELL with negative histogram")

        ema_cross = "NEUTRAL"
        if fast_ema > slow_ema:
            buy_score += 1
            ema_cross = "BUY"
            reasons.append("fast EMA is above slow EMA")
        elif fast_ema < slow_ema:
            sell_score += 1
            ema_cross = "SELL"
            reasons.append("fast EMA is below slow EMA")

        if rsi < 30.0:
            buy_score += 1
            reasons.append("RSI is oversold")
        elif rsi > 70.0:
            sell_score += 1
            reasons.append("RSI is overbought")
        elif 45.0 <= rsi <= 55.0:
            reasons.append("RSI is neutral")

        score = max(buy_score, sell_score)
        direction = "BUY" if buy_score > sell_score else "SELL" if sell_score > buy_score else "HOLD"
        if direction == "HOLD" or score == 0:
            signal = "HOLD"
            tier = 3
            confidence = 0.0
        else:
            signal = direction
            tier = 1 if score >= 3 else 2 if score == 2 else 3
            confidence = {1: 0.9, 2: 0.7, 3: 0.5}[tier]
            if bb["squeeze"]:
                confidence += 0.2
            if 45.0 <= rsi <= 55.0:
                confidence -= 0.1
            confidence = max(0.0, min(1.0, confidence))

        if signal == "HOLD" and 45.0 <= rsi <= 55.0:
            confidence = 0.0
        return {
            "signal": signal,
            "confidence": round(confidence, 4),
            "tier": tier,
            "reasons": reasons,
            "bb": bb,
            "rsi": rsi,
            "macd": macd,
            "ema_cross": ema_cross,
        }

    def get_signal_safe(self, prices: Sequence[float]) -> dict:
        """
        Exception-safe signal generator. Returns a neutral HOLD structure
        if prices is empty, invalid, non-finite, or causes calculation failure.
        """
        try:
            if not prices:
                raise ValueError("prices sequence is empty")
            return self.get_signal(list(prices))
        except Exception as e:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "tier": 3,
                "reasons": [f"fallback due to input error: {e}"],
                "bb": {"upper": 0.0, "middle": 0.0, "lower": 0.0, "width": 0.0, "squeeze": False},
                "rsi": 50.0,
                "macd": {"macd_line": 0.0, "signal_line": 0.0, "histogram": 0.0, "cross": "NONE"},
                "ema_cross": "NEUTRAL",
            }

    def is_entry_blocked(self) -> bool:
        """SignalEngine does not block trading entries directly."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()


def is_entry_blocked() -> bool:
    return False


def is_blocked() -> bool:
    return is_entry_blocked()

