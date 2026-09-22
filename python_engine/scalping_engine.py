"""
Scalping Robot V5 Sovereign Engine
High-frequency volatility breakout and mean-reversion trading architecture.
Re-engineers and enhances the MQL4 Scalping Robot 5.0 EA logic with institutional risk guards:
  - Volatility Shield with real-time surge detection and post-shock cooldown circuit breaker
  - High-Impact Economic News Filter (NFP, CPI, FOMC, PPI, GDP rate decisions)
  - Dynamic ATR-anchored stop buffer adaptation
  - Volatility-regime dynamic position sizing (Van Tharp / Fixed Fractional Risk)
"""

import math
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Union


class ScalpingSignal:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_BUY = "CLOSE_BUY"
    CLOSE_SELL = "CLOSE_SELL"


class MarketRegime:
    LOW_VOLATILITY = "LOW_VOLATILITY"
    NORMAL_VOLATILITY = "NORMAL_VOLATILITY"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    EXTREME_SPIKE = "EXTREME_SPIKE"


class EconomicNewsFilter:
    """
    Institutional High-Impact Economic News Filter.
    Manages calendar schedules for NFP, CPI, FOMC, and interest rate decisions.
    Enforces configurable pre-event and post-event blackout windows.
    """
    def __init__(self, pre_minutes: int = 15, post_minutes: int = 30):
        self.pre_seconds = max(0, pre_minutes * 60)
        self.post_seconds = max(0, post_minutes * 60)
        self.events: List[Dict[str, Any]] = []
        self._load_default_calendar()

    def _parse_timestamp(self, event_time: Union[str, float, int, datetime]) -> float:
        if isinstance(event_time, (int, float)):
            return float(event_time)
        elif isinstance(event_time, datetime):
            if event_time.tzinfo is None:
                return event_time.replace(tzinfo=timezone.utc).timestamp()
            return event_time.timestamp()
        elif isinstance(event_time, str):
            clean_str = event_time.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(clean_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(event_time, fmt).replace(tzinfo=timezone.utc)
                        return dt.timestamp()
                    except ValueError:
                        continue
        return 0.0

    def add_event(
        self,
        event_time: Union[str, float, int, datetime],
        event_name: str,
        currency: str = "USD",
        impact: str = "HIGH"
    ):
        ts = self._parse_timestamp(event_time)
        if ts > 0:
            self.events.append({
                "timestamp": ts,
                "event": event_name,
                "currency": currency.upper(),
                "impact": impact.upper()
            })
            self.events.sort(key=lambda x: x["timestamp"])

    def clear_events(self):
        self.events.clear()

    def _load_default_calendar(self):
        """
        Populate rolling high-impact economic events for Gold/USD.
        Events are computed relative to now() so the calendar never expires.
        NFP: 1st Friday each month at 12:30 UTC
        CPI: ~2nd week each month at 12:30 UTC (estimated as 2nd Tuesday)
        FOMC: ~6 weeks cycle — next 6 meetings estimated from now
        """
        from datetime import timedelta
        import calendar as cal

        now = datetime.utcnow()
        events_added = []

        def first_friday(year, month):
            """Return datetime of first Friday in given month."""
            for day in range(1, 8):
                d = datetime(year, month, day, 12, 30, 0)
                if d.weekday() == 4:  # Friday
                    return d
            return datetime(year, month, 7, 12, 30, 0)

        def second_tuesday(year, month):
            """Return datetime of second Tuesday (≈CPI release)."""
            count = 0
            for day in range(1, 15):
                d = datetime(year, month, day, 12, 30, 0)
                if d.weekday() == 1:  # Tuesday
                    count += 1
                    if count == 2:
                        return d
            return datetime(year, month, 14, 12, 30, 0)

        # Generate NFP and CPI for next 4 months (robust month overflow with divmod)
        for offset in range(0, 5):
            raw_month = now.month - 1 + offset  # 0-indexed
            year = now.year + raw_month // 12
            month = (raw_month % 12) + 1  # back to 1-indexed

            nfp_dt = first_friday(year, month)
            if nfp_dt > now:
                events_added.append((nfp_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                     "US Non-Farm Payrolls (NFP) & Unemployment Rate",
                                     "USD", "HIGH"))

            cpi_dt = second_tuesday(year, month)
            if cpi_dt > now:
                events_added.append((cpi_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                     "US Consumer Price Index (CPI) YoY/MoM",
                                     "USD", "HIGH"))

        # FOMC meetings: approximately every 6-7 weeks — estimate next 4
        # Starting from a known FOMC base date and projecting forward
        fomc_interval_days = 45  # approx 6.5 weeks
        fomc_base = datetime(now.year, now.month, 1, 19, 0, 0)
        for i in range(6):
            candidate = fomc_base + timedelta(days=i * fomc_interval_days)
            if candidate > now:
                events_added.append((candidate.strftime("%Y-%m-%d %H:%M:%S"),
                                     "FOMC Interest Rate Decision & Press Conference",
                                     "USD", "HIGH"))
                if len([e for e in events_added if "FOMC" in e[1]]) >= 3:
                    break

        for t_str, ev, curr, imp in events_added:
            self.add_event(t_str, ev, curr, imp)

    def is_blackout(
        self,
        current_time: Optional[Union[str, float, int, datetime]] = None,
        currency: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Evaluates whether current_time falls within an active news blackout window.
        Returns: (is_blackout, active_event_dict)
        """
        now_ts = time.time() if current_time is None else self._parse_timestamp(current_time)
        target_curr = currency.upper() if currency else None

        for event in self.events:
            if target_curr and event["currency"] != target_curr:
                continue
            event_ts = event["timestamp"]
            window_start = event_ts - self.pre_seconds
            window_end = event_ts + self.post_seconds

            if window_start <= now_ts <= window_end:
                seconds_to_event = event_ts - now_ts
                event_info = dict(event)
                event_info["seconds_to_event"] = round(seconds_to_event, 1)
                event_info["phase"] = "PRE_EVENT" if seconds_to_event > 0 else "POST_EVENT"
                return True, event_info

        return False, None


class ScalpingRobotV5:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "fast_ema": 8,
            "slow_ema": 21,
            "bb_period": 20,
            "bb_std": 2.0,
            "rsi_period": 14,
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
            "atr_period": 14,
            "baseline_atr_period": 30,
            "atr_smoothing": "rma",           # "rma" (Wilder's) or "sma"
            "tp_pips": 15.0,
            "sl_pips": 30.0,
            "trailing_stop_pips": 10.0,
            "trailing_step_pips": 3.0,
            "breakeven_pips": 8.0,
            "breakeven_lock_pips": 2.0,
            "max_spread_pips": 3.5,
            "max_orders": 1,
            "lot_size": 0.01,
            "pip_value": 1.0,                 # XAUUSD: $1 per pip per 0.01 lot (NOT $10 which is EURUSD)
            "pip_size": 0.1 if "XAU" in (config or {}).get("symbol", "XAUUSD") else 0.0001,
            
            # Volatility Shield & Risk Guards
            "volatility_shield_enabled": True,
            "volatility_spike_threshold": 2.2, # True Range / Baseline ATR ratio for extreme spike
            "volatility_cooldown_bars": 5,     # Cooldown bars following an extreme spike
            
            # High-Impact News Filter
            "news_filter_enabled": True,
            "news_blackout_pre_minutes": 15,   # Minutes to freeze entries before event
            "news_blackout_post_minutes": 30,  # Minutes to freeze entries after event
            
            # Dynamic Stop & Position Sizing
            "dynamic_sl_enabled": True,
            "sl_atr_multiplier": 2.0,          # Stop distance = max(min_sl_pips, ATR_pips * 2.0)
            "tp_atr_multiplier": 1.5,          # Take profit distance = max(tp_pips, ATR_pips * 1.5)
            "min_sl_pips": 15.0,
            "max_sl_pips": 120.0,
            "risk_percent": 1.0,               # 1.0% equity risk per trade
            "min_lot_size": 0.01,
            "max_lot_size": 5.0,
            "lot_step": 0.01
        }
        if config:
            self.config.update(config)
        self.config["pip_size"] = max(1e-6, float(self.config.get("pip_size") or 0.1))
        self.config["pip_value"] = max(1e-6, float(self.config.get("pip_value") or 10.0))

        # Initialize Economic News Filter
        self.news_filter = EconomicNewsFilter(
            pre_minutes=int(self.config.get("news_blackout_pre_minutes", 15)),
            post_minutes=int(self.config.get("news_blackout_post_minutes", 30))
        )

        # Internal Shield & Circuit Breaker State
        self.volatility_halt_counter: int = 0
        self.shield_status: Dict[str, Any] = {"status": "NORMAL", "reason": "", "halted": False}
        self.open_positions: List[Dict[str, Any]] = []
        self.trade_history: List[Dict[str, Any]] = []
        self.equity_peak = 10000.0
        self.current_balance = 10000.0

    def calculate_indicators(self, bars: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Calculates EMA, Bollinger Bands, RSI, True Range, and multi-period ATR from bar series.
        Each bar: {'open', 'high', 'low', 'close', 'volume', 'timestamp'}
        """
        min_required = max(
            self.config["bb_period"],
            self.config["slow_ema"],
            self.config["rsi_period"],
            self.config["atr_period"]
        ) + 5
        if len(bars) < min_required:
            return {}

        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]

        # 1. EMAs
        fast_ema = self._calc_ema(closes, self.config["fast_ema"])
        slow_ema = self._calc_ema(closes, self.config["slow_ema"])

        # 2. Bollinger Bands
        period = self.config["bb_period"]
        slice_closes = closes[-period:]
        bb_mid = sum(slice_closes) / max(1, period)
        variance = sum((x - bb_mid) ** 2 for x in slice_closes) / max(1, period)
        std_dev = math.sqrt(max(0.0, variance))
        bb_upper = bb_mid + (self.config["bb_std"] * std_dev)
        bb_lower = bb_mid - (self.config["bb_std"] * std_dev)
        bb_width_pct = ((bb_upper - bb_lower) / max(1e-6, bb_mid)) * 100.0

        # 3. RSI
        rsi = self._calc_rsi(closes, self.config["rsi_period"])

        # 4. Standard ATR & Baseline ATR
        smoothing_method = self.config.get("atr_smoothing", "rma")
        atr = self._calc_atr(highs, lows, closes, self.config["atr_period"], method=smoothing_method)
        baseline_period = min(len(closes) - 1, self.config.get("baseline_atr_period", 30))
        atr_baseline = self._calc_atr(highs, lows, closes, max(1, baseline_period), method=smoothing_method)

        # 5. Instantaneous True Range of current bar
        if len(closes) > 1:
            current_tr = max(
                highs[-1] - lows[-1],
                abs(highs[-1] - closes[-2]),
                abs(lows[-1] - closes[-2])
            )
        else:
            current_tr = max(0.0, highs[-1] - lows[-1])

        # 6. Volatility Ratio & Regime Determination
        baseline_safe = max(1e-5, atr_baseline)
        volatility_ratio = current_tr / baseline_safe

        if volatility_ratio >= self.config.get("volatility_spike_threshold", 2.2):
            regime = MarketRegime.EXTREME_SPIKE
        elif volatility_ratio >= 1.5:
            regime = MarketRegime.HIGH_VOLATILITY
        elif volatility_ratio < 0.75:
            regime = MarketRegime.LOW_VOLATILITY
        else:
            regime = MarketRegime.NORMAL_VOLATILITY

        return {
            "close": closes[-1],
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "bb_width_pct": round(bb_width_pct, 4),
            "rsi": rsi,
            "atr": atr,
            "atr_baseline": atr_baseline,
            "current_tr": round(current_tr, 4),
            "volatility_ratio": round(volatility_ratio, 2),
            "volatility_regime": regime,
            "trend": "BULLISH" if fast_ema > slow_ema else "BEARISH"
        }

    def _calc_ema(self, series: List[float], period: int) -> float:
        if not series or period <= 0:
            return 0.0
        if len(series) < period:
            return series[-1]
        k = 2.0 / (period + 1.0)
        ema = sum(series[:period]) / period
        for price in series[period:]:
            ema = (price * k) + (ema * (1.0 - k))
        return ema

    def _calc_rsi(self, series: List[float], period: int) -> float:
        """
        Wilder's Smoothed RSI — uses full series with recursive exponential smoothing.
        The old 'simple average' RSI was inaccurate; this is the industry-standard version.
        Requires at least period+1 bars; returns 50.0 (neutral) if insufficient data.
        """
        if not series or period <= 0 or len(series) < period + 1:
            return 50.0
        deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
        gains = [max(0.0, d) for d in deltas]
        losses = [abs(min(0.0, d)) for d in deltas]
        # Wilder's first average (SMA of first `period` values)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        # Wilder's recursive smoothing over remaining bars
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        # Edge cases
        if avg_loss == 0.0 and avg_gain == 0.0:
            return 50.0
        if avg_loss == 0.0:
            return 100.0
        if avg_gain == 0.0:
            return 0.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int,
        method: str = "rma"
    ) -> float:
        """
        Calculates Average True Range (ATR) with zero-division safety.
        Supports both Wilder's RMA (Exponential Smoothing) and SMA.
        """
        if not closes or period <= 0:
            return 1.0
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)

        if not trs:
            return max(0.0001, highs[0] - lows[0] if highs and lows else 1.0)

        if len(trs) < period:
            return max(1e-4, sum(trs) / len(trs))

        if method.lower() == "sma":
            return max(1e-4, sum(trs[-period:]) / period)

        # Wilder's RMA smoothing: ATR_t = (ATR_{t-1} * (n-1) + TR_t) / n
        rma = sum(trs[:period]) / period
        for tr in trs[period:]:
            rma = ((rma * (period - 1)) + tr) / period
        return max(1e-4, rma)

    def evaluate_entry(
        self,
        indicators: Dict[str, Any],
        current_spread_pips: float = 1.0,
        current_time: Optional[Union[str, float, int, datetime]] = None
    ) -> str:
        """
        Determines entry signal with full confluence of:
          1. Spread Guard
          2. Max Orders Guard
          3. High-Impact Economic News Filter (Blackout Window)
          4. Volatility Shield Circuit Breaker & Cooldown
          5. Bollinger Bands + RSI + Momentum Confluence
        """
        if not indicators:
            return ScalpingSignal.HOLD

        # 1. Spread Protection
        if current_spread_pips > self.config["max_spread_pips"]:
            self.shield_status = {
                "status": "SPREAD_PROTECTION",
                "reason": f"Spread {current_spread_pips} > max {self.config['max_spread_pips']}",
                "halted": True
            }
            return ScalpingSignal.HOLD

        # 2. Max Orders Protection
        if len(self.open_positions) >= self.config["max_orders"]:
            self.shield_status = {
                "status": "MAX_ORDERS_REACHED",
                "reason": f"Open positions {len(self.open_positions)} >= max {self.config['max_orders']}",
                "halted": True
            }
            return ScalpingSignal.HOLD

        # 3. High-Impact News Filter Protection (Blackout)
        if self.config.get("news_filter_enabled", True):
            currency = "USD" if "XAU" in self.config["symbol"] or "USD" in self.config["symbol"] else self.config["symbol"][:3]
            is_blackout, news_event = self.news_filter.is_blackout(current_time=current_time, currency=currency)
            if is_blackout and news_event:
                self.shield_status = {
                    "status": "NEWS_BLACKOUT",
                    "reason": f"High-Impact News: {news_event.get('event')} ({news_event.get('phase')})",
                    "event": news_event,
                    "halted": True
                }
                return ScalpingSignal.HOLD

        # 4. Volatility Shield Circuit Breaker Protection
        if self.config.get("volatility_shield_enabled", True):
            vol_ratio = indicators.get("volatility_ratio", 1.0)
            threshold = self.config.get("volatility_spike_threshold", 2.2)

            if vol_ratio >= threshold:
                self.volatility_halt_counter = self.config.get("volatility_cooldown_bars", 5)
                self.shield_status = {
                    "status": "VOLATILITY_HALT",
                    "reason": f"Volatility spike detected: {vol_ratio:.2f}x baseline (threshold: {threshold}x)",
                    "volatility_ratio": vol_ratio,
                    "halted": True
                }
                return ScalpingSignal.HOLD

            if self.volatility_halt_counter > 0:
                self.volatility_halt_counter -= 1
                self.shield_status = {
                    "status": "COOLDOWN",
                    "reason": f"Volatility cooldown active ({self.volatility_halt_counter} bars remaining)",
                    "bars_remaining": self.volatility_halt_counter,
                    "halted": True
                }
                return ScalpingSignal.HOLD

        # Shield cleared
        self.shield_status = {"status": "NORMAL", "reason": "All risk guards passed", "halted": False}

        price = indicators["close"]
        bb_lower = indicators["bb_lower"]
        bb_upper = indicators["bb_upper"]
        fast_ema = indicators["fast_ema"]
        slow_ema = indicators["slow_ema"]
        rsi = indicators["rsi"]

        # BUY SIGNAL:
        # Price tags or dips below lower Bollinger Band AND RSI is oversold (< 33) AND fast EMA >= slow EMA (momentum confirmation)
        ema_bullish = fast_ema >= slow_ema * 0.9998  # allow near-cross
        if price <= bb_lower * 1.0005 and rsi <= self.config["rsi_oversold"] + 3.0 and ema_bullish:
            return ScalpingSignal.BUY

        # SELL SIGNAL:
        # Price tags or rises above upper Bollinger Band AND RSI is overbought (> 67) AND fast EMA <= slow EMA (momentum confirmation)
        ema_bearish = fast_ema <= slow_ema * 1.0002  # allow near-cross
        if price >= bb_upper * 0.9995 and rsi >= self.config["rsi_overbought"] - 3.0 and ema_bearish:
            return ScalpingSignal.SELL

        return ScalpingSignal.HOLD

    def calculate_dynamic_stops(
        self,
        indicators: Dict[str, Any],
        price: Optional[float] = None,
        signal: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Calculates volatility-adaptive Stop-Loss and Take-Profit buffers.
        During elevated ATR or post-shock regimes, stop distance dynamically widens to prevent
        whipsaw liquidations while maintaining risk integrity.
        """
        pip_size = self.config["pip_size"]
        base_sl_pips = float(self.config.get("sl_pips", 30.0))
        base_tp_pips = float(self.config.get("tp_pips", 15.0))

        if not self.config.get("dynamic_sl_enabled", True) or not indicators:
            sl_pips = base_sl_pips
            tp_pips = base_tp_pips
        else:
            atr_val = indicators.get("atr", pip_size * base_sl_pips / 2.0)
            atr_pips = atr_val / pip_size
            sl_mult = float(self.config.get("sl_atr_multiplier", 2.0))
            tp_mult = float(self.config.get("tp_atr_multiplier", 1.5))
            min_sl = float(self.config.get("min_sl_pips", 15.0))
            max_sl = float(self.config.get("max_sl_pips", 120.0))

            # Dynamic SL anchored to ATR
            sl_pips = max(min_sl, min(max_sl, atr_pips * sl_mult))
            # Dynamic TP maintains positive risk/reward scaling
            tp_pips = max(base_tp_pips, atr_pips * tp_mult)

        result = {
            "sl_pips": round(sl_pips, 1),
            "tp_pips": round(tp_pips, 1),
            "sl_price": None,
            "tp_price": None
        }

        if price is not None and signal is not None:
            if signal == ScalpingSignal.BUY:
                result["sl_price"] = round(price - (sl_pips * pip_size), 2)
                result["tp_price"] = round(price + (tp_pips * pip_size), 2)
            elif signal == ScalpingSignal.SELL:
                result["sl_price"] = round(price + (sl_pips * pip_size), 2)
                result["tp_price"] = round(price - (tp_pips * pip_size), 2)

        return result

    def calculate_position_size(
        self,
        account_balance: float,
        indicators: Dict[str, Any],
        sl_pips: Optional[float] = None,
        risk_percent: Optional[float] = None
    ) -> float:
        """
        Calculates dynamic position sizing adapting to market volatility regime (Van Tharp / Fixed Fractional Risk).
        Formula:
          Risk Dollars = Account Balance * (Risk Percent / 100)
          Effective SL (pips) = Dynamic ATR Stop Buffer
          Lots = Risk Dollars / (Effective SL * Pip Value)
        Clamped within broker min/max lot constraints.
        """
        bal = max(100.0, float(account_balance))
        risk_pct = float(risk_percent if risk_percent is not None else self.config.get("risk_percent", 1.0))
        risk_dollars = bal * (risk_pct / 100.0)

        pip_value = self.config["pip_value"]
        min_lots = float(self.config.get("min_lot_size", 0.01))
        max_lots = float(self.config.get("max_lot_size", 5.0))
        lot_step = float(self.config.get("lot_step", 0.01))

        if sl_pips is not None and sl_pips > 0:
            effective_sl_pips = sl_pips
        else:
            stops = self.calculate_dynamic_stops(indicators)
            effective_sl_pips = stops["sl_pips"]

        # Dollar risk per lot = Stop Loss in Pips * Pip Value per Lot
        risk_per_lot = max(1e-4, effective_sl_pips * pip_value)
        raw_lots = risk_dollars / risk_per_lot

        # Quantize to lot step and clamp
        steps = math.floor(raw_lots / lot_step)
        quantized_lots = steps * lot_step
        final_lots = max(min_lots, min(max_lots, quantized_lots))

        return round(final_lots, 2)
