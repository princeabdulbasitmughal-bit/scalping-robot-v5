"""
Wave 57: Hourly PnL Map
=========================
Tracks realised PnL bucketed by UTC hour (0-23) within the current session.
If the current UTC hour has accumulated net loss > threshold -> reduces lot
by 50% (advisory, not a hard block).

API:
    hourly_pnl_map.record_trade(pnl: float)
    hourly_pnl_map.get_lot_multiplier() -> float   (0.5 if bad hour, else 1.0)
    hourly_pnl_map.info() -> dict
"""

import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_LOSS_THRESHOLD_USD = -30.0   # if hour has lost more than $30, scale lot


class HourlyPnLMap:
    """
    Accumulates PnL per UTC hour. Advisory lot multiplier only — no hard block.
    """

    def __init__(self, loss_threshold_usd: float = _DEFAULT_LOSS_THRESHOLD_USD):
        self.loss_threshold_usd = loss_threshold_usd
        # Map hour (0-23) -> cumulative PnL this session
        self._hour_pnl: dict = {h: 0.0 for h in range(24)}
        self._trade_count: int = 0

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, pnl: float) -> None:
        """Call at trade close with USD PnL."""
        try:
            hour = datetime.now(timezone.utc).hour
            self._hour_pnl[hour] = self._hour_pnl.get(hour, 0.0) + pnl
            self._trade_count += 1
            logger.info(
                f"[WAVE57] Hour {hour:02d}UTC PnL updated: "
                f"${self._hour_pnl[hour]:.2f} (trade PnL ${pnl:.2f})"
            )
        except Exception as exc:
            logger.debug(f"[WAVE57] record_trade error: {exc}")

    # ------------------------------------------------------------------
    # Advisory API
    # ------------------------------------------------------------------

    def get_lot_multiplier(self) -> float:
        """
        Returns 0.5 if the current UTC hour has historically lost more than
        the threshold this session, otherwise 1.0.
        """
        try:
            hour = datetime.now(timezone.utc).hour
            hour_pnl = self._hour_pnl.get(hour, 0.0)
            if hour_pnl < self.loss_threshold_usd:
                logger.info(
                    f"[WAVE57] Bad hour detected (UTC {hour:02d}): "
                    f"PnL=${hour_pnl:.2f} < threshold ${self.loss_threshold_usd:.2f} "
                    f"-> lot x0.5"
                )
                return 0.5
            return 1.0
        except Exception as exc:
            logger.debug(f"[WAVE57] get_lot_multiplier error: {exc}")
            return 1.0

    # ------------------------------------------------------------------
    # Info API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        try:
            hour = datetime.now(timezone.utc).hour
            current_pnl = self._hour_pnl.get(hour, 0.0)
            return {
                "wave": 57,
                "name": "HourlyPnLMap",
                "current_utc_hour": hour,
                "current_hour_pnl_usd": round(current_pnl, 2),
                "lot_multiplier": self.get_lot_multiplier(),
                "total_trades_recorded": self._trade_count,
                "hour_pnl_map": {
                    str(h): round(v, 2)
                    for h, v in self._hour_pnl.items()
                    if v != 0.0
                },
            }
        except Exception:
            return {"wave": 57, "error": "info_failed"}


# Module-level singleton
hourly_pnl_map = HourlyPnLMap()
