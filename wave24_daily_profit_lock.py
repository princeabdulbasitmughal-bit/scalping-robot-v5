"""
Wave 24: Daily Profit Lock
Once daily PnL exceeds the profit target (default +$150), switches the bot into
"protect mode": reduces lot to 0.01 and requires a higher signal quality score.

This prevents giving back profits after a good day.
"""

import logging
import math
import threading

logger = logging.getLogger(__name__)

_DEFAULT_TARGET_USD  = 150.0    # lock triggers at +$150 daily profit
_PROTECT_LOT         = 0.01     # reduced lot in protect mode
_PROTECT_MIN_SCORE   = 70       # require score >= 70 (normally >= 55) in protect mode


class DailyProfitLock:
    """Engages 'protect mode' when daily profit target is reached."""

    def __init__(
        self,
        profit_target_usd: float = None,
        protect_lot: float = _PROTECT_LOT,
        protect_min_score: int = _PROTECT_MIN_SCORE,
        daily_target_usd: float = None,
        **kwargs,
    ):
        self._lock = threading.RLock()
        if daily_target_usd is not None:
            resolved_target = daily_target_usd
        elif profit_target_usd is not None:
            resolved_target = profit_target_usd
        elif "target_usd" in kwargs and kwargs["target_usd"] is not None:
            resolved_target = kwargs["target_usd"]
        else:
            resolved_target = _DEFAULT_TARGET_USD

        self._profit_target = float(resolved_target)
        self._protect_lot   = float(protect_lot)
        self._protect_score = int(protect_min_score)

        self._protect_mode: bool = False
        self._peak_daily_pnl: float = 0.0
        self._engagements: int = 0

    # ------------------------------------------------------------------
    def update(self, daily_pnl: float) -> None:
        """
        Call on every tick / heartbeat with current daily PnL.
        Engages protect mode when target is reached.
        Does NOT auto-disengage during the same trading day
        (daily reset in mt5_live_trader handles midnight UTC reset).
        """
        if daily_pnl is None or not isinstance(daily_pnl, (int, float)) or not math.isfinite(daily_pnl):
            return

        with self._lock:
            if daily_pnl > self._peak_daily_pnl:
                self._peak_daily_pnl = float(daily_pnl)

            if not self._protect_mode and daily_pnl >= self._profit_target:
                self._protect_mode = True
                self._engagements += 1
                logger.info(
                    f"[PROFIT LOCK] ENGAGED #{self._engagements}: "
                    f"daily_pnl=${daily_pnl:.2f} >= target=${self._profit_target:.2f} "
                    f"— lot→{self._protect_lot} score_min→{self._protect_score}"
                )

    def reset(self) -> None:
        """Call on midnight UTC daily reset."""
        with self._lock:
            self._protect_mode = False
            self._peak_daily_pnl = 0.0
            logger.info("[PROFIT LOCK] Daily reset — protect mode cleared")

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._protect_mode

    @property
    def profit_target_usd(self) -> float:
        with self._lock:
            return self._profit_target

    @property
    def daily_target_usd(self) -> float:
        with self._lock:
            return self._profit_target

    def apply_lot(self, current_lot: float) -> float:
        """Return adjusted lot — reduced to protect_lot when locked."""
        if (
            current_lot is None
            or not isinstance(current_lot, (int, float))
            or not math.isfinite(current_lot)
            or current_lot <= 0
        ):
            return current_lot
        with self._lock:
            if self._protect_mode:
                new_lot = min(float(current_lot), self._protect_lot)
                if new_lot < current_lot:
                    logger.debug(
                        f"[PROFIT LOCK] Lot reduced: {current_lot:.2f} → {new_lot:.2f}"
                    )
                return new_lot
            return float(current_lot)

    def get_min_score(self, base_min_score: int = 55) -> int:
        """Return minimum signal score required — higher in protect mode."""
        if not isinstance(base_min_score, (int, float)) or not math.isfinite(base_min_score):
            base_score = 55
        else:
            base_score = int(base_min_score)

        with self._lock:
            if self._protect_mode:
                return max(base_score, self._protect_score)
            return base_score

    apply_min_score = get_min_score

    def info(self) -> dict:
        """Summary dict for live_status.json."""
        with self._lock:
            return {
                "protect_mode": self._protect_mode,
                "profit_target_usd": self._profit_target,
                "daily_target_usd": self._profit_target,
                "peak_daily_pnl": round(self._peak_daily_pnl, 2),
                "engagements": self._engagements,
                "protect_lot": self._protect_lot,
                "protect_min_score": self._protect_score,
            }


# Module-level singleton
daily_profit_lock = DailyProfitLock(
    profit_target_usd=_DEFAULT_TARGET_USD,
    protect_lot=_PROTECT_LOT,
    protect_min_score=_PROTECT_MIN_SCORE,
)
