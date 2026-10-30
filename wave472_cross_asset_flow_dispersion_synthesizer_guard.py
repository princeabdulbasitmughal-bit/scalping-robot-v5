"""
Wave 472: Cross-Asset Order Flow Shock Dispersion Synthesizer Guard
===================================================================
Institutional Quantitative Mathematical Formulation:
Under Forbes & Rigobon (2002) "No Contagion, Only Interdependence", Bekaert, Harvey & Ng (2005),
and Hasbrouck (2003) "Intraday Price Formation in US Equity Index Markets", institutional
surges in benchmark instruments (e.g. DXY, US10Y Treasuries, or XAGUSD) spill over into
XAUUSD order book queues with microsecond-level lead-lag dynamics.

Let z_m(t) = (F_m(t) - mu_m) / max(sigma_m, epsilon) be standardized order flows across
M interconnected market venues or asset classes (m = 1, ..., M):

1. Cross-Asset Flow Dispersion (Cross-Sectional Dispersion):
   sigma_disp(t) = sqrt( 1 / (M - 1) * sum_{m=1}^M (z_m(t) - bar{z}(t))^2 )
   When sigma_disp(t) > max_dispersion_threshold (default: > 2.80), flow decoupling and
   fragmented liquidity withdrawal are occurring across multi-asset legs.

2. Coordinated Macro Flow Shock:
   Z_macro(t) = 1 / M * sum_{m=1}^M |z_m(t)|
   When Z_macro(t) > max_macro_shock_z (default: > 2.50 sigma), a systemic cross-asset
   liquidity extraction event is underway.

3. Grand Sovereign Microstructure Canopy Synthesis (Waves 468-472):
   Unifies:
   - Cross-Asset Flow Dispersion Risk: Phi_disp = min(1.0, sigma_disp / 3.50)
   - Coordinated Macro Flow Shock Risk: Phi_macro = min(1.0, Z_macro / 3.0)
   - Replenishment Half-Life Decay Risk: Phi_rep = min(1.0, max(0.0, (t_1/2 - 0.50) / 3.0)) (Wave 471)
   - Depth Curvature Acceleration Risk: Phi_curv = min(1.0, max(0.0, -kappa / 2.50)) (Wave 470)

   The Composite Macro-Microstructure Fragility Canopy Index is:
   Omega_{472}(t) = 0.25 * Phi_disp + 0.25 * Phi_macro + 0.25 * Phi_rep + 0.25 * Phi_curv

Circuit Breakers:
1. CROSS_ASSET_FLOW_DISPERSION_SHOCK: sigma_disp(t) > max_dispersion_threshold (default: > 2.80)
2. COORDINATED_MACRO_FLOW_SURGE: Z_macro(t) > max_macro_shock_z (default: > 2.50)
3. SOVEREIGN_CANOPY_DISPERSION_BREACH: Omega_{472}(t) > critical_canopy_threshold (default: > 0.68)

When triggered, the guard isolates trading execution engines across MT5 and OmniTrade,
ensuring capital is never exposed during multi-asset liquidity contagion shocks.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave472CrossAssetFlowDispersionSynthesizerGuard:
    """
    Synthesizes cross-asset order flow dispersion, coordinated macro flow shocks,
    and upstream orderbook decay invariants into a sovereign multi-asset risk defense.
    """

    def __init__(
        self,
        max_dispersion_threshold: float = 2.80,
        max_macro_shock_z: float = 2.50,
        critical_canopy_threshold: float = 0.68,
        lead_flow_z_threshold: float = 2.00,
        cooldown_sec: float = 2.0
    ) -> None:
        if max_dispersion_threshold <= 1.0:
            raise ValueError(f"max_dispersion_threshold must be > 1.0, got {max_dispersion_threshold}")
        if max_macro_shock_z <= 1.0:
            raise ValueError(f"max_macro_shock_z must be > 1.0, got {max_macro_shock_z}")
        if not (0.40 <= critical_canopy_threshold <= 0.90):
            raise ValueError(f"critical_canopy_threshold must be in [0.40, 0.90], got {critical_canopy_threshold}")
        if lead_flow_z_threshold <= 0.50:
            raise ValueError(f"lead_flow_z_threshold must be > 0.50, got {lead_flow_z_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_dispersion_threshold: float = max_dispersion_threshold
        self.max_macro_shock_z: float = max_macro_shock_z
        self.critical_canopy_threshold: float = critical_canopy_threshold
        self.lead_flow_z_threshold: float = lead_flow_z_threshold
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.flow_dispersion: float = 0.0
        self.macro_shock_z: float = 0.0
        self.lead_flow_z: float = 0.0
        self.composite_canopy_index: float = 0.0
        self.sub_metrics: Dict[str, float] = {}

        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        asset_flow_zscores: List[float],
        replenishment_halflife: float = 0.50,
        depth_curvature: float = 1.0,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous standardized flow z-scores across multi-asset benchmarks
        along with upstream replenishment half-life (Wave 471) and depth curvature (Wave 470).
        asset_flow_zscores[0] is designated as the primary lead cross-asset flow (e.g. DXY or XAGUSD).
        """
        if len(asset_flow_zscores) < 2:
            raise ValueError("asset_flow_zscores must contain at least 2 assets")
        for z in asset_flow_zscores:
            if not math.isfinite(z):
                raise ValueError("All asset flow z-scores must be finite numbers")
        if not math.isfinite(replenishment_halflife) or replenishment_halflife < 0.0:
            raise ValueError("replenishment_halflife must be non-negative and finite")
        if not math.isfinite(depth_curvature):
            raise ValueError("depth_curvature must be finite")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        z_arr = np.array(asset_flow_zscores, dtype=np.float64)
        m = len(z_arr)

        # 1. Cross-Asset Flow Dispersion (Sample Standard Deviation)
        self.flow_dispersion = float(np.std(z_arr, ddof=1))

        # 2. Coordinated Macro Flow Shock (Mean Absolute Z-score)
        self.macro_shock_z = float(np.mean(np.abs(z_arr)))

        # 3. Lead Flow Z-Score
        self.lead_flow_z = float(z_arr[0])

        # Normalize components into risk scores [0.0, 1.0]
        phi_disp = min(1.0, max(0.0, self.flow_dispersion / 3.50))
        phi_macro = min(1.0, max(0.0, self.macro_shock_z / 3.0))
        phi_rep = min(1.0, max(0.0, (replenishment_halflife - 0.50) / 3.0))
        phi_curv = min(1.0, max(0.0, -depth_curvature / 2.50))

        # Composite canopy index Omega_{472}
        self.composite_canopy_index = float(0.25 * phi_disp + 0.25 * phi_macro + 0.25 * phi_rep + 0.25 * phi_curv)

        self.sub_metrics = {
            "phi_disp": round(phi_disp, 4),
            "phi_macro": round(phi_macro, 4),
            "phi_rep": round(phi_rep, 4),
            "phi_curv": round(phi_curv, 4)
        }

        # Evaluate Circuit Breakers
        dispersion_breached = (self.flow_dispersion > self.max_dispersion_threshold)
        macro_breached = (self.macro_shock_z > self.max_macro_shock_z)
        canopy_breached = (self.composite_canopy_index > self.critical_canopy_threshold)
        lead_surge_breached = (abs(self.lead_flow_z) > self.lead_flow_z_threshold)

        if dispersion_breached or macro_breached or canopy_breached or lead_surge_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution based on lead flow surge
            if lead_surge_breached and not dispersion_breached:
                if self.lead_flow_z > self.lead_flow_z_threshold:
                    self.blocked_side = "SELL" # Heavy foreign buying surge incoming -> shorting is toxic
                    side_note = "LEAD_ASSET_BUY_SURGE"
                else:
                    self.blocked_side = "BUY" # Heavy foreign dumping incoming -> buying is toxic
                    side_note = "LEAD_ASSET_DUMP_SURGE"
            else:
                self.blocked_side = "ALL"
                side_note = "MULTI_ASSET_FLOW_DISPERSION_CASCADE"

            trigger = (
                "CROSS_ASSET_FLOW_DISPERSION_SHOCK" if dispersion_breached else
                ("COORDINATED_MACRO_FLOW_SURGE" if macro_breached else
                ("LEAD_ASSET_ORDER_FLOW_SURGE" if lead_surge_breached else "SOVEREIGN_CANOPY_DISPERSION_BREACH"))
            )
            self._block_reason = (
                f"{trigger}: sigma_disp={self.flow_dispersion:.2f} (max={self.max_dispersion_threshold:.2f}), "
                f"Z_macro={self.macro_shock_z:.2f} (max={self.max_macro_shock_z:.2f}), "
                f"z_lead={self.lead_flow_z:.2f} (thresh={self.lead_flow_z_threshold:.2f}), "
                f"Omega={self.composite_canopy_index:.3f} [{side_note}], blocked: {self.blocked_side}"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Checks if specific side is blocked."""
        if not self._is_blocked:
            return False
        if self.blocked_side == "ALL":
            return True
        return self.blocked_side == side.upper()

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave472CrossAssetFlowDispersionSynthesizerGuard",
            "flow_dispersion": round(self.flow_dispersion, 4),
            "macro_shock_z": round(self.macro_shock_z, 4),
            "lead_flow_z": round(self.lead_flow_z, 4),
            "composite_canopy_index": round(self.composite_canopy_index, 4),
            "sub_metrics": self.sub_metrics,
            "max_dispersion_threshold": self.max_dispersion_threshold,
            "max_macro_shock_z": self.max_macro_shock_z,
            "critical_canopy_threshold": self.critical_canopy_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.flow_dispersion = 0.0
        self.macro_shock_z = 0.0
        self.lead_flow_z = 0.0
        self.composite_canopy_index = 0.0
        self.sub_metrics.clear()
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
