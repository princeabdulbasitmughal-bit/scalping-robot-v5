"""
Wave 12: Telegram Alert System
Sends real-time trade notifications via Telegram Bot API.
Zero external dependencies — uses urllib.request (built-in).
Configure via E:\\scalping-robot-v5\\telegram_config.json
"""
import json
import os
import time
import urllib.request
import urllib.parse
import threading
from datetime import datetime
from typing import Optional


TELEGRAM_CONFIG_PATH = r"E:\scalping-robot-v5\telegram_config.json"
TELEGRAM_LOG_PATH = r"E:\scalping-robot-v5\telegram.log"

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
        ts = datetime.utcnow().strftime("%H:%M:%S")
        with open(TELEGRAM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


class TelegramAlerter:

    def __init__(self):
        self._config = {}
        self._last_sent: float = 0.0
        self._load_config()
        self._lock = threading.Lock()

    def _load_config(self):
        try:
            if os.path.exists(TELEGRAM_CONFIG_PATH):
                with open(TELEGRAM_CONFIG_PATH) as f:
                    self._config = json.load(f)
            else:
                with open(TELEGRAM_CONFIG_PATH, "w") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2)
                self._config = DEFAULT_CONFIG.copy()
        except Exception as e:
            self._config = DEFAULT_CONFIG.copy()
            _log(f"Config load error: {e}")

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

    def send_alert(self, text: str, force: bool = False) -> bool:
        """Rate-limited alert send."""
        if not self._config.get("enabled", False):
            return False
        with self._lock:
            min_interval = float(self._config.get("min_alert_interval_sec", 60))
            if not force and time.time() - self._last_sent < min_interval:
                return False
            # Send in background thread to never block main loop
            def _send():
                ok = self._send_raw(text)
                _log(f"{'SENT' if ok else 'FAILED'}: {text[:60]}")
            t = threading.Thread(target=_send, daemon=True)
            t.start()
            self._last_sent = time.time()
            return True

    # ── Formatted alert helpers ───────────────────────────────────────────────
    def alert_trade_open(self, direction: str, entry: float, sl: float, tp: float, lot: float):
        if not self._config.get("alert_on_trade_open", True):
            return
        emoji = "BUY" if direction == "BUY" else "SELL"
        msg = (
            f"<b>[GOLD ROBOT] {emoji} OPENED</b>\n"
            f"Direction: <b>{direction}</b>\n"
            f"Entry: <b>{entry:.2f}</b>\n"
            f"SL: {sl:.2f} | TP: {tp:.2f}\n"
            f"Lot: {lot:.2f}\n"
            f"Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg)

    def alert_trade_close(self, direction: str, pnl: float, reason: str, balance: float):
        if not self._config.get("alert_on_trade_close", True):
            return
        result = "WIN" if pnl >= 0 else "LOSS"
        emoji = "WIN" if pnl >= 0 else "LOSS"
        msg = (
            f"<b>[GOLD ROBOT] {emoji} CLOSED</b>\n"
            f"Direction: {direction} | Result: <b>{result}</b>\n"
            f"PnL: <b>${pnl:+.2f}</b>\n"
            f"Reason: {reason}\n"
            f"Balance: ${balance:,.2f}\n"
            f"Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg)

    def alert_circuit_breaker(self, reason: str, balance: float, daily_pnl: float):
        if not self._config.get("alert_on_circuit_breaker", True):
            return
        msg = (
            f"<b>[GOLD ROBOT] CIRCUIT BREAKER FIRED</b>\n"
            f"Reason: <b>{reason}</b>\n"
            f"Balance: ${balance:,.2f}\n"
            f"Daily PnL: ${daily_pnl:+.2f}\n"
            f"Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )
        self.send_alert(msg, force=True)

    def alert_daily_summary(
        self, balance: float, daily_pnl: float, wins: int, losses: int,
        win_rate: float, total_trades: int
    ):
        if not self._config.get("alert_on_daily_summary", True):
            return
        grade = "A" if win_rate >= 60 else "B" if win_rate >= 50 else "C"
        msg = (
            f"<b>[GOLD ROBOT] DAILY SUMMARY</b>\n"
            f"Balance: <b>${balance:,.2f}</b>\n"
            f"Daily PnL: <b>${daily_pnl:+.2f}</b>\n"
            f"Trades: {total_trades} (W:{wins} L:{losses})\n"
            f"Win Rate: <b>{win_rate:.1f}%</b> | Grade: <b>{grade}</b>\n"
            f"Date: {datetime.utcnow().strftime('%Y-%m-%d')} UTC"
        )
        self.send_alert(msg, force=True)


# ── Module-level singleton ─────────────────────────────────────────────────
telegram_alerter = TelegramAlerter()
