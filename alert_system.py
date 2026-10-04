#!/usr/bin/env python3
"""
Scalping Robot V5 - Real-Time Alert & Notification System
Monitors live trading metrics, evaluates risk and performance conditions,
rate-limits notifications, and maintains live alert status.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

# Base Directories and Paths
BASE_DIR = Path(r"E:\scalping-robot-v5")
STATUS_FILE = BASE_DIR / "live_status.json"
ALERTS_LOG_FILE = BASE_DIR / "alerts.log"
ALERT_STATUS_FILE = BASE_DIR / "alert_status.json"
TRADES_LOG_FILE = BASE_DIR / "trades.log"

# Logger Configuration
logger = logging.getLogger("AlertSystem")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # Always log to file
    try:
        fh = logging.FileHandler(BASE_DIR / "alerts_system_internal.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    except Exception:
        pass

    # Log to stdout only if available (prevents crashes under pythonw.exe)
    if sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(sh)


def format_number(val: float, is_currency: bool = False) -> str:
    """Format numbers cleanly (e.g. $150 or $175.50, and 65% or 64.5%)."""
    if val == int(val):
        formatted = f"{int(val)}"
    else:
        if is_currency:
            formatted = f"{val:.2f}"
        else:
            formatted = f"{val:.2f}".rstrip("0").rstrip(".")
    return f"${formatted}" if is_currency else formatted


def parse_timestamp_utc(ts: Any) -> Optional[datetime]:
    """Parse various timestamp formats into a UTC datetime."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        ts_str = str(ts).strip()
        if not ts_str:
            return None
        # Numeric string
        try:
            val = float(ts_str)
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except ValueError:
            pass

        # Trailing 'Z'
        if ts_str.endswith("Z"):
            dt = datetime.fromisoformat(ts_str[:-1])
            return dt.replace(tzinfo=timezone.utc)

        # Standard ISO format
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # Log format 'YYYY-MM-DD HH:MM:SS'
        for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                base_part = ts_str.split(",")[0] if fmt == "%Y-%m-%d %H:%M:%S" and "," in ts_str else ts_str
                dt = datetime.strptime(base_part, fmt)
                return dt.astimezone().astimezone(timezone.utc)
            except Exception:
                pass
    except Exception:
        pass
    return None


