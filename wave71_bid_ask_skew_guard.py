"""
wave71_bid_ask_skew_guard.py
------------------------------
Risk guard: blocks entries when the bid/ask depth imbalance (skew) is
extreme, indicating one-sided order flow that makes clean fills unlikely.

Rules
-----
- Skew = (bid_volume - ask_volume) / (bid_volume + ask_volume)
  Range: [-1.0, +1.0]
  - +1.0 → all bids (strong buy pressure)
  - -1.0 → all asks (strong sell pressure)
- Blocks BUY  entries when skew < -`skew_threshold`  (overwhelming sell pressure)
- Blocks SELL entries when skew > +`skew_threshold`  (overwhelming buy pressure)
- Blocks ALL  entries when |skew| > `hard_block_threshold` (extreme imbalance)
- Fail-closed: invalid inputs (bool, NaN, Inf, negative volumes, zero total)
  return BLOCKED immediately.
- During warmup (< `min_ticks` valid skew readings), gate is OPEN.

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool     (uses last stored skew)
  is_blocked(tick)       -> bool     (alias)
  update(bid_vol, ask_vol) -> None   (record new depth snapshot)
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading

# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_SKEW_THRESHOLD:  float = 0.7   # directional block threshold
DEFAULT_HARD_THRESHOLD:  float = 0.9   # all-direction block threshold
DEFAULT_MIN_TICKS:       int   = 5     # warmup readings before blocking


class BidAskSkewGuard:
    """Blocks entries on extreme bid/ask depth imbalance."""

    def __init__(
        self,
        skew_threshold: float = DEFAULT_SKEW_THRESHOLD,
        hard_block_threshold: float = DEFAULT_HARD_THRESHOLD,
        min_ticks: int = DEFAULT_MIN_TICKS,
    ) -> None:
        # ── validate ─────────────────────────────────────────────────────
        for name, val in [("skew_threshold", skew_threshold),
                          ("hard_block_threshold", hard_block_threshold)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if not (0.0 < val <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")

        if skew_threshold >= hard_block_threshold:
            raise ValueError("skew_threshold must be < hard_block_threshold")

        if isinstance(min_ticks, bool) or not isinstance(min_ticks, int):
            raise TypeError("min_ticks must be a plain int")
        if min_ticks < 1:
            raise ValueError("min_ticks must be >= 1")

        self.skew_threshold = float(skew_threshold)
        self.hard_block_threshold = float(hard_block_threshold)
        self.min_ticks = min_ticks

        self._lock = threading.RLock()
        self._last_skew: float = 0.0
        self._tick_count: int = 0
        self._last_valid: bool = False    # True once a valid reading was stored

    # ── private ────────────────────────────────────────────────────────────
    @staticmethod
    def _validate_volume(name: str, val: object) -> float:
        if isinstance(val, bool):
            raise TypeError(f"{name} must not be bool")
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be numeric")
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"{name} must not be NaN/Inf")
        if v < 0:
            raise ValueError(f"{name} must be >= 0")
        return v

    @staticmethod
    def _compute_skew(bid_vol: float, ask_vol: float) -> float:
        total = bid_vol + ask_vol
        if total == 0.0:
            return 0.0   # neutral when no depth data
        return (bid_vol - ask_vol) / total

    # ── public API ──────────────────────────────────────────────────────────
    def update(self, bid_volume: object, ask_volume: object) -> None:
        """
        Record a new bid/ask depth snapshot.

        Parameters
        ----------
        bid_volume : total bid-side volume (>= 0)
        ask_volume : total ask-side volume (>= 0)
        """
        bv = self._validate_volume("bid_volume", bid_volume)
        av = self._validate_volume("ask_volume", ask_volume)

        skew = self._compute_skew(bv, av)

        with self._lock:
            self._last_skew = skew
            self._tick_count += 1
            self._last_valid = True

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) when depth imbalance exceeds thresholds.

        Returns
        -------
        bool – True = blocked, False = allowed.
        """
        with self._lock:
            if self._tick_count < self.min_ticks or not self._last_valid:
                return False  # still in warmup

            skew = self._last_skew
            abs_skew = abs(skew)

            # Hard block: extreme imbalance in either direction
            if abs_skew >= self.hard_block_threshold:
                return True

            # Directional blocks
            # skew very negative → overwhelming sell pressure → block BUY
            # skew very positive → overwhelming buy pressure → block SELL
            # We block all entries when either direction is extreme
            if abs_skew >= self.skew_threshold:
                return True

            return False

    def get_skew(self) -> float:
        """Return the most recent skew value (thread-safe)."""
        with self._lock:
            return self._last_skew

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._last_skew = 0.0
            self._tick_count = 0
            self._last_valid = False


# ── module-level singleton ──────────────────────────────────────────────────
_guard = BidAskSkewGuard(
    skew_threshold=DEFAULT_SKEW_THRESHOLD,
    hard_block_threshold=DEFAULT_HARD_THRESHOLD,
    min_ticks=DEFAULT_MIN_TICKS,
)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → BidAskSkewGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def update(bid_volume: object, ask_volume: object) -> None:
    """Module-level alias → BidAskSkewGuard.update()."""
    _guard.update(bid_volume, ask_volume)


def reset() -> None:
    """Module-level alias → BidAskSkewGuard.reset()."""
    _guard.reset()
