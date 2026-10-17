"""
Wave 12: Telegram Alert System
Sends real-time trade notifications via Telegram Bot API.
Zero external dependencies — uses urllib.request (built-in).
Configure via E:\\scalping-robot-v5\\telegram_config.json
"""
import json
import math
import os
import time
import urllib.request
import urllib.parse
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


_BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent
TELEGRAM_CONFIG_PATH = str(_BASE_DIR / "telegram_config.json")
TELEGRAM_LOG_PATH = str(_BASE_DIR / "telegram.log")

# Default config template (edit to enable)
DEFAULT_CONFIG = {
    "bot_token": "",          # Your Telegram bot token from @BotFather
    "chat_id": "",            # Your Telegram chat ID (use @userinfobot)
    "enabled": False,         # Set True after configuring
    "min_alert_interval_sec": 60,  # Rate limit: min seconds between messages
    "alert_on_trade_open": True,
    "alert_on_trade_close": True,
    "alert_on_circuit_breaker": True,
    "alert_on_daily_summary": True,
}


def _log(msg: str):
    try:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with open(TELEGRAM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


class TelegramAlerter:

    def __init__(
        self,
        config_path: Optional[str] = None,
        sender_fn=None
    ):
        self._config_path = str(config_path) if config_path else TELEGRAM_CONFIG_PATH
        self._sender_fn = sender_fn
        self._config = {}
        self._last_sent: float = 0.0
        self._lock = threading.RLock()
        self._sent_messages = []
        self._load_config()

    def _load_config(self):
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            else:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2)
                self._config = DEFAULT_CONFIG.copy()
        except Exception as e:
            self._config = DEFAULT_CONFIG.copy()
            _log(f"Config load error: {e}")

    def update_config(self, new_cfg: dict, persist: bool = False):
        """Update active configuration in a thread-safe manner."""
        with self._lock:
            if isinstance(new_cfg, dict):
                self._config.update(new_cfg)
                if persist:
                    try:
                        tmp = self._config_path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(self._config, f, indent=2)
                        os.replace(tmp, self._config_path)
                    except Exception as e:
                        _log(f"Config persist error: {e}")

    def _send_raw(self, text: str) -> bool:
        """Send message via Telegram Bot API. Returns True on success."""
        token = self._config.get("bot_token", "")
        chat_id = self._config.get("chat_id", "")
        if not token or not chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except Exception as e:
            _log(f"Send error: {e}")
            return False

    def send_alert(self, text: str, force: bool = False, now_ts: Optional[float] = None) -> bool:
        """Rate-limited alert send with thread dispatch and telemetry."""
        if not self._config.get("enabled", False):
            return False
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            min_interval = float(self._config.get("min_alert_interval_sec", 60))
            if not force and now - self._last_sent < min_interval:
                return False

            self._sent_messages.append((now, text))
            if len(self._sent_messages) > 200:
                self._sent_messages.pop(0)

            # Send in background thread to never block main loop
            def _send():
                try:
                    if self._sender_fn is not None:
                        ok = bool(self._sender_fn(text))
                    else:
                        ok = self._send_raw(text)
                    _log(f"{'SENT' if ok else 'FAILED'}: {text[:60]}")
                except Exception as ex:
                    _log(f"Send execution error: {ex}")

            t = threading.Thread(target=_send, daemon=True)
            t.start()
            self._last_sent = now
            return True

    # ── Formatted alert helpers ───────────────────────────────────────────────
    def alert_trade_open(
        self,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        lot: float,
        now_dt: Optional[datetime] = None,
        force: bool = False,
    ):
        if not self._config.get("alert_on_trade_open", True):
            return
        emoji = "BUY" if direction == "BUY" else "SELL"
        dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        try:
            e_val = float(entry) if not isinstance(entry, bool) and math.isfinite(float(entry or 0.0)) else 0.0
            sl_val = float(sl) if not isinstance(sl, bool) and math.isfinite(float(sl or 0.0)) else 0.0
            tp_val = float(tp) if not isinstance(tp, bool) and math.isfinite(float(tp or 0.0)) else 0.0
            lot_val = float(lot) if not isinstance(lot, bool) and math.isfinite(float(lot or 0.0)) else 0.0
        except (ValueError, TypeError):
            e_val, sl_val, tp_val, lot_val = 0.0, 0.0, 0.0, 0.0

        msg = (
            f"<b>[GOLD ROBOT] {emoji} OPENED</b>\n"
            f"Direction: <b>{direction}</b>\n"
            f"Entry: <b>{e_val:.2f}</b>\n"
            f"SL: {sl_val:.2f} | TP: {tp_val:.2f}\n"
            f"Lot: {lot_val:.2f}\n"
            f"Time: {dt.strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg, force=force)

    def alert_trade_close(
        self,
        direction: str,
        pnl: float,
        reason: str,
        balance: float,
        now_dt: Optional[datetime] = None,
        force: bool = False,
    ):
        if not self._config.get("alert_on_trade_close", True):
            return
        try:
            pnl_val = float(pnl) if not isinstance(pnl, bool) and math.isfinite(float(pnl or 0.0)) else 0.0
            bal_val = float(balance) if not isinstance(balance, bool) and math.isfinite(float(balance or 0.0)) else 0.0
        except (ValueError, TypeError):
            pnl_val, bal_val = 0.0, 0.0

        result = "WIN" if pnl_val >= 0 else "LOSS"
        emoji = "WIN" if pnl_val >= 0 else "LOSS"
        dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        msg = (
            f"<b>[GOLD ROBOT] {emoji} CLOSED</b>\n"
            f"Direction: {direction} | Result: <b>{result}</b>\n"
            f"PnL: <b>${pnl_val:+.2f}</b>\n"
            f"Reason: {reason}\n"
            f"Balance: ${bal_val:,.2f}\n"
            f"Time: {dt.strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg, force=force)

    def alert_circuit_breaker(
        self,
        reason: str,
        balance: float,
        daily_pnl: float,
        now_dt: Optional[datetime] = None,
    ):
        if not self._config.get("alert_on_circuit_breaker", True):
            return
        try:
            bal_val = float(balance) if not isinstance(balance, bool) and math.isfinite(float(balance or 0.0)) else 0.0
            pnl_val = float(daily_pnl) if not isinstance(daily_pnl, bool) and math.isfinite(float(daily_pnl or 0.0)) else 0.0
        except (ValueError, TypeError):
            bal_val, pnl_val = 0.0, 0.0

        dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        msg = (
            f"<b>[GOLD ROBOT] CIRCUIT BREAKER FIRED</b>\n"
            f"Reason: <b>{reason}</b>\n"
            f"Balance: ${bal_val:,.2f}\n"
            f"Daily PnL: ${pnl_val:+.2f}\n"
            f"Time: {dt.strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg, force=True)

    def alert_daily_summary(
        self,
        balance: float,
        daily_pnl: float,
        wins: int,
        losses: int,
        win_rate: float,
        total_trades: int,
        now_dt: Optional[datetime] = None,
    ):
        if not self._config.get("alert_on_daily_summary", True):
            return
        try:
            bal_val = float(balance) if not isinstance(balance, bool) and math.isfinite(float(balance or 0.0)) else 0.0
            pnl_val = float(daily_pnl) if not isinstance(daily_pnl, bool) and math.isfinite(float(daily_pnl or 0.0)) else 0.0
            wr_val = float(win_rate) if not isinstance(win_rate, bool) and math.isfinite(float(win_rate or 0.0)) else 0.0
            w_int = int(wins or 0) if not isinstance(wins, bool) else 0
            l_int = int(losses or 0) if not isinstance(losses, bool) else 0
            tot_int = int(total_trades or 0) if not isinstance(total_trades, bool) else 0
        except (ValueError, TypeError):
            bal_val, pnl_val, wr_val, w_int, l_int, tot_int = 0.0, 0.0, 0.0, 0, 0, 0

        grade = "A" if wr_val >= 60 else "B" if wr_val >= 50 else "C"
        dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        msg = (
            f"<b>[GOLD ROBOT] DAILY SUMMARY</b>\n"
            f"Balance: <b>${bal_val:,.2f}</b>\n"
            f"Daily PnL: <b>${pnl_val:+.2f}</b>\n"
            f"Trades: {tot_int} (W:{w_int} L:{l_int})\n"
            f"Win Rate: <b>{wr_val:.1f}%</b> | Grade: <b>{grade}</b>\n"
            f"Date: {dt.strftime('%Y-%m-%d')} UTC"
        )
        self.send_alert(msg, force=True)

    def is_entry_blocked(self) -> bool:
        """Unified risk interface: alerting does not block entries."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()

    def reset(self):
        """Reset internal rate limiting and telemetry history."""
        with self._lock:
            self._last_sent = 0.0
            self._sent_messages.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Telemetry statistics on sent alerts."""
        with self._lock:
            return {
                "last_sent": self._last_sent,
                "sent_count": len(self._sent_messages),
                "enabled": bool(self._config.get("enabled", False)),
                "min_alert_interval_sec": float(self._config.get("min_alert_interval_sec", 60)),
            }


# ── Module-level singleton ─────────────────────────────────────────────────
telegram_alerter = TelegramAlerter()
