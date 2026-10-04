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

logger = logging.getLogger("wave13_ml")


class LinearRegressor:
    """Ordinary least squares 1-D linear regression. Pure Python, zero deps."""

    def fit(self, y: list) -> dict:
        n = len(y)
        if n < 3:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        ss_xy = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        ss_xx = sum((x[i] - x_mean) ** 2 for i in range(n))
        ss_yy = sum((y[i] - y_mean) ** 2 for i in range(n))
        if ss_xx == 0:
            return {"slope": 0.0, "intercept": y_mean, "r_squared": 0.0}
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        r_squared = (ss_xy ** 2 / (ss_xx * ss_yy)) if ss_yy > 0 else 0.0
        return {"slope": slope, "intercept": intercept, "r_squared": max(0.0, min(1.0, r_squared))}


class MLPredictor:
    """
    Predicts next-bar price direction using:
    1. Linear regression slope (trend)
    2. Momentum (price delta ratio over window)
    3. Volatility-normalised slope (ATR-adjusted)
    4. RSI-style overbought/oversold correction
    """

    def __init__(self, window: int = 20, min_r2: float = 0.25):
        self.window = window
        self.min_r2 = min_r2
        self._regressor = LinearRegressor()
        self._last_prediction: dict = {}
        self._prediction_history: list = []  # (timestamp, direction, confidence)
        self._hit_count = 0
        self._total_checked = 0

    # ------------------------------------------------------------------
    def predict(self, closes: list) -> dict:
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
        if len(closes) < 5:
            return {"direction": "NEUTRAL", "confidence": 0, "slope": 0.0, "r_squared": 0.0,
                    "momentum": 0.0, "atr_norm_slope": 0.0}

        # Use last `window` bars
        data = closes[-self.window:]
        n = len(data)

        # 1. Linear regression
        reg = self._regressor.fit(data)
        slope = reg["slope"]
        r2 = reg["r_squared"]

        # 2. Momentum: percentage move over full window
        if data[0] != 0:
            momentum = (data[-1] - data[0]) / data[0]
        else:
            momentum = 0.0

        # 3. ATR proxy (mean absolute delta)
        deltas = [abs(data[i] - data[i - 1]) for i in range(1, n)]
        atr = sum(deltas) / len(deltas) if deltas else 1.0
        atr_norm_slope = slope / atr if atr > 0 else 0.0

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
        self._last_prediction = result
        logger.debug(
            f"[ML PREDICT] dir={direction} conf={confidence}% r2={r2:.3f} "
            f"slope={slope:.5f} atr_norm={atr_norm_slope:.3f} mom={momentum:.5f}"
        )
        return result

    # ------------------------------------------------------------------
    def predict_signal_agreement(self, closes: list, signal: str) -> dict:
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
        self._total_checked += 1
        if predicted_direction == actual_direction and predicted_direction != "NEUTRAL":
            self._hit_count += 1

    @property
    def accuracy(self) -> float:
        if self._total_checked == 0:
            return 0.0
        return round(100.0 * self._hit_count / self._total_checked, 1)

    @property
    def last_prediction(self) -> dict:
        return self._last_prediction


# Module-level singleton
ml_predictor = MLPredictor(window=20, min_r2=0.20)
