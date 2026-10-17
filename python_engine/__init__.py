"""
Scalping Robot V5 - Python Engine Package
High-performance institutional algorithmic trading core.
"""

__version__ = "5.0.0"

from .scalping_engine import ScalpingRobotV5, ScalpingSignal
from .backtester import Backtester, ScalpingBacktester
from .storage import atomic_write_json, safe_read_json
from .live_runner import ScalpingLiveRunner
from .risk_guard import RiskGuard, Decision

__all__ = [
    "__version__",
    "ScalpingRobotV5",
    "ScalpingSignal",
    "Backtester",
    "ScalpingBacktester",
    "atomic_write_json",
    "safe_read_json",
    "ScalpingLiveRunner",
    "RiskGuard",
    "Decision",
]


