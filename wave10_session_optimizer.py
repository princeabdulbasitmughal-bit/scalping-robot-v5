"""
Wave 10: Session Optimizer
Features:
  - Identifies optimal trading windows within each session
  - Volatility calendar (best/worst hours for XAUUSD)
  - Pip target adjustment per session volatility profile
  - Session overlap bonus (London-NY overlap = highest quality)
  - Friday afternoon and Monday morning filters
"""
from datetime import datetime, timezone
from typing import Dict, Tuple


# ── XAUUSD hourly volatility map (UTC hour → relative volatility index 0-10) ──
XAUUSD_HOURLY_VOLATILITY = {
    0:  3,   # Tokyo open - moderate
    1:  4,
    2:  5,   # Tokyo peak
    3:  4,
    4:  3,
    5:  3,
    6:  4,   # Frankfurt pre-open
    7:  7,   # London open — HIGH
    8:  9,   # London peak — VERY HIGH
    9:  9,
    10: 8,
    11: 7,
    12: 6,   # London midday dip
    13: 8,   # NY open pre-market
    14: 10,  # London-NY overlap — MAXIMUM
    15: 10,
    16: 9,
    17: 8,
    18: 6,   # NY afternoon
    19: 5,
    20: 4,
    21: 3,   # Markets wind down
    22: 3,   # Rollover window — avoid
    23: 3,   # Asia early
}

# ── Session definitions (UTC) ──────────────────────────────────────────────
SESSIONS = {
    "TOKYO":   {"start": 0,  "end": 9,  "pip_multiplier": 0.7,  "quality": "LOW"},
    "LONDON":  {"start": 7,  "end": 16, "pip_multiplier": 1.0,  "quality": "HIGH"},
    "NY":      {"start": 13, "end": 22, "pip_multiplier": 1.0,  "quality": "HIGH"},
    "OVERLAP": {"start": 13, "end": 17, "pip_multiplier": 1.3,  "quality": "PREMIUM"},
}

# ── Avoid windows ──────────────────────────────────────────────────────────
AVOID_HOURS_UTC = {22, 23, 0}   # Rollover + thin early Tokyo


class SessionOptimizer:

    def get_current_session_info(self) -> Dict:
        """Return current session metadata and trading quality."""
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday

        # Weekend check
        if weekday >= 5:
            return {"session": "CLOSED", "quality": "NONE", "vol_index": 0,
                    "pip_multiplier": 1.0, "tradeable": False, "reason": "WEEKEND"}

        # Friday afternoon filter (after 19:00 UTC)
        if weekday == 4 and hour >= 19:
            return {"session": "FRIDAY_CLOSE", "quality": "LOW", "vol_index": 2,
                    "pip_multiplier": 0.5, "tradeable": False, "reason": "FRIDAY_AFTERNOON"}

        # Monday morning filter (before 8:00 UTC — gaps risk)
        if weekday == 0 and hour < 8:
            return {"session": "MONDAY_OPEN", "quality": "LOW", "vol_index": 2,
                    "pip_multiplier": 0.5, "tradeable": False, "reason": "MONDAY_MORNING_GAP"}

        # Rollover avoidance
        if hour in AVOID_HOURS_UTC:
            return {"session": "ROLLOVER", "quality": "NONE", "vol_index": 1,
                    "pip_multiplier": 0.0, "tradeable": False, "reason": "ROLLOVER_WINDOW"}

        vol_index = XAUUSD_HOURLY_VOLATILITY.get(hour, 5)

        # Determine active session
        in_london = 7 <= hour < 16
        in_ny = 13 <= hour < 22
        in_overlap = 13 <= hour < 17
        in_tokyo = 0 <= hour < 9

        if in_overlap:
            session = "OVERLAP"
            quality = "PREMIUM"
            pip_mult = 1.3
        elif in_london and in_ny:
            session = "LONDON_NY"
            quality = "HIGH"
            pip_mult = 1.15
        elif in_london:
            session = "LONDON"
            quality = "HIGH"
            pip_mult = 1.0
        elif in_ny:
            session = "NY"
            quality = "HIGH"
            pip_mult = 1.0
        elif in_tokyo:
            session = "TOKYO"
            quality = "LOW"
            pip_mult = 0.7
        else:
            session = "OFF_HOURS"
            quality = "NONE"
            pip_mult = 0.0

        # Low volatility guard
        tradeable = vol_index >= 4 and quality != "NONE"

        return {
            "session": session,
            "quality": quality,
            "vol_index": vol_index,
            "pip_multiplier": pip_mult,
            "tradeable": tradeable,
            "hour_utc": hour,
            "weekday": weekday,
            "reason": "OK" if tradeable else f"LOW_VOL ({vol_index}/10)"
        }

    def get_adjusted_targets(
        self, base_sl: float, base_tp: float, rr_ratio: float = 1.5
    ) -> Tuple[float, float]:
        """Adjust SL/TP based on session volatility profile."""
        info = self.get_current_session_info()
        mult = info.get("pip_multiplier", 1.0)
        sl = round(base_sl * mult, 1)
        sl = max(15.0, min(70.0, sl))
        tp = round(sl * rr_ratio, 1)
        return sl, tp

    def session_report(self) -> str:
        info = self.get_current_session_info()
        return (
            f"[SESSION] {info['session']} | Quality={info['quality']} "
            f"Vol={info['vol_index']}/10 Tradeable={info['tradeable']} "
            f"PipMult={info.get('pip_multiplier', 1.0)}"
        )


# ── Module-level singleton ─────────────────────────────────────────────────
session_optimizer = SessionOptimizer()
