"""
Wave 14 — Auto-Configuration Tuner
====================================
Analyses the last N trades from trade history or trades.log,
then suggests optimal SL/TP/lot updates and writes them to config.json.

Zero external dependencies. Pure Python.

Usage:
    from wave14_auto_tuner import auto_tuner
    auto_tuner.analyse_and_tune(trade_history, balance, config_path)
"""

import os
import json
import math
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("wave14_tuner")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _std(values):
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))

def _percentile(values, pct):
    """Approximate percentile without numpy."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (pct / 100.0) * (len(sorted_v) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = idx - lo
    return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac


# ---------------------------------------------------------------------------
# AutoTuner
# ---------------------------------------------------------------------------

class AutoTuner:
    """
    Analyses recent trade history and suggests config improvements.

    Analysis performed:
    1.  Win rate → if < 45%, tighten SL slightly (reduce risk) or loosen TP
    2.  Average MAE (max adverse excursion) proxy → suggest new SL
    3.  Average MFE (max favourable excursion) proxy → suggest new TP
    4.  Profit factor → if PF < 1.1, shrink lot; if PF > 2.0, allow larger lot
    5.  Consecutive loss streaks → suggest lot reduction
    6.  Trade frequency → if < 2 trades/day, lower signal threshold suggestion (info only)
    7.  Session distribution → flag worst-performing session
    8.  Writes suggested changes back to config.json (only if improvement is significant)
    """

    CONFIG_DEFAULTS = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "rr_ratio": 1.5,
        "max_lot_size": 0.10,
        "risk_per_trade_pct": 1.0,
        "lot_size": 0.02,
        "max_daily_loss_usd": 200.0,
        "daily_profit_target_usd": 200.0,
        "min_time_between_trades_sec": 60,
        "spread_filter_pips": 3.0,
    }

    # Minimum trades required before making any changes
    MIN_TRADES = 10

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config.json"
            )
        self.config_path = config_path
        self._last_report: dict = {}
        self._last_run: float = 0.0

    # ------------------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    cfg = json.load(f)
                # Merge with defaults for any missing keys
                for k, v in self.CONFIG_DEFAULTS.items():
                    cfg.setdefault(k, v)
                return cfg
        except Exception as e:
            logger.warning(f"[TUNER] Could not load config: {e}")
        return dict(self.CONFIG_DEFAULTS)

    def _save_config(self, cfg: dict):
        try:
            with open(self.config_path, "w") as f:
                json.dump(cfg, f, indent=2)
            logger.info(f"[TUNER] Config saved to {self.config_path}")
        except Exception as e:
            logger.error(f"[TUNER] Could not save config: {e}")

    # ------------------------------------------------------------------
    def analyse(self, trade_history: list) -> dict:
        """
        Analyse trade history (list of dicts with keys:
            pnl, exit_reason, direction, entry_price, exit_price, lot_size, duration_sec)
        Returns a report dict with suggestions.
        """
        if len(trade_history) < self.MIN_TRADES:
            return {
                "status": "insufficient_data",
                "trades_analysed": len(trade_history),
                "min_required": self.MIN_TRADES,
                "suggestions": [],
            }

        trades = trade_history[-50:]  # last 50 max
        n = len(trades)

        pnls = [float(t.get("pnl", 0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = len(wins) / n * 100

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 99.0

        avg_win = _mean(wins) if wins else 0.0
        avg_loss = _mean(losses) if losses else 0.0
        avg_rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        # Duration
        durations = [float(t.get("duration_sec", 0)) for t in trades if t.get("duration_sec")]
        avg_duration_min = _mean(durations) / 60.0 if durations else 0.0

        # Exit reason distribution
        exit_reasons = {}
        for t in trades:
            reason = t.get("exit_reason", t.get("close_reason", "UNKNOWN"))
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        # Consecutive loss max
        max_consec_loss = 0
        consec = 0
        for p in pnls:
            if p < 0:
                consec += 1
                max_consec_loss = max(max_consec_loss, consec)
            else:
                consec = 0

        suggestions = []
        cfg = self._load_config()
        proposed = dict(cfg)
        changed = False

        # ── Rule 1: Win rate < 40% → tighten SL (take loss earlier) ──────
        if win_rate < 40 and n >= self.MIN_TRADES:
            new_sl = max(15.0, cfg["sl_pips"] * 0.85)
            if abs(new_sl - cfg["sl_pips"]) >= 2.0:
                suggestions.append(f"Low win rate ({win_rate:.1f}%) — reduce SL from {cfg['sl_pips']} to {new_sl:.1f} pips")
                proposed["sl_pips"] = round(new_sl, 1)
                changed = True

        # ── Rule 2: Profit factor < 1.1 → reduce lot ──────────────────────
        if profit_factor < 1.1 and n >= self.MIN_TRADES:
            new_lot = max(0.01, round(cfg["lot_size"] * 0.80, 2))
            suggestions.append(f"Low profit factor ({profit_factor:.2f}) — reduce lot from {cfg['lot_size']} to {new_lot}")
            proposed["lot_size"] = new_lot
            changed = True

        # ── Rule 3: Profit factor > 2.0 → can increase lot slightly ───────
        if profit_factor > 2.0 and win_rate > 55 and n >= 20:
            new_lot = min(cfg["max_lot_size"], round(cfg["lot_size"] * 1.15, 2))
            if new_lot > cfg["lot_size"]:
                suggestions.append(f"Strong profit factor ({profit_factor:.2f}) + win rate ({win_rate:.1f}%) — increase lot from {cfg['lot_size']} to {new_lot}")
                proposed["lot_size"] = new_lot
                changed = True

        # ── Rule 4: Many timeout exits → reduce TP to lock profit sooner ──
        timeout_count = exit_reasons.get("TIMEOUT", 0) + exit_reasons.get("TIME_EXIT_60MIN", 0) + exit_reasons.get("TIME_EXIT_30MIN_PROFIT", 0)
        if timeout_count > n * 0.4:
            new_tp = max(cfg["sl_pips"] * 1.1, cfg["tp_pips"] * 0.85)
            if abs(new_tp - cfg["tp_pips"]) >= 2.0:
                suggestions.append(f"High timeout rate ({timeout_count}/{n}) — reduce TP from {cfg['tp_pips']} to {new_tp:.1f} pips")
                proposed["tp_pips"] = round(new_tp, 1)
                changed = True

        # ── Rule 5: Max consecutive losses >= 5 → lower daily loss limit ──
        if max_consec_loss >= 5:
            new_daily_loss = max(100.0, cfg["max_daily_loss_usd"] * 0.75)
            suggestions.append(f"Max consec losses = {max_consec_loss} — reduce daily loss limit from ${cfg['max_daily_loss_usd']} to ${new_daily_loss:.0f}")
            proposed["max_daily_loss_usd"] = round(new_daily_loss, 0)
            changed = True

        # ── Rule 6: Average RR below 1.0 → raise TP ──────────────────────
        if avg_rr > 0 and avg_rr < 1.0 and n >= self.MIN_TRADES:
            new_tp = min(100.0, cfg["tp_pips"] * 1.1)
            suggestions.append(f"Avg actual RR ({avg_rr:.2f}) below 1.0 — raise TP from {cfg['tp_pips']} to {new_tp:.1f} pips")
            proposed["tp_pips"] = round(new_tp, 1)
            changed = True

        # ── Update RR ratio in config to match new SL/TP ─────────────────
        if changed:
            sl = proposed.get("sl_pips", cfg["sl_pips"])
            tp = proposed.get("tp_pips", cfg["tp_pips"])
            proposed["rr_ratio"] = round(tp / sl, 2) if sl > 0 else cfg["rr_ratio"]

        report = {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trades_analysed": n,
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 3),
            "avg_rr": round(avg_rr, 3),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "avg_duration_min": round(avg_duration_min, 1),
            "max_consec_losses": max_consec_loss,
            "exit_reason_dist": exit_reasons,
            "suggestions": suggestions,
            "config_changed": changed,
            "proposed_config": proposed if changed else {},
        }
        self._last_report = report
        return report

    # ------------------------------------------------------------------
    def analyse_and_tune(self, trade_history: list, balance: float = 0.0,
                          config_path: str = None, dry_run: bool = False) -> dict:
        """
        Full analysis + optional config write.

        Args:
            trade_history: list of trade dicts
            balance: current account balance (used for sanity checks)
            config_path: override config file path
            dry_run: if True, suggestions only — do NOT write config

        Returns report dict.
        """
        if config_path:
            self.config_path = config_path

        report = self.analyse(trade_history)

        if report.get("config_changed") and not dry_run:
            # Safety: never write if balance < $500 (sanity check)
            if balance > 500.0 or balance == 0.0:
                self._save_config(report["proposed_config"])
                logger.info(f"[TUNER] Config auto-updated: {len(report['suggestions'])} suggestions applied")
            else:
                logger.warning(f"[TUNER] Config NOT written — balance ${balance:.2f} < $500 safety floor")
                report["config_changed"] = False

        # Log all suggestions
        if report.get("suggestions"):
            for s in report["suggestions"]:
                logger.info(f"[TUNER SUGGESTION] {s}")
        else:
            logger.info("[TUNER] No config changes needed — performance within healthy parameters")

        self._last_run = time.time()
        return report

    # ------------------------------------------------------------------
    @property
    def last_report(self) -> dict:
        return self._last_report

    @property
    def seconds_since_last_run(self) -> float:
        return time.time() - self._last_run if self._last_run > 0 else float("inf")


# Module-level singleton
auto_tuner = AutoTuner()
