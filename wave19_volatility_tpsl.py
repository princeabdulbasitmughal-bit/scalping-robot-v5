"""
wave19_volatility_tpsl.py
Wave 19: Volatility-Adaptive TP/SL Adjuster
============================================
Dynamically widens TP in high-vol sessions (London/NY overlap)
and tightens both TP and SL in low-vol dead zones.
Uses ATR-like calculation on recent closes.

Usage:
    from wave19_volatility_tpsl import vol_tpsl_adjuster
    tp, sl = vol_tpsl_adjuster.adjusted_tpsl(closes, base_tp_pips, base_sl_pips, session_info)
"""

import math
import logging

logger = logging.getLogger(__name__)


class VolatilityTPSLAdjuster:
    """
    Adjusts TP and SL pips based on:
    1. Recent ATR (Average True Range proxy from closes)
    2. Session volatility index from session_optimizer
    """

    def __init__(
        self,
        atr_period: int = 14,
        min_tp_pips: float = 20.0,
        max_tp_pips: float = 120.0,
        min_sl_pips: float = 15.0,
        max_sl_pips: float = 60.0,
    ):
        self.atr_period = atr_period
        self.min_tp_pips = min_tp_pips
        self.max_tp_pips = max_tp_pips
        self.min_sl_pips = min_sl_pips
        self.max_sl_pips = max_sl_pips

    def _calc_atr(self, closes: list) -> float:
        """ATR proxy: mean of abs(close[i] - close[i-1]) over last atr_period bars."""
        if len(closes) < 2:
            return 0.5
        diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        recent = diffs[-self.atr_period:] if len(diffs) >= self.atr_period else diffs
        if not recent:
            return 0.5
        return sum(recent) / len(recent)

    def adjusted_tpsl(
        self,
        closes: list,
        base_tp_pips: float = 45.0,
        base_sl_pips: float = 30.0,
        session_info: dict = None,
    ):
        """
        Returns (tp_pips, sl_pips) adjusted for current volatility.

        High-vol:  TP widens up to 1.5x, SL stays (better R:R)
        Low-vol:   TP tightens to 0.75x, SL tightens to 0.85x (lock in small wins)
        Normal:    No change
        """
        try:
            atr = self._calc_atr(closes)

            # ATR baseline for XAUUSD: ~0.3-1.5 pips per tick
            atr_ratio = atr / 0.6  # normalise around 0.6 pip average

            # Session vol_index (1.0 = normal, 1.5+ = high, 0.5- = low)
            vol_idx = 1.0
            if session_info and isinstance(session_info, dict):
                vol_idx = float(session_info.get("vol_index", 1.0))

            # Combined volatility score
            vol_score = (atr_ratio + vol_idx) / 2.0

            if vol_score >= 1.4:
                # High volatility — widen TP to catch bigger moves, keep SL
                tp_mult = min(1.5, 0.8 + vol_score * 0.5)
                sl_mult = 1.0
                regime = "HIGH-VOL"
            elif vol_score <= 0.65:
                # Low volatility — tighten both to lock profits
                tp_mult = 0.75
                sl_mult = 0.85
                regime = "LOW-VOL"
            else:
                # Normal — no change
                tp_mult = 1.0
                sl_mult = 1.0
                regime = "NORMAL"

            tp_adj = round(
                max(self.min_tp_pips, min(base_tp_pips * tp_mult, self.max_tp_pips)), 1
            )
            sl_adj = round(
                max(self.min_sl_pips, min(base_sl_pips * sl_mult, self.max_sl_pips)), 1
            )

            logger.debug(
                f"[VOL TPSL] regime={regime} atr={atr:.4f} vol_idx={vol_idx:.2f} "
                f"score={vol_score:.2f} TP:{base_tp_pips}->{tp_adj} SL:{base_sl_pips}->{sl_adj}"
            )
            return tp_adj, sl_adj

        except Exception as e:
            logger.debug(f"[VOL TPSL] Error: {e} — using base values")
            return base_tp_pips, base_sl_pips


# Module-level singleton
vol_tpsl_adjuster = VolatilityTPSLAdjuster()
