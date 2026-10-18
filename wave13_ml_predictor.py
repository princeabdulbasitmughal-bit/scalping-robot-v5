"""
Wave 13 — ML Price Direction Predictor
=======================================
Zero external dependencies. Pure Python linear regression on the last 20 bars.
Predicts price direction: UP / DOWN / NEUTRAL with a confidence score 0-100.

Usage:
    from wave13_ml_predictor import ml_predictor
    result = ml_predictor.predict(closes)  # closes: list of floats (recent prices)
    # result = {"direction": "UP", "confidence": 72, "slope": 0.012, "r_squared": 0.81}
"""

import math
import time
import logging
import threading

logger = logging.getLogger("wave13_ml")


class LinearRegressor:
    """Ordinary least squares 1-D linear regression. Pure Python, zero deps."""

    def __init__(self):
        self._predictor = None
        self._lock = threading.RLock()

    def _get_predictor(self):
        with self._lock:
            if self._predictor is None:
                self._predictor = MLPredictor(_regressor=self)
            return self._predictor

    def fit(self, y: list = None) -> dict:
        if not y or not isinstance(y, (list, tuple)):
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
        clean_y = []
        for val in y:
            if val is not None and not isinstance(val, bool):
                try:
                    f = float(val)
                    if math.isfinite(f):
                        clean_y.append(f)
                except (ValueError, TypeError):
                    continue
        n = len(clean_y)
        if n < 3:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(clean_y) / n
        ss_xy = sum((x[i] - x_mean) * (clean_y[i] - y_mean) for i in range(n))
        ss_xx = sum((x[i] - x_mean) ** 2 for i in range(n))
        ss_yy = sum((clean_y[i] - y_mean) ** 2 for i in range(n))
        if ss_xx == 0:
            return {"slope": 0.0, "intercept": y_mean, "r_squared": 0.0}
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        denom = ss_xx * ss_yy
        r_squared = (ss_xy ** 2 / denom) if denom > 0 else 0.0
        return {"slope": slope, "intercept": intercept, "r_squared": max(0.0, min(1.0, r_squared))}

    def predict(self, y: list = None) -> dict:
        """Alias for MLPredictor().predict(y)."""
        return self._get_predictor().predict(y)

    def predict_signal_agreement(self, closes: list = None, signal: str = "BUY") -> dict:
        """Check if ML prediction agrees with a trading signal (BUY/SELL)."""
        return self._get_predictor().predict_signal_agreement(closes, signal)

    def record_outcome(self, predicted_direction: str, actual_direction: str):
        """Call after a trade closes to track ML accuracy."""
        return self._get_predictor().record_outcome(predicted_direction, actual_direction)

    @property
    def accuracy(self) -> float:
        """Prediction accuracy percentage (0.0 to 100.0)."""
        return self._get_predictor().accuracy

    @property
    def last_prediction(self) -> dict:
        """Most recent prediction dictionary."""
        return self._get_predictor().last_prediction

    def is_entry_blocked(self) -> bool:
        """Unified risk interface: ML regression does not block trade execution."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()

    def reset(self) -> None:
        """Reset underlying predictor state."""
        return self._get_predictor().reset()

    def info(self) -> dict:
        """Telemetry diagnostics."""
        return self._get_predictor().info()


class MLPredictor:
    """
    Predicts next-bar price direction using:
    1. Linear regression slope (trend)
    2. Momentum (price delta ratio over window)
    3. Volatility-normalised slope (ATR-adjusted)
    4. RSI-style overbought/oversold correction
    """

    def __init__(self, window: int = 20, min_r2: float = 0.25, _regressor=None):
        self.window = int(window) if isinstance(window, (int, float)) and not isinstance(window, bool) and math.isfinite(window) and window >= 5 else 20
        self.min_r2 = float(min_r2) if isinstance(min_r2, (int, float)) and not isinstance(min_r2, bool) and math.isfinite(min_r2) and min_r2 >= 0 else 0.25
        self._regressor = _regressor if _regressor is not None else LinearRegressor()
        self._last_prediction: dict = {}
        self._prediction_history: list = []  # (timestamp, direction, confidence)
        self._hit_count = 0
        self._total_checked = 0
        self._lock = threading.RLock()

    def is_entry_blocked(self) -> bool:
        """Unified risk interface: ML prediction does not block trade execution."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()

    # ------------------------------------------------------------------
    def predict(self, closes: list = None) -> dict:
        """
        Predict next-bar direction from a list of close prices.

        Returns:
            {
              "direction": "UP" | "DOWN" | "NEUTRAL",
              "confidence": int (0-100),
              "slope": float,
              "r_squared": float,
              "momentum": float,
              "atr_norm_slope": float
            }
        """
        if not closes or not isinstance(closes, (list, tuple)):
            return {"direction": "NEUTRAL", "confidence": 0, "slope": 0.0, "r_squared": 0.0,
                    "momentum": 0.0, "atr_norm_slope": 0.0}

        clean_closes = []
        # Optimization: only inspect up to the last 2 * window elements to bound memory and CPU
        source_closes = closes[-max(self.window * 2, 50):] if len(closes) > max(self.window * 2, 50) else closes
        for c in source_closes:
            if c is not None and not isinstance(c, bool):
                try:
                    fc = float(c)
                    if math.isfinite(fc):
                        clean_closes.append(fc)
                except (ValueError, TypeError):
                    continue

        if len(clean_closes) < 5:
            return {"direction": "NEUTRAL", "confidence": 0, "slope": 0.0, "r_squared": 0.0,
                    "momentum": 0.0, "atr_norm_slope": 0.0}

        # Use last `window` bars
        data = clean_closes[-self.window:]
        n = len(data)

        # 1. Linear regression
        reg = self._regressor.fit(data)
        slope = reg["slope"]
        if not math.isfinite(slope):
            slope = 0.0
        r2 = reg["r_squared"]
        if not math.isfinite(r2):
            r2 = 0.0

        # 2. Momentum: percentage move over full window
        if data[0] != 0:
            momentum = (data[-1] - data[0]) / data[0]
            if not math.isfinite(momentum):
                momentum = 0.0
        else:
            momentum = 0.0

        # 3. ATR proxy (mean absolute delta)
        deltas = [abs(data[i] - data[i - 1]) for i in range(1, n)]
        atr = sum(deltas) / len(deltas) if deltas else 1.0
        atr_norm_slope = slope / atr if atr > 0 else 0.0
        if not math.isfinite(atr_norm_slope):
            atr_norm_slope = 0.0

        # 4. RSI-style: count up-bars vs down-bars
        up_bars = sum(1 for i in range(1, n) if data[i] > data[i - 1])
        down_bars = n - 1 - up_bars
        rsi_proxy = 100 * up_bars / (n - 1) if n > 1 else 50.0

        # ── Determine direction ──────────────────────────────────────
        # Primary: slope sign
        # Secondary: momentum agreement
        # Confidence: based on r², normalised slope magnitude, rsi_proxy
        direction = "NEUTRAL"
        raw_confidence = 0.0

        if r2 >= self.min_r2:
            slope_score = min(abs(atr_norm_slope) * 50.0, 40.0)   # 0-40 pts
            r2_score = r2 * 30.0                                    # 0-30 pts
            momentum_score = min(abs(momentum) * 1000.0, 20.0)     # 0-20 pts
            rsi_bonus = 10.0 if (rsi_proxy > 60 and slope > 0) or (rsi_proxy < 40 and slope < 0) else 0.0

            raw_confidence = slope_score + r2_score + momentum_score + rsi_bonus

            if slope > 0 and momentum >= 0:
                direction = "UP"
            elif slope < 0 and momentum <= 0:
                direction = "DOWN"
            elif slope > 0 and momentum < 0:
                # Conflicting — lower confidence
                direction = "UP"
                raw_confidence *= 0.6
            elif slope < 0 and momentum > 0:
                direction = "DOWN"
                raw_confidence *= 0.6
        else:
            # Weak regression — NEUTRAL
            raw_confidence = max(0.0, r2 * 30.0)

        confidence = min(100, max(0, int(raw_confidence)))

        result = {
            "direction": direction,
            "confidence": confidence,
            "slope": round(slope, 6),
            "r_squared": round(r2, 4),
            "momentum": round(momentum, 6),
            "atr_norm_slope": round(atr_norm_slope, 4),
        }
        with self._lock:
            self._last_prediction = result
        logger.debug(
            f"[ML PREDICT] dir={direction} conf={confidence}% r2={r2:.3f} "
            f"slope={slope:.5f} atr_norm={atr_norm_slope:.3f} mom={momentum:.5f}"
        )
        return result

    # ------------------------------------------------------------------
    def predict_signal_agreement(self, closes: list = None, signal: str = "BUY") -> dict:
        """
        Check if ML prediction agrees with a trading signal (BUY/SELL).

        Returns:
            {
              "agree": bool,
              "confidence": int,
              "direction": str,
              "boost": float   # lot multiplier suggestion: 1.0 = no boost, 1.2 = 20% more
            }
        """
        if closes is None:
            closes = []
        pred = self.predict(closes)
        direction = pred["direction"]
        confidence = pred["confidence"]

        agree = False
        boost = 1.0

        if signal == "BUY" and direction == "UP" and confidence >= 50:
            agree = True
            boost = 1.0 + (confidence - 50) / 200.0   # up to +25% at conf=100
        elif signal == "SELL" and direction == "DOWN" and confidence >= 50:
            agree = True
            boost = 1.0 + (confidence - 50) / 200.0
        elif direction == "NEUTRAL" or confidence < 30:
            agree = True   # no strong disagreement — allow trade
            boost = 1.0

        return {
            "agree": agree,
            "confidence": confidence,
            "direction": direction,
            "boost": round(boost, 3),
        }

    # ------------------------------------------------------------------
    def record_outcome(self, predicted_direction: str, actual_direction: str):
        """Call after a trade closes to track ML accuracy."""
        pred_str = str(predicted_direction).upper() if predicted_direction is not None else ""
        act_str = str(actual_direction).upper() if actual_direction is not None else ""
        with self._lock:
            self._total_checked += 1
            if pred_str == act_str and pred_str not in ("NEUTRAL", ""):
                self._hit_count += 1

    @property
    def accuracy(self) -> float:
        with self._lock:
            if self._total_checked == 0:
                return 0.0
            return round(100.0 * self._hit_count / self._total_checked, 1)

    @property
    def last_prediction(self) -> dict:
        with self._lock:
            return dict(self._last_prediction)

    def reset(self) -> None:
        """Reset internal predictions, history, and accuracy metrics."""
        with self._lock:
            self._last_prediction.clear()
            self._prediction_history.clear()
            self._hit_count = 0
            self._total_checked = 0

    def info(self) -> dict:
        """Telemetry diagnostics dictionary."""
        with self._lock:
            return {
                "window": self.window,
                "min_r2": self.min_r2,
                "total_checked": self._total_checked,
                "hit_count": self._hit_count,
                "accuracy_pct": self.accuracy,
                "last_prediction": dict(self._last_prediction),
            }


# Module-level singleton
ml_predictor = MLPredictor(window=20, min_r2=0.20)


def is_entry_blocked() -> bool:
    """Module-level risk check alias."""
    return ml_predictor.is_entry_blocked()


def is_blocked() -> bool:
    """Module-level risk check alias."""
    return is_entry_blocked()
