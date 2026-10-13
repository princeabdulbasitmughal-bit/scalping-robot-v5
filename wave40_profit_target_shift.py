"""
Wave 40: ProfitTargetShift
If daily PnL > +$150, tighten TP to 80% of normal to lock in profits more aggressively.
Also, if daily PnL < -$100, widen TP slightly to 110% to attempt recovery (use carefully).
"""
import logging
import math
import threading

logger = logging.getLogger(__name__)

_TP_TIGHTEN_THRESHOLD = 150.0   # daily profit above which TP is tightened
_TP_LOOSEN_THRESHOLD  = -100.0  # daily loss below which TP is widened (recovery mode)
_TIGHTEN_FACTOR       = 0.80    # 80% of normal TP when in profit
_LOOSEN_FACTOR        = 1.10    # 110% of normal TP in recovery mode


class ProfitTargetShift:
    """
    Adjusts the TP multiplier based on daily PnL to protect profits or attempt recovery.
    Call adjust_tp(raw_tp_pips, daily_pnl) to get the modified TP value.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_factor: float = 1.0
        self._mode: str = "NORMAL"

    # ------------------------------------------------------------------
    def adjust_tp(self, raw_tp_pips: float, daily_pnl: float) -> float:
        """
        Returns adjusted TP pips based on daily PnL status.

        Args:
            raw_tp_pips: The base TP in pips from config.
            daily_pnl:   Current session's running PnL in USD.

        Returns:
            float: Modified TP in pips.
        """
        if raw_tp_pips is None or math.isnan(raw_tp_pips) or math.isinf(raw_tp_pips) or raw_tp_pips <= 0:
            return raw_tp_pips

        safe_pnl = 0.0 if (daily_pnl is None or math.isnan(daily_pnl) or math.isinf(daily_pnl)) else float(daily_pnl)

        with self._lock:
            if safe_pnl >= _TP_TIGHTEN_THRESHOLD:
                factor = _TIGHTEN_FACTOR
                mode = "PROFIT_LOCK"
            elif safe_pnl <= _TP_LOOSEN_THRESHOLD:
                factor = _LOOSEN_FACTOR
                mode = "RECOVERY"
            else:
                factor = 1.0
                mode = "NORMAL"

            if mode != self._mode:
                self._mode = mode
                self._last_factor = factor
                logger.info(
                    f"[PROFIT TARGET SHIFT] Mode changed to {mode} — "
                    f"TP factor={factor:.2f}x (daily_pnl=${safe_pnl:+.2f})"
                )

            adjusted = round(raw_tp_pips * factor, 1)
            return adjusted

    # ------------------------------------------------------------------
    def info(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode,
                "tp_factor": self._last_factor,
                "tighten_threshold_usd": _TP_TIGHTEN_THRESHOLD,
                "loosen_threshold_usd": _TP_LOOSEN_THRESHOLD,
            }


# Module-level singleton
profit_target_shift = ProfitTargetShift()
