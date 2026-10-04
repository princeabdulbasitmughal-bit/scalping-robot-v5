"""
Wave 24: Daily Profit Lock
Once daily PnL exceeds the profit target (default +$150), switches the bot into
"protect mode": reduces lot to 0.01 and requires a higher signal quality score.

This prevents giving back profits after a good day.
"""

import logging

logger = logging.getLogger(__name__)

_DEFAULT_TARGET_USD  = 150.0    # lock triggers at +$150 daily profit
_PROTECT_LOT         = 0.01     # reduced lot in protect mode
_PROTECT_MIN_SCORE   = 70       # require score >= 70 (normally >= 55) in protect mode


class DailyProfitLock:
    """Engages 'protect mode' when daily profit target is reached."""

    def __init__(
        self,
        profit_target_usd: float = _DEFAULT_TARGET_USD,
        protect_lot: float = _PROTECT_LOT,
        protect_min_score: int = _PROTECT_MIN_SCORE,
    ):
        self._profit_target = profit_target_usd
        self._protect_lot   = protect_lot
        self._protect_score = protect_min_score

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
        if daily_pnl > self._peak_daily_pnl:
            self._peak_daily_pnl = daily_pnl

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
        self._protect_mode = False
        self._peak_daily_pnl = 0.0
        logger.info("[PROFIT LOCK] Daily reset — protect mode cleared")

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._protect_mode

    def apply_lot(self, current_lot: float) -> float:
        """Return adjusted lot — reduced to protect_lot when locked."""
        if self._protect_mode:
            new_lot = min(current_lot, self._protect_lot)
            if new_lot < current_lot:
                logger.debug(
                    f"[PROFIT LOCK] Lot reduced: {current_lot:.2f} → {new_lot:.2f}"
                )
            return new_lot
        return current_lot

    def get_min_score(self, base_min_score: int = 55) -> int:
        """Return minimum signal score required — higher in protect mode."""
        if self._protect_mode:
            return max(base_min_score, self._protect_score)
        return base_min_score

    def info(self) -> dict:
        """Summary dict for live_status.json."""
        return {
            "protect_mode": self._protect_mode,
            "profit_target_usd": self._profit_target,
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
