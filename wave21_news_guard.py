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
import threading

logger = logging.getLogger(__name__)

_NEWS_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_status.json")
_OVERRIDE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_override.json")


class NewsGuard:
    """Blocks trading during high-impact news windows."""

    def __init__(self, status_file: str = None, override_file: str = None, cache_ttl: float = 60.0):
        self._status_file = status_file or _NEWS_STATUS_FILE
        self._override_file = override_file or _OVERRIDE_FILE
        self._last_check_time: float = 0.0
        self._cached_avoid: bool = False
        self._cached_reason: str = "no data"
        self._cache_ttl: float = float(cache_ttl) if isinstance(cache_ttl, (int, float)) and not isinstance(cache_ttl, bool) and cache_ttl >= 0 else 60.0
        self._blocked_count: int = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def _load(self, now_ts: float = None) -> None:
        """Load news_status.json with TTL caching."""
        with self._lock:
            now = time.time() if (now_ts is None or isinstance(now_ts, bool)) else float(now_ts)
            if (now - self._last_check_time) < self._cache_ttl and self._last_check_time > 0:
                return
            self._last_check_time = now

            # Manual override: {"override": true} → always allow
            try:
                if os.path.exists(self._override_file):
                    with open(self._override_file, "r", encoding="utf-8") as f:
                        ov = json.load(f)
                    if ov.get("override", False):
                        self._cached_avoid = False
                        self._cached_reason = "manual override active"
                        return
            except Exception as e:
                logger.warning(f"[NEWS GUARD] Override file parse error: {e}")

            # Read news_status.json
            try:
                if not os.path.exists(self._status_file):
                    self._cached_avoid = False
                    self._cached_reason = "news_status.json not found — allow"
                    return
                with open(self._status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                avoid = bool(data.get("avoid_trading", False))
                headlines = data.get("last_headlines", [])
                last_checked = data.get("last_checked", "")

                if avoid:
                    snippet = headlines[0][:60] if (isinstance(headlines, list) and headlines and isinstance(headlines[0], str)) else "high-impact event"
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
    def is_trading_allowed(self, now_ts: float = None) -> tuple:
        """
        Returns (allowed: bool, reason: str).
        Call before entering a trade.
        """
        with self._lock:
            self._load(now_ts=now_ts)
            if self._cached_avoid:
                self._blocked_count += 1
                logger.info(f"[NEWS GUARD] BLOCKED #{self._blocked_count}: {self._cached_reason}")
                return False, self._cached_reason
            return True, self._cached_reason

    def is_entry_blocked(self, now_ts: float = None) -> bool:
        """Unified risk interface check for trade entry blocking."""
        allowed, _ = self.is_trading_allowed(now_ts=now_ts)
        return not allowed

    def is_blocked(self, now_ts: float = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def set_override(self, avoid: bool, reason: str = "test override") -> None:
        """Set explicit avoid/allow state for testing or manual control."""
        with self._lock:
            self._cached_avoid = bool(avoid)
            self._cached_reason = str(reason)
            self._last_check_time = time.time() + 999999.0  # bypass TTL

    def reset(self) -> None:
        """Reset internal cache and telemetry."""
        with self._lock:
            self._last_check_time = 0.0
            self._cached_avoid = False
            self._cached_reason = "no data"
            self._blocked_count = 0

    def info(self, now_ts: float = None) -> dict:
        """Summary dict for live_status.json."""
        with self._lock:
            self._load(now_ts=now_ts)
            return {
                "avoid_trading": self._cached_avoid,
                "reason": self._cached_reason,
                "blocked_total": self._blocked_count,
            }


# Module-level singleton
news_guard = NewsGuard()
