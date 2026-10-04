"""
Wave 11: Profit Optimizer
Features:
  - Dynamic TP: extend TP when trade is running well (momentum extension)
  - Partial profit at 33% / 67% of TP
  - Win-streak bonus: after 3 wins → allow slightly larger lot (1.1x)
  - Recovery mode: after 3 losses → ultra-conservative 0.01 lot
  - Daily target scaling: slow down after 75% of daily target hit
  - Floating PnL monitor: auto-close if floating PnL reversal > 50% of peak
"""
import collections
import time
from typing import Dict, List, Optional, Tuple


class ProfitOptimizer:

    def __init__(self):
        self._win_streak: int = 0
        self._loss_streak: int = 0
        self._peak_floating_pnl: Dict[str, float] = {}  # ticket → peak float PnL
        self._partial_closed: Dict[str, bool] = {}
        self._session_results: collections.deque = collections.deque(maxlen=10)

    # ── Win/Loss streak tracking ──────────────────────────────────────────────
    def record_result(self, won: bool):
        if won:
            self._win_streak += 1
            self._loss_streak = 0
        else:
            self._loss_streak += 1
            self._win_streak = 0
        self._session_results.append(1 if won else 0)

    # ── Lot size modifier from streaks ────────────────────────────────────────
    def streak_lot_modifier(self) -> float:
        """
        Win streak ≥ 3 → 1.1x lots (confidence bonus)
        Loss streak ≥ 3 → 0.5x lots (recovery mode)
        Loss streak ≥ 5 → 0.01 minimum (ultra conservative)
        """
        if self._loss_streak >= 5:
            return 0.01  # absolute minimum — return raw value, not multiplier
        elif self._loss_streak >= 3:
            return 0.5
        elif self._win_streak >= 3:
            return 1.1
        return 1.0

    def is_recovery_mode(self) -> bool:
        return self._loss_streak >= 3

    # ── Floating PnL reversal guard ───────────────────────────────────────────
    def update_peak_float(self, ticket: str, current_float_pnl: float):
        """Track peak floating PnL per position."""
        prev_peak = self._peak_floating_pnl.get(ticket, 0.0)
        if current_float_pnl > prev_peak:
            self._peak_floating_pnl[ticket] = current_float_pnl

    def should_close_reversal(self, ticket: str, current_float_pnl: float, threshold: float = 0.5) -> bool:
        """
        Return True if floating PnL has reversed by > threshold% of its peak.
        E.g. peak was $20, now $8 → reversed 60% → close.
        """
        peak = self._peak_floating_pnl.get(ticket, 0.0)
        if peak <= 0 or current_float_pnl >= peak:
            return False
        reversal_pct = (peak - current_float_pnl) / peak
        return reversal_pct >= threshold

    def cleanup_ticket(self, ticket: str):
        self._peak_floating_pnl.pop(ticket, None)
        self._partial_closed.pop(ticket, None)

    # ── Partial profit levels ─────────────────────────────────────────────────
    def get_partial_close_level(
        self, ticket: str, pips_profit: float, tp_pips: float, lot_size: float
    ) -> Optional[float]:
        """
        Return lot to partially close, or None if no partial close needed.
        Level 1: at 40% of TP → close 33% of position
        Level 2: at 70% of TP → close another 33%
        """
        if lot_size < 0.03:
            return None  # too small for partial close
        if self._partial_closed.get(ticket, False):
            return None  # already partially closed

        pct = pips_profit / tp_pips if tp_pips > 0 else 0

        if pct >= 0.4:
            self._partial_closed[ticket] = True
            return round(lot_size * 0.33, 2)

        return None

    # ── Dynamic TP extension ──────────────────────────────────────────────────
    def get_extended_tp_pips(
        self,
        base_tp: float,
        pips_profit: float,
        market_regime: str,
        win_streak: int,
    ) -> float:
        """
        If trade is near TP and market is trending → extend TP by 20%.
        Prevents premature exit in strong trending markets.
        """
        if market_regime in ("TRENDING_UP", "TRENDING_DOWN") and win_streak >= 2:
            if pips_profit >= base_tp * 0.8:  # 80% to TP
                return round(base_tp * 1.2, 1)  # extend 20%
        return base_tp

    # ── Daily target scaling ──────────────────────────────────────────────────
    def daily_target_lot_scale(self, daily_pnl: float, daily_target: float) -> float:
        """Reduce lot size as we approach daily target."""
        if daily_target <= 0:
            return 1.0
        pct = daily_pnl / daily_target
        if pct >= 0.75:
            return 0.5   # 75% target hit → half size
        elif pct >= 0.5:
            return 0.75
        return 1.0

    # ── Session performance report ────────────────────────────────────────────
    def session_stats(self) -> Dict:
        results = list(self._session_results)
        if not results:
            return {"win_rate": 0.0, "win_streak": 0, "loss_streak": 0, "recovery_mode": False}
        wr = sum(results) / len(results) * 100
        return {
            "win_rate": round(wr, 1),
            "win_streak": self._win_streak,
            "loss_streak": self._loss_streak,
            "recovery_mode": self.is_recovery_mode(),
            "sample_size": len(results)
        }


# ── Module-level singleton ─────────────────────────────────────────────────
profit_optimizer = ProfitOptimizer()
