"""
Wave 57: Hourly PnL Map
=========================
Tracks realised PnL bucketed by UTC hour (0-23) within the current daily session.
If the current UTC hour has accumulated net loss > threshold -> reduces lot
by 50% (advisory, not a hard block).
Automatically resets at UTC midnight rollover.

API:
    hourly_pnl_map.record_trade(pnl: float, now_dt: Optional[datetime] = None)
    hourly_pnl_map.get_lot_multiplier(now_dt: Optional[datetime] = None) -> float
    hourly_pnl_map.reset() -> None
    hourly_pnl_map.info(now_dt: Optional[datetime] = None) -> dict
"""

import math
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_DEFAULT_LOSS_THRESHOLD_USD = -30.0   # if hour has lost more than $30, scale lot


class HourlyPnLMap:
    """
    Accumulates PnL per UTC hour. Advisory lot multiplier only — no hard block.
    Supports daily UTC rollover and deterministic datetime injection.
    """

    def __init__(self, loss_threshold_usd: float = _DEFAULT_LOSS_THRESHOLD_USD):
        try:
            val = float(loss_threshold_usd)
            self.loss_threshold_usd = -abs(val) if math.isfinite(val) else _DEFAULT_LOSS_THRESHOLD_USD
        except (TypeError, ValueError):
            self.loss_threshold_usd = _DEFAULT_LOSS_THRESHOLD_USD

        # Map hour (0-23) -> cumulative PnL this daily session
        self._hour_pnl: Dict[int, float] = {h: 0.0 for h in range(24)}
        self._trade_count: int = 0
        self._last_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of hourly PnL map and counters."""
        with self._lock:
            self._hour_pnl = {h: 0.0 for h in range(24)}
            self._trade_count = 0
            self._last_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_daily_rollover(self, dt: datetime) -> None:
        """Must be called under self._lock."""
        cur_date = dt.strftime("%Y-%m-%d")
        if cur_date != self._last_date:
            logger.info(
                f"[WAVE57] Daily UTC rollover from {self._last_date} to {cur_date}: resetting hourly PnL map"
            )
            self._hour_pnl = {h: 0.0 for h in range(24)}
            self._last_date = cur_date

    def _resolve_dt(self, now_dt: Optional[datetime]) -> datetime:
        if now_dt is None:
            return datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            return now_dt.replace(tzinfo=timezone.utc)
        return now_dt.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # Feed API
    # ------------------------------------------------------------------

    def record_trade(self, pnl: float, now_dt: Optional[datetime] = None) -> None:
        """Call at trade close with USD PnL."""
        try:
            pnl_val = float(pnl)
            if not math.isfinite(pnl_val):
                return

            dt = self._resolve_dt(now_dt)
            hour = max(0, min(23, int(dt.hour)))

            with self._lock:
                self._check_daily_rollover(dt)
                self._hour_pnl[hour] = round(self._hour_pnl.get(hour, 0.0) + pnl_val, 4)
                self._trade_count += 1
                logger.info(
                    f"[WAVE57] Hour {hour:02d}UTC PnL updated: "
                    f"${self._hour_pnl[hour]:.2f} (trade PnL ${pnl_val:.2f})"
                )
        except Exception as exc:
            logger.debug(f"[WAVE57] record_trade error: {exc}")

    # ------------------------------------------------------------------
    # Advisory API
    # ------------------------------------------------------------------

    def get_lot_multiplier(self, now_dt: Optional[datetime] = None) -> float:
        """
        Returns 0.5 if the current UTC hour has historically lost more than
        the threshold this session, otherwise 1.0.
        """
        try:
            dt = self._resolve_dt(now_dt)
            hour = max(0, min(23, int(dt.hour)))

            with self._lock:
                self._check_daily_rollover(dt)
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

    def info(self, now_dt: Optional[datetime] = None) -> dict:
        try:
            dt = self._resolve_dt(now_dt)
            hour = max(0, min(23, int(dt.hour)))

            with self._lock:
                self._check_daily_rollover(dt)
                current_pnl = self._hour_pnl.get(hour, 0.0)
                return {
                    "wave": 57,
                    "name": "HourlyPnLMap",
                    "current_utc_hour": hour,
                    "current_hour_pnl_usd": round(current_pnl, 2),
                    "lot_multiplier": 0.5 if current_pnl < self.loss_threshold_usd else 1.0,
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
