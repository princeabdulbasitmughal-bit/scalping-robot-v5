import math
import time
from datetime import datetime, timezone
import pytest
from pathlib import Path
import sqlite3

from wave13_ml_predictor import LinearRegressor, MLPredictor
from wave22_equity_curve_halt import EquityCurveHalt
from wave35_overnight_guard import OvernightGuard
from wave33_partial_close import PartialCloseManager
from trade_journal import TradeJournal
from swarm_30_scalping_engine import ScalpingSwarm30


class TestBatch20Hardening:
    def test_wave13_ml_predictor_finite_and_iterable_guards(self):
        reg = LinearRegressor()
        # Non-iterable inputs
        res = reg.fit(123)
        assert res["slope"] == 0.0
        assert res["r_squared"] == 0.0

        # Infinities and NaNs rejected
        res = reg.fit([float('inf'), 2400.0, 2401.0, 2402.0, -float('inf'), float('nan')])
        assert isinstance(res["slope"], float)
        assert math.isfinite(res["slope"])

        # Predictor window bounding
        pred = MLPredictor(window=-5)
        assert pred.window >= 5
        res = pred.predict([float('inf'), 100.0, 101.0, 102.0, 103.0, 104.0])
        assert res["direction"] in ("UP", "DOWN", "NEUTRAL")
        assert math.isfinite(res["slope"])
        assert math.isfinite(res["atr_norm_slope"])

    def test_wave22_equity_curve_halt_rlock_and_nan_guards(self):
        eq = EquityCurveHalt(window=5, loss_threshold_usd=-50.0, slope_threshold=-5.0)
        # NaN / Inf balance guard
        allowed, reason = eq.is_trading_allowed(float('nan'))
        assert allowed is False
        assert "Invalid non-finite balance" in reason

        allowed, reason = eq.is_trading_allowed(float('inf'))
        assert allowed is False

        # NaN trade PnL ignored
        eq.record_trade(float('nan'), won=False)
        eq.record_trade(float('inf'), won=True)
        info = eq.info()
        assert info["trades_in_window"] == 0

        # RLock re-entrancy test
        with eq._lock:
            allowed, _ = eq.is_trading_allowed(10000.0)
            assert allowed is True

    def test_wave35_overnight_guard_now_dt_deterministic(self):
        og = OvernightGuard()
        # Friday 21:00 UTC -> should block entry and force close
        friday_night = datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)
        assert og.is_entry_blocked(now_dt=friday_night) is True
        assert og.should_force_close_all(now_dt=friday_night) is True

        # Tuesday 14:00 UTC -> trading active
        tuesday_day = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
        assert og.is_entry_blocked(now_dt=tuesday_day) is False
        assert og.should_force_close_all(now_dt=tuesday_day) is False

    def test_wave33_partial_close_quantization_and_guards(self):
        pcm = PartialCloseManager()
        # Non-finite inputs return False
        assert pcm.check_position(1, "BUY", float('nan'), 2410.0, 2420.0, 2370.0, 0.02) is False
        assert pcm.check_position(2, "BUY", 2400.0, 2410.0, 2420.0, 2370.0, float('nan')) is False

        # Lot quantization
        lot = pcm.get_partial_lot(0.05, min_lot=0.01, lot_step=0.01)
        assert lot == 0.02

        # Step 0.10 quantization
        lot = pcm.get_partial_lot(0.35, min_lot=0.10, lot_step=0.10)
        assert lot == 0.10 or lot == 0.20

    def test_trade_journal_indexes_created(self, tmp_path):
        test_db = tmp_path / "test_trades.db"
        tj = TradeJournal(db_path=str(test_db))
        conn = sqlite3.connect(str(test_db))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cur.fetchall()}
        conn.close()

        assert "idx_trades_timestamp" in indexes
        assert "idx_trades_symbol_timestamp" in indexes
        assert "idx_trades_exit_reason" in indexes
        assert "idx_daily_summary_date" in indexes

    def test_swarm30_resilient_execution(self):
        swarm = ScalpingSwarm30()
        report = swarm.run_swarm()
        assert report["total_agents"] == 30
        assert report["optimal_count"] >= 25
        assert Path(swarm.root / "reports" / "swarm_30_scalping_report.json").exists()
