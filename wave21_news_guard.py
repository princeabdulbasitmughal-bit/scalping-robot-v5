"""
Wave 21: News Guard
Reads E:\\scalping-robot-v5\\news_status.json produced by gold_news_fetcher.py.
If avoid_trading=True (high-impact event in last 2h) → block all signals.
Also allows manual override via news_override.json: {"override": true} forces trading allowed.
"""

import json
import os
import time
import logging

logger = logging.getLogger(__name__)

_NEWS_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_status.json")
_OVERRIDE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_override.json")


class NewsGuard:
    """Blocks trading during high-impact news windows."""

    def __init__(self):
        self._last_check_time: float = 0.0
        self._cached_avoid: bool = False
        self._cached_reason: str = "no data"
        self._cache_ttl: float = 60.0   # re-read file every 60 s
        self._blocked_count: int = 0

    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load news_status.json with TTL caching."""
        now = time.time()
        if now - self._last_check_time < self._cache_ttl:
            return
        self._last_check_time = now

        # Manual override: {"override": true} → always allow
        try:
            if os.path.exists(_OVERRIDE_FILE):
                with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                    ov = json.load(f)
                if ov.get("override", False):
                    self._cached_avoid = False
                    self._cached_reason = "manual override active"
                    return
        except Exception:
            pass

        # Read news_status.json
        try:
            if not os.path.exists(_NEWS_STATUS_FILE):
                self._cached_avoid = False
                self._cached_reason = "news_status.json not found — allow"
                return
            with open(_NEWS_STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            avoid = bool(data.get("avoid_trading", False))
            headlines = data.get("last_headlines", [])
            last_checked = data.get("last_checked", "")

            if avoid:
                snippet = headlines[0][:60] if headlines else "high-impact event"
                self._cached_reason = f"NEWS GUARD: {snippet} | checked {last_checked}"
                self._cached_avoid = True
            else:
                self._cached_avoid = False
                self._cached_reason = f"news clear | checked {last_checked}"

        except Exception as exc:
            # If we can't read, allow trading (fail-open)
            self._cached_avoid = False
            self._cached_reason = f"news read error ({exc}) — allow"

    # ------------------------------------------------------------------
    def is_trading_allowed(self) -> tuple:
        """
        Returns (allowed: bool, reason: str).
        Call before entering a trade.
        """
        self._load()
        if self._cached_avoid:
            self._blocked_count += 1
            logger.info(f"[NEWS GUARD] BLOCKED #{self._blocked_count}: {self._cached_reason}")
            return False, self._cached_reason
        return True, self._cached_reason

    def info(self) -> dict:
        """Summary dict for live_status.json."""
        self._load()
        return {
            "avoid_trading": self._cached_avoid,
            "reason": self._cached_reason,
            "blocked_total": self._blocked_count,
        }


# Module-level singleton
news_guard = NewsGuard()
