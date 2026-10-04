"""
Wave 8: Signal Quality Optimizer
Adds: ATR-adaptive SL/TP, Stochastic RSI, candlestick pattern detection,
      volume proxy, support/resistance levels, signal scoring 0-100.
"""
import math
import collections
from typing import List, Dict, Any, Tuple, Optional


class SignalScorer:
    """Score signal quality 0-100 before trade entry."""

    def __init__(self):
        self._atr_history: collections.deque = collections.deque(maxlen=14)
        self._stoch_k_history: collections.deque = collections.deque(maxlen=14)
        self._vol_proxy: collections.deque = collections.deque(maxlen=20)

    # ── ATR (Average True Range) ──────────────────────────────────────────────
    def compute_atr(self, bars: List[Dict]) -> float:
        """14-period ATR from OHLC bars dict list."""
        if len(bars) < 2:
            return 1.0
        trs = []
        for i in range(1, min(15, len(bars))):
            h = float(bars[-i].get("high", bars[-i].get("close", 0)) or 0)
            l = float(bars[-i].get("low",  bars[-i].get("close", 0)) or 0)
            pc = float(bars[-(i+1)].get("close", 0) or 0)
            if h == 0 and l == 0:
                c = float(bars[-i].get("close", 0) or 0)
                h = c + 0.5
                l = c - 0.5
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        return round(sum(trs) / len(trs), 3) if trs else 1.0

    # ── Stochastic RSI ────────────────────────────────────────────────────────
    def compute_stoch_rsi(self, closes: List[float], period: int = 14) -> float:
        """Stochastic RSI: 0-100 (0=oversold, 100=overbought)."""
        if len(closes) < period + 1:
            return 50.0
        # Compute RSI series
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        if len(gains) < period:
            return 50.0
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        rsi = 100 - 100 / (1 + rs)
        self._stoch_k_history.append(rsi)
        if len(self._stoch_k_history) < 3:
            return rsi
        stoch_list = list(self._stoch_k_history)
        min_rsi = min(stoch_list)
        max_rsi = max(stoch_list)
        if max_rsi == min_rsi:
            return 50.0
        return round((rsi - min_rsi) / (max_rsi - min_rsi) * 100, 1)

    # ── Support / Resistance ──────────────────────────────────────────────────
    def find_sr_levels(self, closes: List[float], window: int = 20) -> Tuple[float, float]:
        """Identify nearest support and resistance from recent price action."""
        if len(closes) < window:
            return closes[-1] - 1.0, closes[-1] + 1.0
        recent = closes[-window:]
        support = min(recent)
        resistance = max(recent)
        return support, resistance

    # ── Candlestick Patterns ──────────────────────────────────────────────────
    def detect_pattern(self, bars: List[Dict]) -> str:
        """Detect basic 1-2 bar patterns. Returns: BULL_ENGULF, BEAR_ENGULF, DOJI, HAMMER, SHOOTING_STAR, NONE"""
        if len(bars) < 2:
            return "NONE"
        c = bars[-1]
        p = bars[-2]
        co = float(c.get("open", c.get("close", 0)) or 0)
        cc = float(c.get("close", 0) or 0)
        po = float(p.get("open", p.get("close", 0)) or 0)
        pc = float(p.get("close", 0) or 0)
        ch = float(c.get("high", cc) or cc)
        cl = float(c.get("low", cc) or cc)
        body = abs(cc - co)
        upper_wick = ch - max(cc, co)
        lower_wick = min(cc, co) - cl
        total_range = ch - cl if ch > cl else 0.001

        # Doji: body < 10% of range
        if body < total_range * 0.1:
            return "DOJI"
        # Hammer: bullish, small body at top, long lower wick
        if cc > co and lower_wick > body * 2 and upper_wick < body:
            return "HAMMER"
        # Shooting star: bearish, small body at bottom, long upper wick
        if cc < co and upper_wick > body * 2 and lower_wick < body:
            return "SHOOTING_STAR"
        # Bullish engulfing
        if pc < po and cc > co and cc > po and co < pc:
            return "BULL_ENGULF"
        # Bearish engulfing
        if pc > po and cc < co and cc < po and co > pc:
            return "BEAR_ENGULF"
        return "NONE"

    # ── Volume Proxy (tick activity) ──────────────────────────────────────────
    def update_volume_proxy(self, price_change: float):
        """Track price movement as volume proxy."""
        self._vol_proxy.append(abs(price_change))

    def is_high_volume(self) -> bool:
        """True if current tick movement > 1.5x recent average."""
        if len(self._vol_proxy) < 5:
            return False
        avg = sum(list(self._vol_proxy)[:-1]) / (len(self._vol_proxy) - 1)
        return self._vol_proxy[-1] > avg * 1.5 if avg > 0 else False

    # ── Master Score ──────────────────────────────────────────────────────────
    def score_signal(
        self,
        signal: str,
        closes: List[float],
        bars: List[Dict],
        rsi: float,
        bb_squeeze: bool,
        market_regime: str,
        ema_cross: str,
    ) -> int:
        """
        Score a signal 0-100. Higher = better quality.
        Threshold: only take trade if score >= 55.
        """
        if signal == "HOLD" or not closes:
            return 0

        score = 50  # baseline

        # Stochastic RSI alignment
        stoch = self.compute_stoch_rsi(closes[-30:] if len(closes) >= 30 else closes)
        if signal == "BUY":
            if stoch < 30:
                score += 15  # oversold — great BUY
            elif stoch < 50:
                score += 7
            elif stoch > 70:
                score -= 15  # overbought — bad BUY
        else:  # SELL
            if stoch > 70:
                score += 15  # overbought — great SELL
            elif stoch > 50:
                score += 7
            elif stoch < 30:
                score -= 15  # oversold — bad SELL

        # Candlestick pattern alignment
        pattern = self.detect_pattern(bars)
        bullish_patterns = {"HAMMER", "BULL_ENGULF"}
        bearish_patterns = {"SHOOTING_STAR", "BEAR_ENGULF"}
        if signal == "BUY" and pattern in bullish_patterns:
            score += 12
        elif signal == "SELL" and pattern in bearish_patterns:
            score += 12
        elif pattern == "DOJI":
            score -= 8  # uncertainty
        elif (signal == "BUY" and pattern in bearish_patterns) or \
             (signal == "SELL" and pattern in bullish_patterns):
            score -= 12  # opposing pattern

        # BB squeeze bonus (breakout imminent)
        if bb_squeeze:
            score += 8

        # Market regime alignment
        if market_regime == "TRENDING_UP" and signal == "BUY":
            score += 10
        elif market_regime == "TRENDING_DOWN" and signal == "SELL":
            score += 10
        elif market_regime == "VOLATILE":
            score -= 25
        elif market_regime == "RANGING":
            score += 5  # mean-reversion friendly

        # EMA cross alignment
        if ema_cross == signal:
            score += 8
        elif ema_cross != "NEUTRAL" and ema_cross != signal:
            score -= 8

        # RSI extremes
        if signal == "BUY" and rsi < 30:
            score += 10
        elif signal == "SELL" and rsi > 70:
            score += 10

        # High volume confirmation
        if self.is_high_volume():
            score += 5

        return max(0, min(100, score))

    # ── ATR-Adaptive SL/TP Calculator ────────────────────────────────────────
    def get_adaptive_sl_tp(
        self, bars: List[Dict], base_sl_pips: float = 30.0, rr_ratio: float = 1.5
    ) -> Tuple[float, float]:
        """
        Return (sl_pips, tp_pips) scaled by ATR volatility.
        Low volatility → tighter SL. High volatility → wider SL.
        """
        atr = self.compute_atr(bars)
        # ATR in price terms for XAUUSD. Convert to pips (1 pip = 0.1)
        atr_pips = atr / 0.1

        # Scale: if ATR > 15 pips → widen; if ATR < 5 pips → tighten
        if atr_pips > 15:
            factor = min(1.5, atr_pips / 10.0)
        elif atr_pips < 5:
            factor = max(0.6, atr_pips / 8.0)
        else:
            factor = 1.0

        sl = round(base_sl_pips * factor, 1)
        sl = max(15.0, min(60.0, sl))  # Hard clamp 15-60 pips
        tp = round(sl * rr_ratio, 1)
        return sl, tp


# ── Module-level singleton ─────────────────────────────────────────────────
signal_scorer = SignalScorer()
