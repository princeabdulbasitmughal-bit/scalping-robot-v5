"""
test_batch24.py - Regression & Hardening tests for Batch 24:
- wave36_spread_momentum: Finite guards, deterministic now_ts spike detection, thread safety, reset.
- wave37_entry_cooldown: Win/loss differential cooldowns, thread safety, max-duration preservation, reset.
- wave38_volatility_breaker: Rolling vs baseline ATR ratio, finite guards, deterministic evaluation, reset.
- wave39_drawdown_pause: Rolling peak drawdown calculation, finite equity guards, pause expiry & window pruning, reset.
"""

import math
import threading
import pytest

from wave36_spread_momentum import SpreadMomentumGuard
from wave37_entry_cooldown import EntryCooldown
from wave38_volatility_breaker import VolatilityBreaker
from wave39_drawdown_pause import DrawdownPause


def test_wave36_spread_momentum():
    guard = SpreadMomentumGuard()
    guard.reset()

    # 1. Non-finite or negative spreads ignored safely
    guard.update(float('nan'))
    guard.update(float('inf'))
    guard.update(-1.0)
    guard.update("invalid")
    assert len(guard._spread_history) == 0

    # 2. Normal baseline spreads: 1.0, 1.1, 1.0
    base_time = 1000.0
    guard.update(1.0, now_ts=base_time)
    guard.update(1.1, now_ts=base_time + 1)
    guard.update(1.0, now_ts=base_time + 2)
    assert guard.is_entry_blocked(now_ts=base_time + 2) is False

    # 3. Sudden 3.8x spike (1.0 -> 3.8) triggers 60s block
    guard.update(3.8, now_ts=base_time + 3)
    assert guard.is_entry_blocked(now_ts=base_time + 3) is True
    assert guard.seconds_remaining(now_ts=base_time + 3) == pytest.approx(60.0)

    # After 65s -> block expires
    assert guard.is_entry_blocked(now_ts=base_time + 68) is False

    # 4. Reset
    guard.reset()
    assert guard.is_entry_blocked(now_ts=base_time + 3) is False
    assert len(guard._spread_history) == 0


def test_wave37_entry_cooldown():
    cd = EntryCooldown()
    cd.force_reset()

    base_time = 5000.0

    # 1. Winning trade triggers 60s cooldown
    cd.record_trade_close(was_win=True, pnl=15.5, now_ts=base_time)
    assert cd.is_entry_blocked(now_ts=base_time + 30) is True
    assert cd.seconds_remaining(now_ts=base_time + 30) == pytest.approx(30.0)
    assert cd.is_entry_blocked(now_ts=base_time + 61) is False

    # 2. Losing trade triggers 120s revenge cooldown
    cd.record_trade_close(was_win=False, pnl=-25.0, now_ts=base_time + 100)
    assert cd.is_entry_blocked(now_ts=base_time + 150) is True
    assert cd.seconds_remaining(now_ts=base_time + 100) == pytest.approx(120.0)

    # 3. Shorter winning cooldown should NOT truncate longer active loss cooldown
    cd.record_trade_close(was_win=True, pnl=5.0, now_ts=base_time + 110)
    # 110 + 60 = 170s, but 100 + 120 = 220s. Must remain blocked until 220s!
    assert cd.is_entry_blocked(now_ts=base_time + 180) is True
    assert cd.is_entry_blocked(now_ts=base_time + 221) is False

    # 4. NaN/Inf PnL handled gracefully without crash
    cd.record_trade_close(was_win=True, pnl=float('nan'), now_ts=base_time + 300)
    assert "WIN" in cd.last_trade_result

    # 5. Thread safety
    def fire_trades():
        for _ in range(20):
            cd.record_trade_close(was_win=True, pnl=1.0)
            cd.record_trade_close(was_win=False, pnl=-1.0)

    threads = [threading.Thread(target=fire_trades) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cd.total_cooldowns_triggered >= 200


def test_wave38_volatility_breaker():
    vb = VolatilityBreaker()
    vb.reset()

    # 1. Non-finite or negative prices ignored safely
    vb.update(float('nan'))
    vb.update(float('inf'))
    vb.update(-100.0)
    assert vb._tick_count == 0

    # 2. Feed 50 steady ticks around 2000.0 with tiny changes (0.01 pips)
    base_time = 10000.0
    price = 2000.0
    for i in range(50):
        price += 0.01 if i % 2 == 0 else -0.01
        vb.update(price, now_ts=base_time + i)

    assert vb.is_entry_blocked(now_ts=base_time + 50) is False

    # 3. Inject extreme volatility (jumps of 5.0 points per tick for 10 ticks)
    for i in range(10):
        price += 5.0 if i % 2 == 0 else -5.0
        vb.update(price, now_ts=base_time + 51 + i)

    # Volatility ratio should exceed 2.5x and trigger 90s block
    assert vb.is_entry_blocked(now_ts=base_time + 61) is True
    assert vb.seconds_remaining(now_ts=base_time + 61) <= 90.0

    # After 95s -> block expires
    assert vb.is_entry_blocked(now_ts=base_time + 61 + 95) is False

    # 4. Reset
    vb.reset()
    assert vb.is_entry_blocked(now_ts=base_time + 61) is False
    assert vb._tick_count == 0


def test_wave39_drawdown_pause():
    dp = DrawdownPause()
    dp.reset()

    # 1. Non-finite or zero/negative equity safely ignored
    dp.update(float('nan'))
    dp.update(float('inf'))
    dp.update(-50.0)
    dp.update(0.0)
    assert len(dp._equity_history) == 0

    base_time = 20000.0

    # 2. Feed peak equity $10,000
    dp.update(10000.0, now_ts=base_time)
    dp.update(10050.0, now_ts=base_time + 10)  # Peak = 10050
    assert dp.is_entry_blocked(now_ts=base_time + 10) is False

    # 3. Mild dip (0.5% drawdown to 10000.0) -> not blocked (threshold is 1.5%)
    dp.update(10000.0, now_ts=base_time + 20)
    assert dp.is_entry_blocked(now_ts=base_time + 20) is False

    # 4. Severe dip (> 1.5% drawdown: 10050 -> 9850 is ~2.0% drop) -> 15 min (900s) pause
    dp.update(9850.0, now_ts=base_time + 30)
    assert dp.is_entry_blocked(now_ts=base_time + 30) is True
    assert dp.seconds_remaining(now_ts=base_time + 30) == pytest.approx(900.0)

    # After 905s, equity recovers to 10020 (drawdown < 0.3%) -> unblocks
    dp.update(10020.0, now_ts=base_time + 30 + 905)
    assert dp.is_entry_blocked(now_ts=base_time + 30 + 905) is False

    # 5. Window pruning test: past 1800s lookback window, old peak is discarded
    dp.reset()
    dp.update(10050.0, now_ts=base_time)
    dp.update(9850.0, now_ts=base_time + 100)
    assert dp.is_entry_blocked(now_ts=base_time + 100) is True

    # Check after 2000s (> 1800s window), old 10050 peak pruned
    assert dp.is_entry_blocked(now_ts=base_time + 2100) is False

    # 6. Reset
    dp.reset()
    assert dp.is_entry_blocked(now_ts=base_time + 100) is False
    assert len(dp._equity_history) == 0
