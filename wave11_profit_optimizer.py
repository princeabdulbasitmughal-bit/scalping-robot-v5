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
import math
import threading
from typing import Dict, List, Optional, Tuple


class ProfitOptimizer:

    def __init__(self):
        self._win_streak: int = 0
        self._loss_streak: int = 0
        self._peak_floating_pnl: Dict[str, float] = {}  # ticket → peak float PnL
        self._partial_closed: Dict[str, bool] = {}
        self._session_results: collections.deque = collections.deque(maxlen=10)
        self._lock = threading.RLock()


    # ── Win/Loss streak tracking ──────────────────────────────────────────────
    def record_result(self, won: bool):
        with self._lock:
            w = bool(won)
            if w:
                self._win_streak += 1
                self._loss_streak = 0
            else:
                self._loss_streak += 1
                self._win_streak = 0
            self._session_results.append(1 if w else 0)

    # ── Lot size modifier from streaks ────────────────────────────────────────
    def streak_lot_modifier(self) -> float:
        """
        Win streak ≥ 3 → 1.1x lots (confidence bonus)
        Loss streak ≥ 3 → 0.5x lots (recovery mode)
        Loss streak ≥ 5 → 0.01 minimum (ultra conservative)
        """
        with self._lock:
            if self._loss_streak >= 5:
                return 0.10  # ultra-conservative multiplier (10% of base lot)
            elif self._loss_streak >= 3:
                return 0.5
            elif self._win_streak >= 3:
                return 1.1
            return 1.0

    def is_recovery_mode(self) -> bool:
        with self._lock:
            return self._loss_streak >= 3

    def is_entry_blocked(self) -> bool:
        """Unified risk interface: profit optimizer modulates lots, does not block."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()

    # ── Floating PnL reversal guard ───────────────────────────────────────────
    def update_peak_float(self, ticket: str, current_float_pnl: float):
        """Track peak floating PnL per position."""
        if (
            current_float_pnl is None
            or isinstance(current_float_pnl, bool)
            or not isinstance(current_float_pnl, (int, float))
            or not math.isfinite(current_float_pnl)
        ):
            return
        with self._lock:
            prev_peak = self._peak_floating_pnl.get(str(ticket), 0.0)
            if current_float_pnl > prev_peak:
                self._peak_floating_pnl[str(ticket)] = float(current_float_pnl)

    def should_close_reversal(self, ticket: str, current_float_pnl: float, threshold: float = 0.5) -> bool:
        """
        Return True if floating PnL has reversed by > threshold% of its peak.
        E.g. peak was $20, now $8 → reversed 60% → close.
        """
        if (
            current_float_pnl is None
            or isinstance(current_float_pnl, bool)
            or not isinstance(current_float_pnl, (int, float))
            or not math.isfinite(current_float_pnl)
        ):
            return False
        with self._lock:
            peak = self._peak_floating_pnl.get(str(ticket), 0.0)
            if peak <= 0 or current_float_pnl >= peak:
                return False
            thresh = float(threshold) if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and threshold > 0 else 0.5
            reversal_pct = (peak - current_float_pnl) / peak
            return reversal_pct >= thresh

    def cleanup_ticket(self, ticket: str):
        with self._lock:
            self._peak_floating_pnl.pop(str(ticket), None)
            self._partial_closed.pop(str(ticket), None)

    # ── Partial profit levels ─────────────────────────────────────────────────
    def get_partial_close_level(
        self,
        ticket: str,
        pips_profit: float = 0.0,
        tp_pips: float = 40.0,
        lot_size: float = 0.02,
        current_float_pnl: float = None,
        base_lot: float = None,
        **kwargs
    ) -> Optional[float]:
        """
        Return lot to partially close, or None if no partial close needed.
        Level 1: at 40% of TP → close 33% of position
        Level 2: at 70% of TP → close another 33%
        """
        if current_float_pnl is not None:
            pips_profit = current_float_pnl
        if base_lot is not None:
            lot_size = base_lot

        if (
            lot_size is None
            or isinstance(lot_size, bool)
            or not isinstance(lot_size, (int, float))
            or not math.isfinite(lot_size)
            or lot_size < 0.02
        ):
            return None  # too small for partial close
        if (
            pips_profit is None
            or isinstance(pips_profit, bool)
            or not isinstance(pips_profit, (int, float))
            or not math.isfinite(pips_profit)
        ):
            return None
        if (
            tp_pips is None
            or isinstance(tp_pips, bool)
            or not isinstance(tp_pips, (int, float))
            or not math.isfinite(tp_pips)
            or tp_pips <= 0
        ):
            return None

        with self._lock:
            t = str(ticket)
            if self._partial_closed.get(t, False):
                return None  # already partially closed

            pct = pips_profit / tp_pips
            if pct >= 0.4:
                self._partial_closed[t] = True
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
        if (
            base_tp is None
            or isinstance(base_tp, bool)
            or not isinstance(base_tp, (int, float))
            or not math.isfinite(base_tp)
            or base_tp <= 0
        ):
            return 45.0
        if (
            pips_profit is None
            or isinstance(pips_profit, bool)
            or not isinstance(pips_profit, (int, float))
            or not math.isfinite(pips_profit)
        ):
            return base_tp

        ws = int(win_streak) if isinstance(win_streak, (int, float)) and not isinstance(win_streak, bool) else 0

        if market_regime in ("TRENDING_UP", "TRENDING_DOWN") and ws >= 2:
            if pips_profit >= base_tp * 0.8:  # 80% to TP
                return round(base_tp * 1.2, 1)  # extend 20%
        return base_tp

    # ── Daily target scaling ──────────────────────────────────────────────────
    def daily_target_lot_scale(self, daily_pnl: float, daily_target: float) -> float:
        """Reduce lot size as we approach daily target."""
        if (
            daily_pnl is None
            or daily_target is None
            or isinstance(daily_pnl, bool)
            or isinstance(daily_target, bool)
            or not isinstance(daily_pnl, (int, float))
            or not isinstance(daily_target, (int, float))
            or not math.isfinite(daily_pnl)
            or not math.isfinite(daily_target)
            or daily_target <= 0
        ):
            return 1.0
        pct = daily_pnl / daily_target
        if pct >= 0.75:
            return 0.5   # 75% target hit → half size
        elif pct >= 0.5:
            return 0.75
        return 1.0

    # ── Session performance report ────────────────────────────────────────────
    def session_stats(self) -> Dict:
        with self._lock:
            results = list(self._session_results)
            if not results:
                return {"win_rate": 0.0, "win_streak": 0, "loss_streak": 0, "recovery_mode": False}
            wr = sum(results) / len(results) * 100
            return {
                "win_rate": round(wr, 1),
                "win_streak": self._win_streak,
                "loss_streak": self._loss_streak,
                "recovery_mode": self._loss_streak >= 3,
                "sample_size": len(results)
            }

    def reset(self) -> None:
        """Thread-safe reset of streaks and tracked tickets."""
        with self._lock:
            self._win_streak = 0
            self._loss_streak = 0
            self._peak_floating_pnl.clear()
            self._partial_closed.clear()
            self._session_results.clear()

    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 11,
                "name": "ProfitOptimizer",
                "win_streak": self._win_streak,
                "loss_streak": self._loss_streak,
                "recovery_mode": self.is_recovery_mode(),
                "tracked_positions": len(self._peak_floating_pnl),
            }


# ── Module-level singleton ─────────────────────────────────────────────────
profit_optimizer = ProfitOptimizer()

