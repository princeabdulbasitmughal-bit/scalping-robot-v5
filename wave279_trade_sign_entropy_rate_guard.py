"""
wave279_trade_sign_entropy_rate_guard.py
----------------------------------------
Guard: Trade Sign Symbolic Entropy Rate & Information Predictability Guard

Monitors symbolic block entropy rate, Kolmogorov-Sinai metric entropy, and high-frequency trade sign predictability
(Kolmogorov 1958; Sinai 1959; Boffetta et al. 2002; Hasbrouck 1991):
    Trade Sign Stream:          epsilon_t in {+1, -1}
    Symbolic 3-Gram Words:      w_i = (epsilon_{i}, epsilon_{i+1}, epsilon_{i+2}) in {-1, +1}^3  (8 total words)
    Word Probabilities:         P(w) = count(w) / K  where K = N - 2
    Symbolic Block Entropy:     H(3) = - sum_{w: P(w) > 0} P(w) * ln(P(w))
    Normalized Entropy Rate:    h = H(3) / (3 * ln(2)) in [0.0, 1.0]
    Max Word Frequency:         P_{max} = max_w(P(w))

Under independent, stochastic Bernoulli order flow:
    - Trade sign patterns are unpredictable and evenly distributed across all 8 configurations: h ~ 0.80 to 1.00.
    - No single 3-symbol pattern dominates the flow: P_{max} <= 0.30.

During deterministic algorithmic sweeping, iceberg order splitting, or predatory spoofing loops:
    - Trade signs collapse into highly repetitive, predictable word sequences (e.g. +++... or +-+-...):
        1) Symbolic Entropy Rate Collapse:
           h <= MIN_ENTROPY_RATE (default: 0.40) over rolling N >= MIN_TRADES (25 trade signs).
        2) Acute Pattern Repetition:
           P_{max} >= MAX_WORD_FREQUENCY (default: 0.65) over N >= ACUTE_MIN_TRADES (18 trade signs).

Entering trades during symbolic entropy collapse guarantees front-running by deterministic algorithms,
severe queue bypass, and catastrophic adverse selection.

When entropy rate collapse or acute pattern repetition is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade signs via record_trade_sign(sign, ts=None) or
  direct metrics via record_entropy_rate(entropy_rate, max_word_freq=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 30 trade signs.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or zero trade signs are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_sign(sign, ts=None)                                                             -> None
  record_entropy_rate(entropy_rate, max_word_freq=None, sample_count=None, ts=None)             -> None
  update(sign, ts=None)                                                                        -> None   (alias)
  get_entropy_metrics()                                                                        -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30                   # 30 trade signs rolling window
MIN_TRADES: int = 25                    # 25 trade signs minimum for entropy rate evaluation
MIN_ENTROPY_RATE: float = 0.40          # 0.40 minimum normalized entropy rate floor
MAX_WORD_FREQUENCY: float = 0.65        # 65% single word frequency threshold
ACUTE_MIN_TRADES: int = 18              # 18 trades minimum for acute pattern repetition
WORD_LEN: int = 3                       # 3-symbol words
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signs: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy_rate: float = 1.0
_latest_max_word_freq: float = 0.125
_blocked_until: float = 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float or int (not bool)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_entropy_rate(
    entropy_rate: float,
    max_word_freq: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed symbolic entropy rate and max word frequency.
    """
    global _latest_entropy_rate, _latest_max_word_freq, _blocked_until

    if not _is_valid_numeric(entropy_rate):
        return

    h = max(0.0, min(1.0, float(entropy_rate)))
    p_max = float(max_word_freq) if (max_word_freq is not None and _is_valid_numeric(max_word_freq)) else 0.15
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 25

    with _lock:
        _latest_entropy_rate = h
        _latest_max_word_freq = p_max

        # Condition 2: Acute Pattern Repetition
        if p_max >= MAX_WORD_FREQUENCY and n >= ACUTE_MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Symbolic Entropy Rate Collapse
        if h <= MIN_ENTROPY_RATE and n >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade_sign(sign: int, ts: Optional[float] = None) -> None:
    """
    Ingest a single trade sign (+1 for Buy, -1 for Sell) and calculate symbolic entropy rate.
    """
    global _signs, _latest_entropy_rate, _latest_max_word_freq, _blocked_until

    if not _is_valid_numeric(sign):
        return

    s_val = int(sign)
    if s_val == 0:
        return
    s = 1 if s_val > 0 else -1

    with _lock:
        _signs.append(s)

        if len(_signs) >= ACUTE_MIN_TRADES:
            # Construct 3-gram words
            k = len(_signs) - WORD_LEN + 1
            if k > 0:
                counts: Dict[Tuple[int, int, int], int] = collections.defaultdict(int)
                for i in range(k):
                    word = (_signs[i], _signs[i + 1], _signs[i + 2])
                    counts[word] += 1

                max_c = max(counts.values())
                p_max = max_c / float(k)
                _latest_max_word_freq = p_max

                # Condition 2: Acute Pattern Repetition
                if p_max >= MAX_WORD_FREQUENCY and len(_signs) >= ACUTE_MIN_TRADES:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return

                # Calculate Shannon block entropy
                h_block = 0.0
                for c in counts.values():
                    p = c / float(k)
                    h_block -= p * math.log(p)

                max_h = float(WORD_LEN) * math.log(2.0)
                h_norm = h_block / max_h if max_h > 0.0 else 1.0
                _latest_entropy_rate = h_norm

                # Condition 1: Symbolic Entropy Rate Collapse
                if h_norm <= MIN_ENTROPY_RATE and len(_signs) >= MIN_TRADES:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def update(sign: int, ts: Optional[float] = None) -> None:
    """Module alias for record_trade_sign."""
    record_trade_sign(sign, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by entropy rate guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_entropy_metrics() -> Dict[str, Any]:
    """Return dictionary of current symbolic entropy metrics."""
    with _lock:
        return {
            "entropy_rate": round(_latest_entropy_rate, 4),
            "max_word_frequency": round(_latest_max_word_freq, 4),
            "sample_count": len(_signs),
            "word_len": WORD_LEN,
            "min_entropy_rate": MIN_ENTROPY_RATE,
            "max_word_frequency_threshold": MAX_WORD_FREQUENCY,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_entropy_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _signs, _latest_entropy_rate, _latest_max_word_freq, _blocked_until
    with _lock:
        _signs.clear()
        _latest_entropy_rate = 1.0
        _latest_max_word_freq = 0.125
        _blocked_until = 0.0
