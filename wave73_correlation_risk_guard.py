"""
wave73_correlation_risk_guard.py
----------------------------------
Risk guard: monitors the concentration of open positions and blocks new
entries when the number of simultaneously open positions exceeds a safe
limit, preventing overexposure / correlation risk.

Rules
-----
- Tracks a set of open position ticket IDs.
- `open_position(ticket)` registers a new open trade.
- `close_position(ticket)` removes a closed trade.
- `is_entry_blocked()` returns True when len(open_positions) >= `max_positions`.
- Fail-closed: invalid ticket types raise; gate stays OPEN when 0 positions.
- Thread-safe: all mutations under RLock.

Note: This module models *correlation* risk conservatively — having too many
concurrent positions creates amplified exposure if they are correlated (as
they typically are for the same instrument/direction).

Module-level aliases
---------------------
  is_entry_blocked(tick)   -> bool
  is_blocked(tick)         -> bool
  open_position(ticket)    -> None
  close_position(ticket)   -> None
  update(tick)             -> None   (no-op; wave interface)
  reset()                  -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
from typing import Set

DEFAULT_MAX_POSITIONS: int = 3   # max simultaneous open trades before blocking


class CorrelationRiskGuard:
    """Blocks entries when too many positions are open simultaneously."""

    def __init__(self, max_positions: int = DEFAULT_MAX_POSITIONS) -> None:
        if isinstance(max_positions, bool) or not isinstance(max_positions, int):
            raise TypeError("max_positions must be a plain int")
        if max_positions < 1:
            raise ValueError("max_positions must be >= 1")

        self.max_positions = max_positions
        self._lock = threading.RLock()
        self._open_tickets: Set = set()

    # ── private validation ──────────────────────────────────────────────────
    @staticmethod
    def _validate_ticket(ticket: object) -> None:
        if ticket is None:
            raise TypeError("ticket must not be None")
        if isinstance(ticket, bool):
            raise TypeError("ticket must not be bool")
        if isinstance(ticket, float):
            if math.isnan(ticket) or math.isinf(ticket):
                raise ValueError("ticket float must not be NaN/Inf")
        # Allow int, str, float (valid numeric ID)
        if not isinstance(ticket, (int, float, str)):
            raise TypeError(f"ticket must be int, str, or float, got {type(ticket)}")

    # ── public API ──────────────────────────────────────────────────────────
    def open_position(self, ticket: object) -> None:
        """Register a newly opened position."""
        self._validate_ticket(ticket)
        with self._lock:
            self._open_tickets.add(ticket)

    def close_position(self, ticket: object) -> None:
        """
        Remove a closed position.
        Silently ignored if ticket is not tracked (idempotent).
        """
        self._validate_ticket(ticket)
        with self._lock:
            self._open_tickets.discard(ticket)

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) when open position count >= max_positions.
        """
        with self._lock:
            return len(self._open_tickets) >= self.max_positions

    def get_open_count(self) -> int:
        """Return current number of tracked open positions (thread-safe)."""
        with self._lock:
            return len(self._open_tickets)

    def get_open_tickets(self) -> Set:
        """Return a snapshot copy of open ticket IDs (thread-safe)."""
        with self._lock:
            return set(self._open_tickets)

    def reset(self) -> None:
        """Clear all open positions."""
        with self._lock:
            self._open_tickets.clear()


# ── module-level singleton ──────────────────────────────────────────────────
_guard = CorrelationRiskGuard(max_positions=DEFAULT_MAX_POSITIONS)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → CorrelationRiskGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def open_position(ticket: object) -> None:
    """Module-level alias → CorrelationRiskGuard.open_position()."""
    _guard.open_position(ticket)


def close_position(ticket: object) -> None:
    """Module-level alias → CorrelationRiskGuard.close_position()."""
    _guard.close_position(ticket)


def update(tick: object = None) -> None:
    """No-op update hook (wave interface compatibility)."""
    pass


def reset() -> None:
    """Module-level alias → CorrelationRiskGuard.reset()."""
    _guard.reset()
