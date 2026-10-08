"""
RiskGuard - Fail-closed defense-in-depth risk management engine for MT5 trading bot.
Enforces 10 safety invariants before any order reaches the execution pipeline.
All limits only tighten, never loosen. Fail-closed on all errors or invalid data.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional, Union


class Decision(dict):
    """
    Decision outcome returned by RiskGuard.check_order().
    Subclasses dict so that both dict indexing (decision['allowed'])
    and attribute access (decision.allowed) work seamlessly.
    """
    def __init__(self, allowed: bool, reason: str, lot: float = 0.0):
        super().__init__(allowed=allowed, reason=reason, lot=lot)
        self.allowed = bool(allowed)
        self.reason = str(reason)
        self.lot = float(lot)

    def __bool__(self):
        return self.allowed

    def __repr__(self):
        return f"Decision(allowed={self.allowed}, reason='{self.reason}', lot={self.lot})"


def _is_valid_num(val: Any) -> bool:
    """Helper to ensure value is a valid numeric type and not bool, NaN, inf, or None."""
    if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return not (math.isnan(val) or math.isinf(val))


class RiskGuard:
    """
    Fail-closed risk guardian enforcing 10 critical safety invariants.
    """
    def __init__(
        self,
        config: dict,
        state_path: Optional[Union[str, Path]] = None,
        clock: Callable[[], float] = time.time
    ):
        self.config = dict(config) if config else {}
        self.clock = clock

        # State persistence path
        if state_path is not None:
            self.state_path = Path(state_path)
        elif "risk_state_path" in self.config:
            self.state_path = Path(self.config["risk_state_path"])
        else:
            self.state_path = Path(__file__).resolve().parent.parent / "risk_state.json"

        # Kill switch file path
        if "kill_switch_path" in self.config:
            self.kill_switch_path = Path(self.config["kill_switch_path"])
        else:
            self.kill_switch_path = Path(__file__).resolve().parent.parent / "KILL_SWITCH"

        self.state: Dict[str, Any] = {}
        self._load_state()

    def _get_current_utc_date(self) -> str:
        """Returns the current date in YYYY-MM-DD format according to UTC."""
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self) -> None:
        """Loads persistent state or initializes a clean one."""
        today = self._get_current_utc_date()
        default_state = {
            "date_utc": today,
            "daily_pnl": 0.0,
            "daily_loss_halted": False,
            "balance_floor_halted": False,
            "trade_count_today": 0,
            "last_trade_time": 0.0,
        }

        if not self.state_path.exists():
            self.state = default_state
            self._save_state()
            return

        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                self.state = default_state
                self._save_state()
                return

            saved_date = data.get("date_utc", "")
            # Invariant 5: balance_floor_halted is PERMANENT until manual reset!
            balance_floor_halted = bool(data.get("balance_floor_halted", False))

            if saved_date != today:
                # New UTC day: reset daily counters and daily loss halt.
                # Balance-floor halt remains permanent!
                self.state = {
                    "date_utc": today,
                    "daily_pnl": 0.0,
                    "daily_loss_halted": False,
                    "balance_floor_halted": balance_floor_halted,
                    "trade_count_today": 0,
                    "last_trade_time": float(data.get("last_trade_time", 0.0)),
                }
                self._save_state()
            else:
                self.state = {
                    "date_utc": today,
                    "daily_pnl": float(data.get("daily_pnl", 0.0)),
                    "daily_loss_halted": bool(data.get("daily_loss_halted", False)),
                    "balance_floor_halted": balance_floor_halted,
                    "trade_count_today": int(data.get("trade_count_today", 0)),
                    "last_trade_time": float(data.get("last_trade_time", 0.0)),
                }
        except Exception:
            # Invariant 9: Fail closed if an existing state file is corrupted
            self.state = {
                "date_utc": today,
                "daily_pnl": -999999.0,
                "daily_loss_halted": True,
                "balance_floor_halted": True,
                "trade_count_today": 999999,
                "last_trade_time": 0.0,
            }

    def _save_state(self) -> None:
        """Persists risk state atomically."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            tmp_path.replace(self.state_path)
        except Exception:
            pass

    def _check_day_rollover(self) -> None:
        """Checks if UTC day has changed and resets daily metrics if so."""
        today = self._get_current_utc_date()
        if self.state.get("date_utc") != today:
            # Daily reset only on UTC day rollover
            balance_floor_halted = bool(self.state.get("balance_floor_halted", False))
            self.state["date_utc"] = today
            self.state["daily_pnl"] = 0.0
            self.state["daily_loss_halted"] = False
            # Balance-floor halt remains permanent!
            self.state["balance_floor_halted"] = balance_floor_halted
            self.state["trade_count_today"] = 0
            self._save_state()

    def record_trade(self, pnl: float, timestamp: Optional[float] = None) -> None:
        """
        Records a completed trade's PnL to update daily metrics.
        """
        try:
            self._check_day_rollover()
            self.state["daily_pnl"] = round(self.state.get("daily_pnl", 0.0) + float(pnl), 2)
            self.state["trade_count_today"] = self.state.get("trade_count_today", 0) + 1
            now = float(timestamp if timestamp is not None else self.clock())
            self.state["last_trade_time"] = now

            max_daily_loss = float(self.config.get("max_daily_loss_usd", 200.0))
            if self.state["daily_pnl"] <= -max_daily_loss:
                self.state["daily_loss_halted"] = True

            self._save_state()
        except Exception:
            pass

    def reset_balance_floor(self) -> None:
        """Manual reset for balance floor halt."""
        self.state["balance_floor_halted"] = False
        self._save_state()

    def reset_daily_loss(self) -> None:
        """Manual reset for daily loss halt."""
        self.state["daily_loss_halted"] = False
        self.state["daily_pnl"] = 0.0
        self._save_state()

    def check_order(self, order: dict, account: dict, market: dict) -> Decision:
        """
        Enforces 10 safety invariants before allowing an order.
        Fail-closed on any error or missing/invalid field.
        """
        try:
            # Invariant 9: Fail-closed on input types
            if not isinstance(order, dict) or not isinstance(account, dict) or not isinstance(market, dict):
                return Decision(False, "FAIL_CLOSED: order, account, and market must be dictionaries", 0.0)

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 4: Kill switch
            # ─────────────────────────────────────────────────────────────────
            kill_flag = bool(self.config.get("kill_switch", False))
            if kill_flag or self.kill_switch_path.exists():
                return Decision(False, "KILL_SWITCH_ACTIVE: Order rejected due to active kill switch", 0.0)

            # Check day rollover
            self._check_day_rollover()

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 5: Daily loss halt and Balance floor
            # ─────────────────────────────────────────────────────────────────
            raw_balance = account.get("balance")
            if not _is_valid_num(raw_balance) or float(raw_balance) < 0:
                return Decision(False, "FAIL_CLOSED: Invalid or missing account balance", 0.0)
            balance = float(raw_balance)

            min_balance_usd = float(self.config.get("min_balance_usd", 9700.0))
            if balance < min_balance_usd or self.state.get("balance_floor_halted", False):
                self.state["balance_floor_halted"] = True
                self._save_state()
                return Decision(
                    False,
                    f"BALANCE_FLOOR_HALTED: Balance ${balance:,.2f} < floor ${min_balance_usd:,.2f} (permanent halt)",
                    0.0
                )

            max_daily_loss_usd = float(self.config.get("max_daily_loss_usd", 200.0))
            persisted_daily_pnl = float(self.state.get("daily_pnl", 0.0))
            # Also account for any daily_pnl reported directly in account dict
            acct_daily_pnl = account.get("daily_pnl", persisted_daily_pnl)
            if isinstance(acct_daily_pnl, (int, float)) and not math.isnan(acct_daily_pnl):
                effective_daily_pnl = min(persisted_daily_pnl, float(acct_daily_pnl))
            else:
                effective_daily_pnl = persisted_daily_pnl

            if effective_daily_pnl <= -max_daily_loss_usd or self.state.get("daily_loss_halted", False):
                self.state["daily_loss_halted"] = True
                self._save_state()
                return Decision(
                    False,
                    f"DAILY_LOSS_HALTED: Daily loss ${-effective_daily_pnl:,.2f} exceeds limit ${max_daily_loss_usd:,.2f}",
                    0.0
                )

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 6: Max open positions, max trades/day, min time cooldown
            # ─────────────────────────────────────────────────────────────────
            # Max open positions
            max_positions_limit = int(self.config.get("max_positions_per_session", self.config.get("max_open_positions", 3)))
            open_positions = account.get("open_positions", 0)
            if isinstance(open_positions, list):
                num_open_positions = len(open_positions)
            elif isinstance(open_positions, (int, float)):
                num_open_positions = int(open_positions)
            else:
                return Decision(False, "FAIL_CLOSED: Invalid open_positions format", 0.0)

            if num_open_positions >= max_positions_limit:
                return Decision(
                    False,
                    f"MAX_POSITIONS_REACHED: Currently {num_open_positions} open positions >= max {max_positions_limit}",
                    0.0
                )

            # Max trades per day
            max_trades_limit = int(self.config.get("max_trades_per_day", self.config.get("max_trades_today", 1000)))
            trades_today = int(self.state.get("trade_count_today", 0))
            if trades_today >= max_trades_limit:
                return Decision(
                    False,
                    f"MAX_TRADES_PER_DAY_REACHED: Today trades {trades_today} >= max {max_trades_limit}",
                    0.0
                )

            # Min time between trades cooldown
            min_cooldown_sec = float(self.config.get("min_time_between_trades_sec", self.config.get("min_time_between_trades", 0.0)))
            if min_cooldown_sec > 0:
                now = float(self.clock())
                last_time = float(self.state.get("last_trade_time", 0.0))
                if last_time > 0 and (now - last_time) < min_cooldown_sec:
                    return Decision(
                        False,
                        f"COOLDOWN_ACTIVE: {now - last_time:.1f}s elapsed < min cooldown {min_cooldown_sec:.1f}s",
                        0.0
                    )

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 7: Spread guard
            # ─────────────────────────────────────────────────────────────────
            raw_spread_filter = self.config.get("spread_filter_pips", 3.0)
            spread_filter_pips = float(raw_spread_filter) if _is_valid_num(raw_spread_filter) and float(raw_spread_filter) > 0 else 3.0

            spread_val = market.get("spread_pips", market.get("spread"))
            if not _is_valid_num(spread_val):
                return Decision(False, "FAIL_CLOSED: Missing or invalid spread in market data", 0.0)
            spread_pips = float(spread_val)

            if spread_pips < 0.0:
                return Decision(False, f"FAIL_CLOSED: Negative spread ({spread_pips:.2f} pips) invalid", 0.0)

            if spread_pips > spread_filter_pips:
                return Decision(
                    False,
                    f"SPREAD_EXCEEDED: Spread {spread_pips:.2f} pips > filter {spread_filter_pips:.2f} pips",
                    0.0
                )

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 8: Stale tick guard
            # ─────────────────────────────────────────────────────────────────
            raw_max_age = self.config.get("max_tick_age_sec", 5.0)
            max_tick_age_sec = float(raw_max_age) if _is_valid_num(raw_max_age) and float(raw_max_age) > 0 else 5.0

            tick_time = market.get("tick_time", market.get("time"))
            if not _is_valid_num(tick_time):
                return Decision(False, "FAIL_CLOSED: Missing or invalid tick timestamp in market data", 0.0)

            tick_time_val = float(tick_time)
            if tick_time_val <= 0.0:
                return Decision(False, "FAIL_CLOSED: Non-positive tick timestamp", 0.0)

            # Normalize millisecond epoch timestamp if detected
            if tick_time_val > 1e11:
                tick_time_val = tick_time_val / 1000.0

            now = float(self.clock())
            tick_age = now - tick_time_val
            if tick_age > max_tick_age_sec:
                return Decision(
                    False,
                    f"STALE_TICK: Tick age {tick_age:.2f}s > max allowable {max_tick_age_sec:.2f}s",
                    0.0
                )
            if tick_age < -10.0:
                return Decision(False, f"FAIL_CLOSED: Tick timestamp from the future ({tick_age:.2f}s)", 0.0)

            # ─────────────────────────────────────────────────────────────────
            # INVARIANT 1: Mandatory Stop Loss (SL Lazmi)
            # ─────────────────────────────────────────────────────────────────
            # Resolve order direction
            raw_type = order.get("order_type", order.get("type", order.get("direction")))
            if raw_type is None:
                return Decision(False, "FAIL_CLOSED: Missing order type/direction", 0.0)

            if str(raw_type).upper() in ("BUY", "0", "ORDER_TYPE_BUY") or raw_type == 0:
                direction = "BUY"
            elif str(raw_type).upper() in ("SELL", "1", "ORDER_TYPE_SELL") or raw_type == 1:
                direction = "SELL"
            else:
                return Decision(False, f"FAIL_CLOSED: Unrecognized order type '{raw_type}'", 0.0)

            # Price check
            raw_price = order.get("price")
            if raw_price is None:
                raw_price = market.get("ask") if direction == "BUY" else market.get("bid")
            if not _is_valid_num(raw_price) or float(raw_price) <= 0:
                return Decision(False, "FAIL_CLOSED: Missing or invalid order price", 0.0)
            price = float(raw_price)

            # SL check
            raw_sl = order.get("sl")
            if not _is_valid_num(raw_sl) or float(raw_sl) <= 0:
                return Decision(False, "MANDATORY_SL_VIOLATION: Order has no valid stop loss", 0.0)
            sl = float(raw_sl)

            # Directional alignment check
            if direction == "BUY" and sl >= price:
                return Decision(False, f"SL_WRONG_SIDE: BUY order SL ({sl}) must be strictly below entry price ({price})", 0.0)
            elif direction == "SELL" and sl <= price:
                return Decision(False, f"SL_WRONG_SIDE: SELL order SL ({sl}) must be strictly above entry price ({price})", 0.0)

            # SL Distance validation
            if "pip_size" in market and (not _is_valid_num(market["pip_size"]) or float(market["pip_size"]) <= 0):
                return Decision(False, "FAIL_CLOSED: Invalid pip_size in market data", 0.0)
            raw_pip = market.get("pip_size", self.config.get("pip_size", 0.1))
            pip_size = float(raw_pip) if _is_valid_num(raw_pip) and float(raw_pip) > 0 else 0.1

            sl_distance = abs(price - sl)
            sl_pips = sl_distance / pip_size

            raw_min_sl = self.config.get("min_sl_pips", 5.0)
            min_sl_pips = float(raw_min_sl) if _is_valid_num(raw_min_sl) and float(raw_min_sl) > 0 else 5.0

            raw_max_sl = self.config.get("max_sl_pips", 200.0)
            max_sl_pips = float(raw_max_sl) if _is_valid_num(raw_max_sl) and float(raw_max_sl) > 0 else 200.0

            if sl_pips < min_sl_pips:
                return Decision(
                    False,
                    f"SL_DISTANCE_TOO_SMALL: SL distance {sl_pips:.1f} pips < min {min_sl_pips:.1f} pips",
                    0.0
                )
            if sl_pips > max_sl_pips:
                return Decision(
                    False,
                    f"SL_DISTANCE_TOO_LARGE: SL distance {sl_pips:.1f} pips > max {max_sl_pips:.1f} pips",
                    0.0
                )

            # ─────────────────────────────────────────────────────────────────
            # INVARIANTS 2, 3 & 10: Lot cap, Risk-per-trade, and Tightening Normalization
            # ─────────────────────────────────────────────────────────────────
            raw_lot = order.get("lots", order.get("lot_size", self.config.get("lot_size", 0.02)))
            if not _is_valid_num(raw_lot) or float(raw_lot) <= 0:
                return Decision(False, "FAIL_CLOSED: Invalid requested lot size", 0.0)
            working_lot = float(raw_lot)

            # Broker specifications
            if "min_lot" in market and (not _is_valid_num(market["min_lot"]) or float(market["min_lot"]) <= 0):
                return Decision(False, "FAIL_CLOSED: Invalid min_lot in market data", 0.0)
            raw_min_lot = market.get("min_lot", self.config.get("min_lot_size", 0.01))
            broker_min_lot = float(raw_min_lot) if _is_valid_num(raw_min_lot) and float(raw_min_lot) > 0 else 0.01

            if "max_lot" in market and (not _is_valid_num(market["max_lot"]) or float(market["max_lot"]) <= 0):
                return Decision(False, "FAIL_CLOSED: Invalid max_lot in market data", 0.0)
            raw_max_lot = market.get("max_lot", self.config.get("broker_max_lot", 100.0))
            broker_max_lot = float(raw_max_lot) if _is_valid_num(raw_max_lot) and float(raw_max_lot) > 0 else 100.0

            if "lot_step" in market and (not _is_valid_num(market["lot_step"]) or float(market["lot_step"]) <= 0):
                return Decision(False, "FAIL_CLOSED: Invalid lot_step in market data", 0.0)
            raw_step = market.get("lot_step", self.config.get("lot_step", 0.01))
            lot_step = float(raw_step) if _is_valid_num(raw_step) and float(raw_step) > 0 else 0.01

            raw_cfg_max = self.config.get("max_lot_size", 0.10)
            config_max_lot = float(raw_cfg_max) if _is_valid_num(raw_cfg_max) and float(raw_cfg_max) > 0 else 0.10

            # Invariant 10: Guard only tightens: effective limit = min(config, broker)
            effective_max_lot = min(config_max_lot, broker_max_lot)
            working_lot = min(working_lot, effective_max_lot)

            # Invariant 3: Risk per trade dollar cap
            # formula: lot * sl_distance * contract_size <= (risk_per_trade_pct / 100) * balance
            raw_risk_pct = self.config.get("risk_per_trade_pct", 1.0)
            risk_per_trade_pct = float(raw_risk_pct) if _is_valid_num(raw_risk_pct) and float(raw_risk_pct) > 0 else 1.0

            if "contract_size" in market and (not _is_valid_num(market["contract_size"]) or float(market["contract_size"]) <= 0):
                return Decision(False, "FAIL_CLOSED: Invalid contract_size in market data", 0.0)
            raw_contract = self.config.get("contract_size", market.get("contract_size", 100.0))
            contract_size = float(raw_contract) if _is_valid_num(raw_contract) and float(raw_contract) > 0 else 100.0

            max_risk_dollars = (risk_per_trade_pct / 100.0) * balance
            dollar_risk = working_lot * sl_distance * contract_size

            if dollar_risk > max_risk_dollars:
                # Reduce lot size to safe ceiling
                safe_raw_lot = max_risk_dollars / (sl_distance * contract_size)
                working_lot = min(working_lot, safe_raw_lot)

            # Invariant 2: Normalize lot size to lot_step (floor down)
            steps = math.floor(round(working_lot / lot_step, 6))
            quantized_lot = round(steps * lot_step, 4)

            # Re-verify against broker limits and effective max lot
            if quantized_lot < broker_min_lot:
                return Decision(
                    False,
                    f"RISK_CAP_EXCEEDED: Allowed lot {quantized_lot} below broker minimum lot {broker_min_lot}",
                    0.0
                )

            if quantized_lot > effective_max_lot:
                quantized_lot = effective_max_lot

            # All 10 invariants satisfied!
            return Decision(True, "ORDER_APPROVED", quantized_lot)

        except Exception as exc:
            # Invariant 9: Fail-closed on ANY unexpected exception
            return Decision(False, f"FAIL_CLOSED: Unexpected exception: {type(exc).__name__}: {str(exc)}", 0.0)