class AlertSystem:
    """
    Real-Time Alert and Notification System for Scalping Robot V5.
    Reads live_status.json every 60 seconds, checks thresholds,
    rate-limits notifications to max once per 15 minutes per alert type,
    writes to alerts.log, and publishes alert_status.json.
    """

    def __init__(
        self,
        status_file: Optional[Path | str] = None,
        alerts_log_file: Optional[Path | str] = None,
        alert_status_file: Optional[Path | str] = None,
        check_interval: int = 60,
        rate_limit_minutes: int = 15,
    ):
        self.status_file = Path(status_file) if status_file else STATUS_FILE
        self.alerts_log_file = Path(alerts_log_file) if alerts_log_file else ALERTS_LOG_FILE
        self.alert_status_file = Path(alert_status_file) if alert_status_file else ALERT_STATUS_FILE
        self.check_interval = int(check_interval)
        self.rate_limit_seconds = int(rate_limit_minutes * 60)

        # Rate limiting dictionary: alert_type -> float (epoch timestamp)
        self.last_alert_times: Dict[str, float] = {}

        # Tracking state
        self.last_alert: str = ""
        self.total_alerts_today: int = 0
        self.current_date = datetime.now().date()
        self.peak_equity: float = 10000.0
        self.system_start_time = datetime.now(timezone.utc)
        self.running: bool = False

        # Load persisted alert status if exists
        self._load_existing_status()

    def _load_existing_status(self):
        """Restore total_alerts_today and last_alert if alert_status.json exists for today."""
        if self.alert_status_file.exists():
            try:
                with open(self.alert_status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.last_alert = str(data.get("last_alert", ""))
                saved_date = data.get("date")
                today_str = str(self.current_date)
                if saved_date == today_str:
                    self.total_alerts_today = int(data.get("total_alerts_today", 0))
                else:
                    self.total_alerts_today = 0
            except Exception as e:
                logger.debug(f"Could not load previous alert status: {e}")
        else:
            # Initialize alert_status.json if missing
            self._write_alert_status("OK")

    def read_live_status(self) -> Optional[Dict[str, Any]]:
        """Safely read live_status.json with retry handling."""
        if not self.status_file.exists():
            logger.warning(f"Status file not found: {self.status_file}")
            return None

        for attempt in range(5):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
            except Exception as e:
                logger.error(f"Unexpected error reading {self.status_file}: {e}")
                break
        return None

    def is_active_session(self, data: Dict[str, Any]) -> bool:
        """
        Check if trading session is active:
        1. If explicitly provided in data ('active_session', 'in_trading_session', 'session_active').
        2. If robot status is STOPPED, HALTED, or trading_halted is True -> False.
        3. Forex Tokyo/London/New York sessions with 30-min buffer or ACTIVE_SCALPING.
        """
        if "active_session" in data:
            return bool(data["active_session"])
        if "in_trading_session" in data:
            return bool(data["in_trading_session"])
        if "session_active" in data:
            return bool(data["session_active"])

        if data.get("trading_halted", False):
            return False

        status = str(data.get("status", "")).upper()
        if status in ["STOPPED", "HALTED", "INACTIVE", "PAUSED", "OFFLINE"]:
            return False

        now_utc = datetime.now(timezone.utc)
        utc_hour = now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
        buffer_hours = 0.5

        # Tokyo (00:00-09:00 UTC), London (08:00-17:00 UTC), NY (13:00-22:00 UTC)
        in_tokyo = (utc_hour >= (24.0 - buffer_hours)) or (utc_hour < (9.0 + buffer_hours))
        in_london = (8.0 - buffer_hours) <= utc_hour < (17.0 + buffer_hours)
        in_ny = (13.0 - buffer_hours) <= utc_hour < (22.0 + buffer_hours)

        return in_tokyo or in_london or in_ny or (status == "ACTIVE_SCALPING")

    def get_time_since_last_trade_minutes(self, data: Dict[str, Any]) -> float:
        """Find the most recent trade time and calculate minutes elapsed."""
        now_utc = datetime.now(timezone.utc)
        candidate_times: List[datetime] = []

        # 1. Direct field in live_status.json
        for field in ("last_trade_time", "last_trade_timestamp", "latest_trade_time"):
            if field in data and data[field]:
                dt = parse_timestamp_utc(data[field])
                if dt:
                    candidate_times.append(dt)

        # 2. Trades list in live_status.json
        for list_key in ("last_trades", "recent_trades", "trades_history"):
            trades = data.get(list_key, [])
            if isinstance(trades, list):
                for t in trades:
                    if isinstance(t, dict):
                        for ts_key in ("timestamp", "close_time", "open_time", "time"):
                            if ts_key in t and t[ts_key]:
                                dt = parse_timestamp_utc(t[ts_key])
                                if dt:
                                    candidate_times.append(dt)

        # 3. Open positions in live_status.json
        positions = data.get("open_positions", [])
        if isinstance(positions, list):
            for p in positions:
                if isinstance(p, dict):
                    if "open_time" in p and p["open_time"]:
                        dt = parse_timestamp_utc(p["open_time"])
                        if dt:
                            candidate_times.append(dt)

        # 4. Check trades.log if available
        if not candidate_times and TRADES_LOG_FILE.exists():
            try:
                with open(TRADES_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for line in reversed(lines[-20:]):
                    line = line.strip()
                    if line:
                        parts = line.split()
                        if len(parts) >= 2:
                            ts_str = f"{parts[0]} {parts[1]}"
                            dt = parse_timestamp_utc(ts_str)
                            if dt:
                                candidate_times.append(dt)
                                break
            except Exception:
                pass

        if candidate_times:
            newest_trade = max(candidate_times)
            elapsed_sec = (now_utc - newest_trade).total_seconds()
            return max(0.0, elapsed_sec / 60.0)

        # If no trades have ever occurred, check session/robot start time or fallback to system start
        for start_key in ("session_start", "start_time", "robot_start_time"):
            if start_key in data and data[start_key]:
                dt = parse_timestamp_utc(data[start_key])
                if dt:
                    elapsed_sec = (now_utc - dt).total_seconds()
                    return max(0.0, elapsed_sec / 60.0)

        # Elapsed since AlertSystem started
        elapsed_sec = (now_utc - self.system_start_time).total_seconds()
        return max(0.0, elapsed_sec / 60.0)

    def evaluate_conditions(self, data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        """
        Evaluate all 6 alert conditions against live status data:
        1. Win rate dropped below 70%: 'ALERT: Win rate critical: X%'
        2. Daily loss > $150: 'ALERT: Daily loss danger: $X'
        3. No trades in 90 min during active session: 'ALERT: Trading stalled'
        4. Balance below $9800: 'ALERT: Balance critical: $X'
        5. Equity drawdown > 5%: 'ALERT: Equity drawdown: X%'
        6. Open positions > 4: 'ALERT: Too many positions: N'

        Returns:
            active_conditions: List of dicts with keys (type, level, message)
            overall_status: 'OK', 'WARNING', or 'CRITICAL'
        """
        active_conditions: List[Dict[str, Any]] = []

        # 1. Win Rate Check
        raw_win_rate = data.get("win_rate_pct", data.get("win_rate"))
        total_trades = data.get("total_trades")
        if raw_win_rate is not None:
            win_rate = float(raw_win_rate)
            # Normalize ratio 0.0-1.0 if applicable
            if 0.0 < win_rate <= 1.0 and total_trades and total_trades > 0:
                win_rate *= 100.0

            # Alert if win rate dropped below 70%
            # If total_trades is 0 and win_rate is 0.0 on a fresh start, do not false-alarm
            if win_rate < 70.0 and (total_trades is None or total_trades > 0 or win_rate > 0.0):
                formatted_wr = format_number(win_rate)
                active_conditions.append({
                    "type": "win_rate_critical",
                    "level": "CRITICAL",
                    "message": f"ALERT: Win rate critical: {formatted_wr}%",
                })

        # 2. Daily Loss Check
        raw_daily_loss = data.get("daily_loss")
        raw_daily_pnl = data.get("daily_pnl")
        daily_loss = 0.0
        if raw_daily_loss is not None and float(raw_daily_loss) > 0:
            daily_loss = float(raw_daily_loss)
        elif raw_daily_pnl is not None and float(raw_daily_pnl) < 0:
            daily_loss = abs(float(raw_daily_pnl))

        if daily_loss > 150.0:
            formatted_loss = format_number(daily_loss, is_currency=True)
            active_conditions.append({
                "type": "daily_loss_danger",
                "level": "CRITICAL",
                "message": f"ALERT: Daily loss danger: {formatted_loss}",
            })

        # 3. Trading Stalled Check (No trades in 90 min during active session)
        if self.is_active_session(data):
            minutes_idle = self.get_time_since_last_trade_minutes(data)
            if minutes_idle > 90.0:
                active_conditions.append({
                    "type": "trading_stalled",
                    "level": "WARNING",
                    "message": "ALERT: Trading stalled",
                })

        # 4. Balance Check
        balance = float(data.get("balance", 10000.0))
        if balance < 9800.0:
            formatted_bal = format_number(balance, is_currency=True)
            active_conditions.append({
                "type": "balance_critical",
                "level": "CRITICAL",
                "message": f"ALERT: Balance critical: {formatted_bal}",
            })

        # 5. Equity Drawdown Check
        equity = float(data.get("equity", balance))
        self.peak_equity = max(self.peak_equity, equity, balance)

        # Explicit drawdown in data if provided
        drawdown_pct = 0.0
        if "equity_drawdown_pct" in data:
            drawdown_pct = float(data["equity_drawdown_pct"])
        elif "drawdown_pct" in data:
            drawdown_pct = float(data["drawdown_pct"])
        else:
            # Calculated drawdown
            peak = self.peak_equity
            dd_from_peak = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
            dd_from_balance = ((balance - equity) / balance * 100.0) if (balance > 0 and equity < balance) else 0.0
            drawdown_pct = max(dd_from_peak, dd_from_balance)

        if drawdown_pct > 5.0:
            formatted_dd = format_number(drawdown_pct)
            active_conditions.append({
                "type": "equity_drawdown",
                "level": "CRITICAL",
                "message": f"ALERT: Equity drawdown: {formatted_dd}%",
            })

        # 6. Open Positions Count Check
        positions = data.get("open_positions", [])
        positions_count = int(data.get("open_positions_count", len(positions) if isinstance(positions, list) else 0))
        if positions_count > 4:
            active_conditions.append({
                "type": "too_many_positions",
                "level": "WARNING",
                "message": f"ALERT: Too many positions: {positions_count}",
            })

        # Determine overall system status
        has_critical = any(cond["level"] == "CRITICAL" for cond in active_conditions)
        has_warning = any(cond["level"] == "WARNING" for cond in active_conditions)

        if has_critical:
            overall_status = "CRITICAL"
        elif has_warning:
            overall_status = "WARNING"
        else:
            overall_status = "OK"

        return active_conditions, overall_status

    def _log_alert_to_file(self, alert_msg: str):
        """Append alert with timestamp to alerts.log."""
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{ts_str}] {alert_msg}"
        print(log_entry, flush=True)

        try:
            self.alerts_log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.alerts_log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            logger.error(f"Failed to append to {self.alerts_log_file}: {e}")

    def _write_alert_status(self, status: str):
        """Write summary atomically to alert_status.json."""
        summary = {
            "last_alert": self.last_alert,
            "total_alerts_today": self.total_alerts_today,
            "status": status,
            "date": str(self.current_date),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        temp_path = self.alert_status_file.parent / f"{self.alert_status_file.name}.tmp.{os.getpid()}"
        try:
            self.alert_status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (AttributeError, OSError):
                    pass
            os.replace(temp_path, self.alert_status_file)
        except Exception as e:
            logger.error(f"Failed writing {self.alert_status_file}: {e}")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

    def check_alerts(self, live_data: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Executes one evaluation cycle.
        Returns the list of alerts fired in this cycle.
        """
        # Daily counter reset on date rollover
        now_date = datetime.now().date()
        if now_date != self.current_date:
            self.current_date = now_date
            self.total_alerts_today = 0

        data = live_data if live_data is not None else self.read_live_status()
        if data is None:
            return []

        active_conditions, overall_status = self.evaluate_conditions(data)
        now_ts = time.time()
        triggered_alerts: List[str] = []

        for cond in active_conditions:
            cond_type = cond["type"]
            msg = cond["message"]

            # Rate limit check: max once per 15 minutes for the same alert type
            last_time = self.last_alert_times.get(cond_type)
            is_rate_limited = False

            if last_time is not None:
                if isinstance(last_time, (int, float)):
                    elapsed = now_ts - float(last_time)
                elif isinstance(last_time, datetime):
                    elapsed = (datetime.now() - last_time).total_seconds()
                else:
                    elapsed = now_ts - float(last_time)

                if elapsed < self.rate_limit_seconds:
                    is_rate_limited = True

            if not is_rate_limited:
                # Update last alert timestamp
                self.last_alert_times[cond_type] = now_ts
                self._log_alert_to_file(msg)
                self.last_alert = msg
                self.total_alerts_today += 1
                triggered_alerts.append(msg)

        # Write summary status to alert_status.json
        self._write_alert_status(overall_status)

        return triggered_alerts

    def run(self):
        """Infinite loop executing check_alerts every 60 seconds."""
        logger.info(f"AlertSystem started. Monitoring {self.status_file} every {self.check_interval}s...")
        self.running = True

        while self.running:
            try:
                self.check_alerts()
            except KeyboardInterrupt:
                logger.info("AlertSystem stopped by user.")
                break
            except Exception as e:
                logger.error(f"Error in alert check cycle: {e}", exc_info=True)

            try:
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                logger.info("AlertSystem stopped during sleep.")
                break


def main():
    system = AlertSystem()
    system.run()


if __name__ == "__main__":
    main()
