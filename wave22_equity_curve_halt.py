"""
Wave 22: Equity Curve Halt
Monitors the slope of the last N trade PnL values.
If the running equity curve is in accelerating drawdown, halt trading until recovery.

Halt condition  : sum of last N PnL < -threshold_usd  AND slope < -slope_threshold
Recovery condition: balance recovers > halt_balance * recovery_factor  OR  N_good_trades win streak
"""

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class EquityCurveHalt:
    """
    Tracks rolling trade PnL and halts trading when the equity curve
    is in deep negative slope (drawdown acceleration).
    """

    def __init__(
        self,
        window: int = 10,
        loss_threshold_usd: float = -150.0,
        slope_threshold: float = -10.0,
        recovery_win_streak: int = 2,
        cooldown_sec: float = 300.0,
    ):
        self._window = window
        self._loss_threshold = loss_threshold_usd   # sum over window
        self._slope_threshold = slope_threshold      # avg PnL per trade
        self._recovery_win_streak = recovery_win_streak
        self._cooldown_sec = cooldown_sec

        self._pnl_history: deque = deque(maxlen=window)
        self._halted: bool = False
        self._halt_time: float = 0.0
        self._halt_balance: float = 0.0
        self._consecutive_wins: int = 0
        self._halt_count: int = 0
        self._halt_reason: str = ""

    # ------------------------------------------------------------------
    def record_trade(self, pnl: float, won: bool) -> None:
        """Call after every closed trade."""
        self._pnl_history.append(pnl)
        if won:
            self._consecutive_wins += 1
        else:
            self._consecutive_wins = 0

    # ------------------------------------------------------------------
    def is_trading_allowed(self, current_balance: float) -> tuple:
        """
        Returns (allowed: bool, reason: str).
        Call before each signal evaluation.
        """
        # --- Check recovery if already halted ---
        if self._halted:
            elapsed = time.time() - self._halt_time
            wins_ok = self._consecutive_wins >= self._recovery_win_streak
            time_ok = elapsed >= self._cooldown_sec

            if wins_ok or time_ok:
                self._halted = False
                recovery_reason = (
                    f"win streak={self._consecutive_wins}"
                    if wins_ok
                    else f"cooldown {elapsed/60:.1f}min"
                )
                logger.info(f"[EQ HALT] RECOVERED via {recovery_reason} — trading resumed")
                return True, f"eq_halt recovered ({recovery_reason})"
            else:
                reason = (
                    f"EQUITY CURVE HALT: {self._halt_reason} | "
                    f"wins_needed={self._recovery_win_streak - self._consecutive_wins} "
                    f"or wait {(self._cooldown_sec - elapsed)/60:.1f}min"
                )
                return False, reason

        # --- Evaluate halt condition ---
        if len(self._pnl_history) < self._window:
            return True, f"eq_ok (warming up {len(self._pnl_history)}/{self._window})"

        window_sum = sum(self._pnl_history)
        slope = window_sum / self._window   # average PnL per trade

        if window_sum < self._loss_threshold and slope < self._slope_threshold:
            self._halted = True
            self._halt_time = time.time()
            self._halt_balance = current_balance
            self._halt_count += 1
            self._consecutive_wins = 0
            self._halt_reason = (
                f"window_sum=${window_sum:.2f} slope=${slope:.2f}/trade"
            )
            logger.warning(
                f"[EQ HALT] ACTIVATED #{self._halt_count}: {self._halt_reason} — trading halted"
            )
            return False, f"EQUITY CURVE HALT #{self._halt_count}: {self._halt_reason}"

        return True, f"eq_ok sum=${window_sum:.2f} slope=${slope:.2f}"

    def info(self) -> dict:
        """Summary dict for live_status.json."""
        window_list = list(self._pnl_history)
        return {
            "halted": self._halted,
            "halt_count": self._halt_count,
            "halt_reason": self._halt_reason,
            "window_pnl_sum": round(sum(window_list), 2) if window_list else 0.0,
            "consecutive_wins": self._consecutive_wins,
            "trades_in_window": len(window_list),
        }


# Module-level singleton
equity_curve_halt = EquityCurveHalt(
    window=10,
    loss_threshold_usd=-150.0,
    slope_threshold=-10.0,
    recovery_win_streak=2,
    cooldown_sec=300.0,
)
