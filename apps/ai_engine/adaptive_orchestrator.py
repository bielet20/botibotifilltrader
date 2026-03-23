import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from apps.engine.bot_advisor import build_bot_advice
from apps.shared.database import SessionLocal
from apps.shared.models import AutopilotDecisionLogDB, BotDB, PositionDB, TradeDB


class AdaptiveOrchestratorService:
    def __init__(self, bot_manager, production_guard=None):
        self.bot_manager = bot_manager
        self.production_guard = production_guard
        self.refresh_from_env()
        self._running = False
        self._task = None
        self._last_report: Dict[str, Any] = {}
        self._copilot_state_path = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
            "reports",
            "copilot_total_state.json",
        )
        self._copilot_total: Dict[str, Any] = {
            "enabled": os.getenv("COPILOT_TOTAL_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            "profile": "balanced",
            "reason": "startup",
            "requested_by": "system",
            "last_updated": self._utc_now(),
            "attack_window_until_ts": 0.0,
            "attack_window_duration_min": 0,
        }
        self._load_copilot_total_state()

    def refresh_from_env(self) -> None:
        self.interval_sec = int(os.getenv("AUTO_ORCHESTRATOR_INTERVAL_SEC", "180"))
        self.enabled = os.getenv("AUTO_ORCHESTRATOR_ENABLED", "false").lower() == "true"
        self.default_symbol = os.getenv("AUTO_ORCHESTRATOR_SYMBOL", "BTC/USDT")
        self.default_symbols = self._parse_symbols(
            os.getenv("AUTO_ORCHESTRATOR_SYMBOLS", self.default_symbol)
        )
        self.default_allocation = float(os.getenv("AUTO_ORCHESTRATOR_ALLOCATION", "350"))
        self.max_active_bots = int(os.getenv("AUTO_ORCHESTRATOR_MAX_ACTIVE", "3"))
        self.window_trades = int(os.getenv("AUTO_ORCHESTRATOR_WINDOW_TRADES", "30"))
        self.mainnet_autolaunch = os.getenv("AUTO_ORCHESTRATOR_AUTOLAUNCH_MAINNET", "false").lower() in {"1", "true", "yes", "on"}
        self.mainnet_min_confidence = float(os.getenv("AUTO_ORCHESTRATOR_MAINNET_MIN_CONFIDENCE", "90"))
        self.mainnet_allowed_horizons = {
            str(part or "").strip().lower()
            for part in str(os.getenv("AUTO_ORCHESTRATOR_MAINNET_ALLOWED_HORIZONS", "medio,largo") or "").split(",")
            if str(part or "").strip()
        }
        if not self.mainnet_allowed_horizons:
            self.mainnet_allowed_horizons = {"medio", "largo"}

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_copilot_total_state(self) -> None:
        path = self._copilot_state_path
        try:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
            if isinstance(payload, dict):
                self._copilot_total.update(payload)
        except Exception:
            # Non-fatal: keep in-memory defaults.
            pass

    def _save_copilot_total_state(self) -> None:
        path = self._copilot_state_path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._copilot_total, f, ensure_ascii=True, indent=2)
        except Exception:
            # Non-fatal: mode still works in-memory.
            pass

    def copilot_total_status(self) -> Dict[str, Any]:
        now_ts = float(time.time())
        attack_until = float(self._copilot_total.get("attack_window_until_ts", 0.0) or 0.0)
        attack_active = bool(attack_until > now_ts)
        return {
            "enabled": bool(self._copilot_total.get("enabled", False)),
            "profile": str(self._copilot_total.get("profile") or "balanced"),
            "reason": str(self._copilot_total.get("reason") or "manual"),
            "requested_by": str(self._copilot_total.get("requested_by") or "unknown"),
            "last_updated": str(self._copilot_total.get("last_updated") or self._utc_now()),
            "attack_window_active": attack_active,
            "attack_window_duration_min": int(self._copilot_total.get("attack_window_duration_min") or 0),
            "attack_window_until_ts": attack_until if attack_active else 0.0,
            "attack_window_remaining_sec": int(max(0.0, attack_until - now_ts)) if attack_active else 0,
            "state_file": self._copilot_state_path,
        }

    def set_copilot_total(self, enabled: bool, requested_by: str = "api", reason: str = "manual_toggle") -> Dict[str, Any]:
        self._copilot_total["enabled"] = bool(enabled)
        self._copilot_total["requested_by"] = str(requested_by or "api")
        self._copilot_total["reason"] = str(reason or "manual_toggle")
        self._copilot_total["last_updated"] = self._utc_now()
        if not enabled:
            self._copilot_total["profile"] = "balanced"
            self._copilot_total["attack_window_until_ts"] = 0.0
            self._copilot_total["attack_window_duration_min"] = 0
        self._save_copilot_total_state()
        return self.copilot_total_status()

    def set_attack_window(self, minutes: int, requested_by: str = "api", reason: str = "manual_attack_window") -> Dict[str, Any]:
        mins = max(0, min(int(minutes or 0), 240))
        now_ts = float(time.time())
        if mins <= 0:
            self._copilot_total["attack_window_until_ts"] = 0.0
            self._copilot_total["attack_window_duration_min"] = 0
            self._copilot_total["reason"] = "attack_window_disabled"
        else:
            self._copilot_total["attack_window_until_ts"] = now_ts + (mins * 60.0)
            self._copilot_total["attack_window_duration_min"] = mins
            self._copilot_total["reason"] = reason
        self._copilot_total["requested_by"] = str(requested_by or "api")
        self._copilot_total["last_updated"] = self._utc_now()
        self._save_copilot_total_state()
        return self.copilot_total_status()

    @staticmethod
    def _copilot_profile_from_context(market_context: Dict[str, Any]) -> str:
        context = market_context or {}
        regime = str(context.get("regime") or "mixto").strip().lower()
        volatility = float(context.get("volatility_pct") or 0.0)
        trend_pct = float(context.get("trend_pct") or 0.0)
        abs_trend = abs(trend_pct)

        # In bearish context: if volatility is high, stay defensive.
        # If volatility is contained, use balanced to avoid being overly inactive.
        if trend_pct <= -2.0 and volatility >= 0.55:
            return "defensive"
        if regime == "tendencia_estable" and volatility < 0.8 and abs_trend >= 1.5 and trend_pct > 0:
            return "aggressive"
        if regime in {"lateral_volatil", "tendencia_volatil"} or volatility >= 1.2:
            return "defensive"
        return "balanced"

    def _attack_window_active(self) -> bool:
        until_ts = float(self._copilot_total.get("attack_window_until_ts", 0.0) or 0.0)
        now_ts = float(time.time())
        if until_ts <= now_ts:
            if until_ts > 0:
                # Auto-expire and return to regime-driven profile.
                self._copilot_total["attack_window_until_ts"] = 0.0
                self._copilot_total["attack_window_duration_min"] = 0
                self._copilot_total["reason"] = "attack_window_expired_auto_return_balanced"
                self._copilot_total["last_updated"] = self._utc_now()
                self._save_copilot_total_state()
            return False
        return True

    @staticmethod
    def _copilot_thresholds(profile: str) -> Dict[str, Any]:
        key = str(profile or "balanced").strip().lower()
        if key == "aggressive":
            return {
                "ema_min_spread_pct": 0.00018,
                "ema_min_slope_pct": 0.00008,
                "live_min_reentry_move_pct": 0.00055,
                "live_min_close_profit_pct": 0.00065,
                "live_min_trade_interval_sec": 70.0,
                "live_force_close_loss_pct": 0.0038,
                "ai_take_profit_cooldown_sec": 160.0,
                "ai_min_take_profit_pct": 0.0085,
                "ai_hard_take_profit_pct": 0.02,
                "leverage": 1.4,
                "risk_max_drawdown": 0.05,
            }
        if key == "defensive":
            return {
                "ema_min_spread_pct": 0.00052,
                "ema_min_slope_pct": 0.00022,
                "live_min_reentry_move_pct": 0.00120,
                "live_min_close_profit_pct": 0.00150,
                "live_min_trade_interval_sec": 130.0,
                "live_force_close_loss_pct": 0.0022,
                "ai_take_profit_cooldown_sec": 95.0,
                "ai_min_take_profit_pct": 0.0048,
                "ai_hard_take_profit_pct": 0.011,
                "leverage": 1.0,
                "risk_max_drawdown": 0.03,
            }
        return {
            "ema_min_spread_pct": 0.00030,
            "ema_min_slope_pct": 0.00012,
            "live_min_reentry_move_pct": 0.00082,
            "live_min_close_profit_pct": 0.00100,
            "live_min_trade_interval_sec": 95.0,
            "live_force_close_loss_pct": 0.0030,
            "ai_take_profit_cooldown_sec": 120.0,
            "ai_min_take_profit_pct": 0.0065,
            "ai_hard_take_profit_pct": 0.015,
            "leverage": 1.2,
            "risk_max_drawdown": 0.04,
        }

    def _apply_copilot_total_policy(
        self,
        config: Dict[str, Any],
        profile: str,
        market_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        patched = dict(config or {})
        th = self._copilot_thresholds(profile)
        patched.update(
            {
                "ema_min_spread_pct": float(th["ema_min_spread_pct"]),
                "ema_min_slope_pct": float(th["ema_min_slope_pct"]),
                "live_min_reentry_move_pct": float(th["live_min_reentry_move_pct"]),
                "live_min_close_profit_pct": float(th["live_min_close_profit_pct"]),
                "live_execution_guard_enabled": True,
                "live_allow_scale_in": False,
                "live_scale_in_min_move_pct": 0.0022,
                "live_min_trade_interval_sec": float(th["live_min_trade_interval_sec"]),
                "live_force_close_loss_pct": float(th["live_force_close_loss_pct"]),
                "live_taker_fee_pct": 0.00045,
                "ai_take_profit_enabled": True,
                "ai_take_profit_only_production": True,
                "ai_take_profit_cooldown_sec": float(th["ai_take_profit_cooldown_sec"]),
                "ai_min_take_profit_pct": float(th["ai_min_take_profit_pct"]),
                "ai_hard_take_profit_pct": float(th["ai_hard_take_profit_pct"]),
                "leverage": float(th["leverage"]),
                "autopilot_mode": "copilot_total",
                "autopilot_profile": str(profile),
                "autopilot_last_context": dict(market_context or {}),
                "autopilot_last_updated": self._utc_now(),
                "autopilot_micro_entry_enabled": True,
                "autopilot_micro_entry_flat_wait_sec": 300.0,
                "autopilot_micro_entry_duration_sec": 900.0,
            }
        )
        risk_cfg = dict(patched.get("risk_config") or {})
        risk_cfg["max_drawdown"] = float(th["risk_max_drawdown"])
        patched["risk_config"] = risk_cfg

        # 24/7 trend-capture layer:
        # - accelerate long entries in healthy bullish trends
        # - auto-switch to capital defense on adverse context
        context = dict(market_context or {})
        regime = str(context.get("regime") or "").strip().lower()
        trend_pct = float(context.get("trend_pct") or 0.0)
        volatility = float(context.get("volatility_pct") or 0.0)
        trend_capture_ok = regime == "tendencia_estable" and trend_pct >= 1.0 and volatility <= 0.75
        defense_mode = trend_pct <= -1.4 or volatility >= 1.0

        if trend_capture_ok:
            patched["ema_min_spread_pct"] = min(float(patched.get("ema_min_spread_pct") or 0.00018), 0.00012)
            patched["ema_min_slope_pct"] = min(float(patched.get("ema_min_slope_pct") or 0.00008), 0.00005)
            patched["live_min_reentry_move_pct"] = min(float(patched.get("live_min_reentry_move_pct") or 0.00055), 0.00040)
            patched["live_min_close_profit_pct"] = min(float(patched.get("live_min_close_profit_pct") or 0.00065), 0.00055)
            patched["live_min_trade_interval_sec"] = min(float(patched.get("live_min_trade_interval_sec") or 70.0), 55.0)
            patched["live_force_close_loss_pct"] = min(float(patched.get("live_force_close_loss_pct") or 0.0038), 0.0032)
            patched["ai_take_profit_cooldown_sec"] = min(float(patched.get("ai_take_profit_cooldown_sec") or 160.0), 90.0)
            patched["ai_min_take_profit_pct"] = min(float(patched.get("ai_min_take_profit_pct") or 0.0085), 0.0058)
            patched["ai_hard_take_profit_pct"] = min(float(patched.get("ai_hard_take_profit_pct") or 0.0200), 0.0135)
            patched["leverage"] = min(max(float(patched.get("leverage") or 1.4), 1.35), 1.5)
            patched["allow_short"] = False
            patched["autopilot_micro_entry_flat_wait_sec"] = min(
                float(patched.get("autopilot_micro_entry_flat_wait_sec") or 300.0),
                180.0,
            )
            patched["autopilot_micro_entry_duration_sec"] = max(
                float(patched.get("autopilot_micro_entry_duration_sec") or 900.0),
                1200.0,
            )
            patched["autopilot_capture_mode"] = "trend_capture_24x7"
        elif defense_mode:
            patched["live_min_trade_interval_sec"] = max(float(patched.get("live_min_trade_interval_sec") or 95.0), 120.0)
            patched["live_force_close_loss_pct"] = min(float(patched.get("live_force_close_loss_pct") or 0.0030), 0.0024)
            risk_cfg = dict(patched.get("risk_config") or {})
            risk_cfg["max_drawdown"] = min(float(risk_cfg.get("max_drawdown") or th["risk_max_drawdown"]), 0.03)
            patched["risk_config"] = risk_cfg
            patched["autopilot_capture_mode"] = "capital_defense"
        else:
            patched["autopilot_capture_mode"] = "neutral"
        return patched

    @staticmethod
    def _scaling_rules_for_profile(profile: str) -> Dict[str, Any]:
        key = str(profile or "balanced").strip().lower()
        if key == "aggressive":
            return {
                "tiers": [0.70, 0.90, 1.00, 1.15, 1.30, 1.45],
                "max_step_up": 1,
                "min_trade_count_for_step_up": 8,
                "min_win_rate_for_step_up": 58.0,
                "max_consecutive_losses_for_step_up": 0,
                "max_step_down": 2,
            }
        if key == "defensive":
            return {
                "tiers": [0.60, 0.75, 0.90, 1.00, 1.08, 1.15],
                "max_step_up": 1,
                "min_trade_count_for_step_up": 10,
                "min_win_rate_for_step_up": 62.0,
                "max_consecutive_losses_for_step_up": 0,
                "max_step_down": 2,
            }
        return {
            "tiers": [0.65, 0.85, 1.00, 1.12, 1.24, 1.35],
            "max_step_up": 1,
            "min_trade_count_for_step_up": 9,
            "min_win_rate_for_step_up": 60.0,
            "max_consecutive_losses_for_step_up": 0,
            "max_step_down": 2,
        }

    @staticmethod
    def _nearest_tier_index(target: float, tiers: List[float]) -> int:
        if not tiers:
            return 0
        idx = min(range(len(tiers)), key=lambda i: abs(float(tiers[i]) - float(target)))
        return int(idx)

    def _apply_copilot_capital_scaling(
        self,
        config: Dict[str, Any],
        metrics: Dict[str, float],
        profile: str,
    ) -> Dict[str, Any]:
        patched = dict(config or {})
        m = metrics or {}
        trade_count = int(m.get("trade_count", 0) or 0)
        net_pnl = float(m.get("net_pnl", 0.0) or 0.0)
        win_rate = float(m.get("win_rate", 0.0) or 0.0)
        consecutive_losses = int(m.get("consecutive_losses", 0) or 0)

        base_allocation = float(
            patched.get("autopilot_base_allocation")
            or patched.get("capital_allocation")
            or patched.get("allocation")
            or self.default_allocation
            or 250.0
        )
        base_allocation = max(50.0, base_allocation)

        # Approx equity model for sizing: base allocation + rolling net result.
        current_equity = max(base_allocation * 0.50, base_allocation + net_pnl)
        equity_ratio = current_equity / max(base_allocation, 1e-9)

        rules = self._scaling_rules_for_profile(profile)
        tiers = list(rules.get("tiers") or [1.0])
        target_idx = self._nearest_tier_index(equity_ratio, tiers)

        prev_idx = int(
            patched.get("autopilot_scaling_tier")
            if patched.get("autopilot_scaling_tier") is not None
            else self._nearest_tier_index(float(patched.get("autopilot_scaling_factor", 1.0) or 1.0), tiers)
        )
        prev_idx = max(0, min(prev_idx, len(tiers) - 1))

        allow_step_up = (
            trade_count >= int(rules.get("min_trade_count_for_step_up", 8))
            and win_rate >= float(rules.get("min_win_rate_for_step_up", 58.0))
            and consecutive_losses <= int(rules.get("max_consecutive_losses_for_step_up", 0))
            and net_pnl > 0.0
        )
        degradation = (
            consecutive_losses >= 2
            or net_pnl < 0.0
            or (trade_count >= 6 and win_rate < 48.0)
        )

        if degradation:
            step_down = int(rules.get("max_step_down", 2))
            new_idx = max(0, min(prev_idx, target_idx) - step_down)
            scaling_reason = "degradation_protection"
        elif allow_step_up:
            step_up = int(rules.get("max_step_up", 1))
            new_idx = min(len(tiers) - 1, max(prev_idx, target_idx, prev_idx + step_up))
            scaling_reason = "confirmed_edge_step_up"
        else:
            # Keep or gently mean-revert to avoid overtrading.
            new_idx = min(prev_idx, target_idx) if target_idx < prev_idx else prev_idx
            scaling_reason = "hold_tier_waiting_confirmation"

        scaling_factor = float(tiers[new_idx])
        scaled_allocation = max(50.0, round(base_allocation * scaling_factor, 4))
        patched["autopilot_base_allocation"] = round(base_allocation, 4)
        patched["autopilot_scaling_factor"] = round(scaling_factor, 4)
        patched["autopilot_scaling_tier"] = int(new_idx)
        patched["autopilot_scaling_ratio"] = round(equity_ratio, 6)
        patched["autopilot_scaling_reason"] = scaling_reason
        patched["capital_allocation"] = float(scaled_allocation)
        patched["allocation"] = float(scaled_allocation)

        # Preserve relative trade sizing for strategies that use amount/trade_amount.
        prev_allocation = float(patched.get("autopilot_prev_allocation") or base_allocation)
        prev_allocation = max(prev_allocation, 1e-9)
        ratio = scaled_allocation / prev_allocation
        if "trade_amount" in patched:
            patched["trade_amount"] = round(max(0.0001, float(patched.get("trade_amount") or 0.0001) * ratio), 6)
        if "amount" in patched:
            patched["amount"] = round(max(0.0001, float(patched.get("amount") or 0.0001) * ratio), 6)
        patched["autopilot_prev_allocation"] = float(scaled_allocation)
        return patched

    @staticmethod
    def _bool_cfg(value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "on"}:
                return True
            if v in {"0", "false", "no", "off"}:
                return False
        if value is None:
            return default
        return bool(value)

    def _apply_micro_entry_probe(
        self,
        config: Dict[str, Any],
        metrics: Dict[str, float],
        *,
        open_positions_count: int,
        attack_window_active: bool,
    ) -> Dict[str, Any]:
        patched = dict(config or {})
        if not self._bool_cfg(patched.get("autopilot_micro_entry_enabled"), default=True):
            patched["autopilot_probe_active"] = False
            return patched

        now_ts = float(time.time())
        flat_since_ts = float(patched.get("autopilot_flat_since_ts") or 0.0)
        probe_until_ts = float(patched.get("autopilot_probe_until_ts") or 0.0)
        flat_wait_sec = max(180.0, float(patched.get("autopilot_micro_entry_flat_wait_sec") or 900.0))
        probe_duration_sec = max(180.0, float(patched.get("autopilot_micro_entry_duration_sec") or 900.0))
        if attack_window_active:
            flat_wait_sec = min(flat_wait_sec, 180.0)

        if open_positions_count > 0:
            patched["autopilot_flat_since_ts"] = 0.0
            patched["autopilot_probe_until_ts"] = 0.0
            patched["autopilot_probe_active"] = False
            patched["autopilot_probe_reason"] = "position_open"
            return patched

        if flat_since_ts <= 0.0:
            flat_since_ts = now_ts
            patched["autopilot_flat_since_ts"] = flat_since_ts

        trade_count = int(metrics.get("trade_count", 0) or 0)
        net_pnl = float(metrics.get("net_pnl", 0.0) or 0.0)
        win_rate = float(metrics.get("win_rate", 0.0) or 0.0)
        consecutive_losses = int(metrics.get("consecutive_losses", 0) or 0)
        if attack_window_active:
            # Temporary tactical mode: still protected, but less restrictive to avoid staying flat too long.
            risk_ok = (consecutive_losses <= 2) and (net_pnl >= -3.0) and (win_rate >= 25.0 or trade_count <= 6)
        else:
            risk_ok = (consecutive_losses <= 1) and (net_pnl >= -2.5) and (win_rate >= 35.0 or trade_count <= 4)

        should_arm_probe = (
            (now_ts - flat_since_ts) >= flat_wait_sec
            and risk_ok
            and (attack_window_active or str(patched.get("autopilot_profile") or "").lower() in {"balanced", "aggressive"})
        )

        if should_arm_probe and probe_until_ts <= now_ts:
            probe_until_ts = now_ts + probe_duration_sec
            patched["autopilot_probe_until_ts"] = probe_until_ts
            patched["autopilot_probe_reason"] = "flat_market_micro_probe"

        probe_active = probe_until_ts > now_ts
        patched["autopilot_probe_active"] = bool(probe_active)
        if not probe_active:
            return patched

        # Controlled probe: loosen entries, keep hard capital protection.
        patched["ema_min_spread_pct"] = min(float(patched.get("ema_min_spread_pct", 0.0003) or 0.0003), 0.00014)
        patched["ema_min_slope_pct"] = min(float(patched.get("ema_min_slope_pct", 0.00012) or 0.00012), 0.00006)
        patched["live_min_reentry_move_pct"] = min(float(patched.get("live_min_reentry_move_pct", 0.00082) or 0.00082), 0.00045)
        patched["live_min_close_profit_pct"] = min(float(patched.get("live_min_close_profit_pct", 0.0010) or 0.0010), 0.00060)
        # Protect downside during probe.
        current_force_loss = float(patched.get("live_force_close_loss_pct", 0.0030) or 0.0030)
        patched["live_force_close_loss_pct"] = min(current_force_loss, 0.0026)
        patched["live_min_trade_interval_sec"] = min(float(patched.get("live_min_trade_interval_sec", 95.0) or 95.0), 75.0)

        # Keep probe size small and bounded.
        current_trade_amount = float(patched.get("trade_amount", patched.get("amount", 0.0015)) or 0.0015)
        probe_trade_amount = max(0.0002, min(current_trade_amount, 0.0012))
        patched["trade_amount"] = round(probe_trade_amount, 6)
        patched["amount"] = round(probe_trade_amount, 6)
        patched["autopilot_probe_expires_in_sec"] = int(max(0.0, probe_until_ts - now_ts))
        return patched

    @staticmethod
    def _config_change_snapshot(before_cfg: Dict[str, Any], after_cfg: Dict[str, Any]) -> Dict[str, Any]:
        before = before_cfg or {}
        after = after_cfg or {}
        keys = [
            "capital_allocation",
            "allocation",
            "trade_amount",
            "amount",
            "leverage",
            "ema_min_spread_pct",
            "ema_min_slope_pct",
            "live_min_reentry_move_pct",
            "live_min_close_profit_pct",
            "live_force_close_loss_pct",
            "live_min_trade_interval_sec",
            "autopilot_profile",
            "autopilot_scaling_factor",
            "autopilot_scaling_reason",
            "autopilot_probe_active",
            "autopilot_probe_reason",
        ]
        out = {}
        for key in keys:
            old_v = before.get(key)
            new_v = after.get(key)
            if old_v != new_v:
                out[key] = {"before": old_v, "after": new_v}

        old_risk = dict(before.get("risk_config") or {})
        new_risk = dict(after.get("risk_config") or {})
        if old_risk.get("max_drawdown") != new_risk.get("max_drawdown"):
            out["risk_config.max_drawdown"] = {
                "before": old_risk.get("max_drawdown"),
                "after": new_risk.get("max_drawdown"),
            }
        return out

    @staticmethod
    def _strict_policy(capital_allocation: float) -> Dict[str, Any]:
        return {
            "enabled": True,
            "window_trades": 30,
            "min_trades": 8,
            "min_win_rate": 50.0,
            "min_net_pnl": 0.0,
            "max_consecutive_losses": 2,
            "max_loss_abs": 5.0,
            "max_loss_pct_of_allocation": 0.01,
            "capital_allocation": float(capital_allocation or 0.0),
            "stop_on_unproductive": True,
        }

    @staticmethod
    def _live_warmup_policy(capital_allocation: float) -> Dict[str, Any]:
        policy = AdaptiveOrchestratorService._strict_policy(capital_allocation)
        policy["min_trades"] = max(12, int(policy.get("min_trades", 8)))
        policy["stop_on_unproductive"] = True
        return policy

    @staticmethod
    def _is_orchestrator_managed(bot_id: str, config: Dict[str, Any]) -> bool:
        cfg = config or {}
        if str(cfg.get("autonomy_status") or "").strip().lower() == "quarantined":
            return False
        if str(cfg.get("managed_by") or "").lower() == "adaptive_orchestrator":
            return True
        if str(bot_id or "").upper().startswith("AUTO-ADAPT-"):
            return True
        return False

    @staticmethod
    def _is_live_mainnet_config(config: Dict[str, Any]) -> bool:
        cfg = config or {}
        executor = str(cfg.get("executor") or "paper").strip().lower()
        if executor != "hyperliquid":
            return False
        return not bool(cfg.get("hyperliquid_testnet", True))

    @staticmethod
    def _is_verified_for_production(config: Dict[str, Any]) -> bool:
        cfg = config or {}
        return bool(
            cfg.get("analysis_approved")
            or cfg.get("candidate_for_production")
            or cfg.get("production_ready")
            or cfg.get("autoadapt_mainnet_candidate")
        )

    @staticmethod
    def _parse_symbols(raw: str) -> List[str]:
        symbols = []
        for part in str(raw or "").split(","):
            symbol = str(part or "").strip().upper()
            if not symbol:
                continue
            symbols.append(symbol)
        return symbols or ["BTC/USDT"]

    @staticmethod
    def _symbol_token(symbol: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9]+", "_", str(symbol or "").upper()).strip("_")
        return clean[:24] or "UNKNOWN"

    def _managed_bot_id(self, symbol: str, horizon: str) -> str:
        return f"AUTO-ADAPT-{self._symbol_token(symbol)}-{horizon.upper()}"

    def _mainnet_candidate(self, rec: Dict[str, Any], horizon: str) -> bool:
        confidence = float(rec.get("confidence") or 0.0)
        action = str(rec.get("recommended_action") or "").strip().lower()
        if horizon not in self.mainnet_allowed_horizons:
            return False
        if action not in {"create_new", "tune_existing"}:
            return False
        return confidence >= self.mainnet_min_confidence

    def _recent_metrics(self, db, bot_id: str) -> Dict[str, float]:
        trades = (
            db.query(TradeDB)
            .filter(TradeDB.bot_id == bot_id)
            .order_by(TradeDB.time.desc())
            .limit(self.window_trades)
            .all()
        )
        if not trades:
            return {"trade_count": 0, "net_pnl": 0.0, "consecutive_losses": 0, "win_rate": 0.0}

        scored = [float(t.pnl or 0.0) for t in trades if float(t.pnl or 0.0) != 0.0]
        wins = sum(1 for pnl in scored if pnl > 0)
        win_rate = (wins / len(scored) * 100.0) if scored else 0.0
        net_pnl = sum((float(t.pnl or 0.0) - float(t.fee or 0.0)) for t in trades)

        consecutive_losses = 0
        for t in trades:
            if float(t.pnl or 0.0) <= 0.0:
                consecutive_losses += 1
            else:
                break

        return {
            "trade_count": len(trades),
            "net_pnl": round(net_pnl, 6),
            "consecutive_losses": int(consecutive_losses),
            "win_rate": round(win_rate, 2),
        }

    @staticmethod
    def _healthy_for_live_restart(metrics: Dict[str, float]) -> bool:
        """
        Guardrail para evitar relanzar en bucle bots live degradados.
        """
        m = dict(metrics or {})
        trade_count = int(m.get("trade_count") or 0)
        consecutive_losses = int(m.get("consecutive_losses") or 0)
        net_pnl = float(m.get("net_pnl") or 0.0)
        win_rate = float(m.get("win_rate") or 0.0)

        if trade_count <= 0:
            return False
        if consecutive_losses >= 3:
            return False
        if trade_count >= 8 and win_rate < 30.0:
            return False
        if trade_count >= 12 and net_pnl <= 0.0:
            return False
        return True

    @staticmethod
    def _is_unproductive_for_autonomy(metrics: Dict[str, float]) -> bool:
        """
        Determina si un bot debe salir de ejecución automática por baja productividad.
        """
        m = dict(metrics or {})
        trade_count = int(m.get("trade_count") or 0)
        consecutive_losses = int(m.get("consecutive_losses") or 0)
        net_pnl = float(m.get("net_pnl") or 0.0)
        win_rate = float(m.get("win_rate") or 0.0)

        # Sin muestra suficiente, no aplicamos cuarentena automática.
        if trade_count < 8:
            return False
        if consecutive_losses >= 3:
            return True
        if win_rate < 30.0:
            return True
        if trade_count >= 12 and net_pnl <= 0.0:
            return True
        return False

    @staticmethod
    def _is_quarantined(cfg: Dict[str, Any]) -> bool:
        return str((cfg or {}).get("autonomy_status") or "").strip().lower() == "quarantined"

    def _preserve_quarantine_fields(self, prev_cfg: Dict[str, Any], new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        prev = dict(prev_cfg or {})
        cfg = dict(new_cfg or {})
        if not self._is_quarantined(prev):
            return cfg
        cfg["autonomy_status"] = "quarantined"
        cfg["autonomy_status_reason"] = str(prev.get("autonomy_status_reason") or "unproductive_metrics")
        cfg["autonomy_status_since"] = prev.get("autonomy_status_since") or self._utc_now()
        return cfg

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self.run_once(trigger="scheduled")
            except Exception as e:
                self._last_report = {
                    "generated_at": self._utc_now(),
                    "trigger": "scheduled",
                    "status": "error",
                    "error": str(e),
                }
            await asyncio.sleep(self.interval_sec)

    async def run_once(self, trigger: str = "manual", symbol: str = None, allocation: float = None):
        if symbol:
            symbols = [str(symbol).strip().upper()]
        else:
            symbols = list(self.default_symbols)

        effective_allocation = float(allocation or self.default_allocation or 350.0)
        effective_allocation = max(50.0, effective_allocation)

        actions: List[Dict[str, Any]] = []
        opportunities: List[Dict[str, Any]] = []
        recommendations_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        market_context_by_symbol: Dict[str, Dict[str, Any]] = {}
        decision_logs: List[Dict[str, Any]] = []
        copilot_enabled = bool(self._copilot_total.get("enabled", False))
        copilot_profile = str(self._copilot_total.get("profile") or "balanced")
        attack_window_active = self._attack_window_active()

        if self.production_guard:
            try:
                await self.production_guard.scan_once(trigger="orchestrator-pre")
            except Exception:
                pass

        with SessionLocal() as db:
            bots = db.query(BotDB).filter(BotDB.is_archived == False).all()
            bot_map = {b.id: b for b in bots}
            active_count = sum(1 for b in bots if str(b.status or "").lower() == "running")
            touched_bots = set()

            for effective_symbol in symbols:
                analysis = await build_bot_advice(db, symbol=effective_symbol, allocation=effective_allocation)
                recommendations = analysis.get("recommendations", [])
                recommendations_by_symbol[effective_symbol] = recommendations
                market_context = dict(analysis.get("market_context") or {})
                market_context_by_symbol[effective_symbol] = market_context
                if copilot_enabled:
                    if attack_window_active:
                        copilot_profile = "aggressive"
                    else:
                        copilot_profile = self._copilot_profile_from_context(market_context)

                for rec in recommendations:
                    horizon = (rec.get("horizon") or "medio").strip().lower()
                    action = rec.get("recommended_action")
                    managed_id = self._managed_bot_id(effective_symbol, horizon)
                    is_mainnet_candidate = self._mainnet_candidate(rec, horizon)

                    if action == "create_new":
                        base_cfg = dict(rec.get("new_bot_config") or {})
                        base_cfg["id"] = managed_id
                        base_cfg["symbol"] = effective_symbol
                        base_cfg["capital_allocation"] = float(base_cfg.get("capital_allocation") or effective_allocation)
                        base_cfg["allocation"] = float(base_cfg.get("allocation") or base_cfg["capital_allocation"])
                        base_cfg["executor"] = "paper"
                        base_cfg["managed_by"] = "adaptive_orchestrator"
                        base_cfg["self_managed"] = True
                        base_cfg["autoadapt_horizon"] = horizon
                        base_cfg["production_policy"] = self._strict_policy(base_cfg["capital_allocation"])
                        base_cfg["autoadapt_confidence"] = float(rec.get("confidence") or 0.0)
                        base_cfg["autoadapt_market_context"] = dict(analysis.get("market_context") or {})
                        if copilot_enabled:
                            base_cfg = self._apply_copilot_total_policy(base_cfg, copilot_profile, market_context)

                        if is_mainnet_candidate:
                            base_cfg["analysis_approved"] = True
                            base_cfg["candidate_for_production"] = True
                            base_cfg["production_ready"] = True
                            base_cfg["autoadapt_mainnet_candidate"] = True
                            if self.mainnet_autolaunch:
                                base_cfg["executor"] = "hyperliquid"
                                base_cfg["hyperliquid_testnet"] = False
                                base_cfg["production_policy"] = self._live_warmup_policy(base_cfg["capital_allocation"])
                            opportunities.append(
                                {
                                    "bot_id": managed_id,
                                    "symbol": effective_symbol,
                                    "horizon": horizon,
                                    "confidence": float(rec.get("confidence") or 0.0),
                                    "action": action,
                                    "autolaunch_requested": bool(self.mainnet_autolaunch),
                                }
                            )

                        if managed_id in bot_map:
                            bot_entry = bot_map[managed_id]
                            bot_entry.config = self._preserve_quarantine_fields(dict(bot_entry.config or {}), base_cfg)
                            bot_entry.strategy = base_cfg.get("strategy", bot_entry.strategy)
                            bot_entry.capital_allocation = float(base_cfg.get("capital_allocation") or 0.0)
                            bot_cfg_now = dict(bot_entry.config or {})
                            if (
                                str(bot_entry.status or "").lower() != "running"
                                and active_count < self.max_active_bots
                                and not self._is_quarantined(bot_cfg_now)
                            ):
                                if self.bot_manager.start_bot(managed_id, base_cfg):
                                    bot_entry.status = "running"
                                    active_count += 1
                                    actions.append({"type": "start", "bot_id": managed_id, "reason": f"create_new:{effective_symbol}:{horizon}"})
                        else:
                            bot_entry = BotDB(
                                id=managed_id,
                                strategy=base_cfg.get("strategy", "ema_cross"),
                                status="stopped",
                                capital_allocation=float(base_cfg.get("capital_allocation") or 0.0),
                                config=base_cfg,
                                is_archived=False,
                                created_at=datetime.utcnow(),
                            )
                            db.add(bot_entry)
                            bot_map[managed_id] = bot_entry
                            actions.append({"type": "create", "bot_id": managed_id, "reason": f"create_new:{effective_symbol}:{horizon}"})

                            if active_count < self.max_active_bots and not self._is_quarantined(base_cfg) and self.bot_manager.start_bot(managed_id, base_cfg):
                                bot_entry.status = "running"
                                active_count += 1
                                actions.append({"type": "start", "bot_id": managed_id, "reason": f"new_managed:{effective_symbol}:{horizon}"})

                    elif action in {"tune_existing", "reduce_risk"}:
                        target_id = rec.get("recommended_bot_id")
                        target_entry = bot_map.get(target_id) if target_id else None
                        target_cfg = dict(target_entry.config or {}) if target_entry else {}
                        target_symbol = str(target_cfg.get("symbol") or "").strip().upper()

                        # Keep one managed bot per symbol+horizon; avoid reusing BTC bot for ETH/ADA.
                        if (not target_entry) or (target_symbol and target_symbol != effective_symbol):
                            base_cfg = dict(rec.get("edited_config") or rec.get("new_bot_config") or {})
                            base_cfg["id"] = managed_id
                            base_cfg["symbol"] = effective_symbol
                            base_cfg["capital_allocation"] = float(base_cfg.get("capital_allocation") or effective_allocation)
                            base_cfg["allocation"] = float(base_cfg.get("allocation") or base_cfg["capital_allocation"])
                            base_cfg["executor"] = "paper"
                            base_cfg["managed_by"] = "adaptive_orchestrator"
                            base_cfg["self_managed"] = True
                            base_cfg["autoadapt_horizon"] = horizon
                            base_cfg["autoadapt_confidence"] = float(rec.get("confidence") or 0.0)
                            base_cfg["autoadapt_market_context"] = dict(analysis.get("market_context") or {})
                            base_cfg.setdefault("production_policy", self._strict_policy(base_cfg["capital_allocation"]))
                            if copilot_enabled:
                                base_cfg = self._apply_copilot_total_policy(base_cfg, copilot_profile, market_context)

                            if is_mainnet_candidate:
                                base_cfg["analysis_approved"] = True
                                base_cfg["candidate_for_production"] = True
                                base_cfg["production_ready"] = True
                                base_cfg["autoadapt_mainnet_candidate"] = True
                                if self.mainnet_autolaunch:
                                    base_cfg["executor"] = "hyperliquid"
                                    base_cfg["hyperliquid_testnet"] = False
                                    base_cfg["production_policy"] = self._live_warmup_policy(base_cfg["capital_allocation"])
                                opportunities.append(
                                    {
                                        "bot_id": managed_id,
                                        "symbol": effective_symbol,
                                        "horizon": horizon,
                                        "confidence": float(rec.get("confidence") or 0.0),
                                        "action": "symbol_create_or_tune",
                                        "autolaunch_requested": bool(self.mainnet_autolaunch),
                                    }
                                )

                            if managed_id in bot_map:
                                managed_entry = bot_map[managed_id]
                                managed_entry.config = self._preserve_quarantine_fields(dict(managed_entry.config or {}), base_cfg)
                                managed_entry.strategy = base_cfg.get("strategy", managed_entry.strategy)
                                managed_entry.capital_allocation = float(base_cfg.get("capital_allocation") or 0.0)
                                actions.append({"type": "tune", "bot_id": managed_id, "reason": f"symbol_scoped:{effective_symbol}:{horizon}"})
                            else:
                                managed_entry = BotDB(
                                    id=managed_id,
                                    strategy=base_cfg.get("strategy", "ema_cross"),
                                    status="stopped",
                                    capital_allocation=float(base_cfg.get("capital_allocation") or 0.0),
                                    config=base_cfg,
                                    is_archived=False,
                                    created_at=datetime.utcnow(),
                                )
                                db.add(managed_entry)
                                bot_map[managed_id] = managed_entry
                                actions.append({"type": "create", "bot_id": managed_id, "reason": f"symbol_scoped:{effective_symbol}:{horizon}"})

                            managed_cfg_now = dict(managed_entry.config or {})
                            if (
                                str(managed_entry.status or "").lower() != "running"
                                and active_count < self.max_active_bots
                                and not self._is_quarantined(managed_cfg_now)
                            ):
                                if self.bot_manager.start_bot(managed_id, base_cfg):
                                    managed_entry.status = "running"
                                    active_count += 1
                                    actions.append({"type": "start", "bot_id": managed_id, "reason": f"symbol_scoped:{effective_symbol}:{horizon}"})
                            continue

                        if target_id in touched_bots:
                            actions.append({"type": "skip", "bot_id": target_id, "reason": "already_tuned_this_cycle"})
                            continue

                        target_executor = str(target_cfg.get("executor") or "paper").lower()
                        target_testnet = bool(target_cfg.get("hyperliquid_testnet", False))

                        if target_executor == "hyperliquid" and not target_testnet:
                            actions.append(
                                {
                                    "type": "skip",
                                    "bot_id": target_id,
                                    "reason": "live_executor_protected",
                                }
                            )
                            continue

                        updated = dict(target_entry.config or {})
                        updated.update(rec.get("edited_config") or {})
                        updated["autoadapt_last_horizon"] = horizon
                        updated["symbol"] = effective_symbol
                        updated["autoadapt_confidence"] = float(rec.get("confidence") or 0.0)
                        updated["autoadapt_market_context"] = dict(analysis.get("market_context") or {})
                        updated.setdefault("production_policy", self._strict_policy(float(updated.get("capital_allocation") or 0.0)))
                        if copilot_enabled:
                            updated = self._apply_copilot_total_policy(updated, copilot_profile, market_context)

                        if is_mainnet_candidate:
                            updated["analysis_approved"] = True
                            updated["candidate_for_production"] = True
                            updated["production_ready"] = True
                            updated["autoadapt_mainnet_candidate"] = True
                            if self.mainnet_autolaunch:
                                updated["executor"] = "hyperliquid"
                                updated["hyperliquid_testnet"] = False
                                updated["production_policy"] = self._live_warmup_policy(
                                    float(updated.get("capital_allocation") or 0.0)
                                )
                            opportunities.append(
                                {
                                    "bot_id": target_id,
                                    "symbol": effective_symbol,
                                    "horizon": horizon,
                                    "confidence": float(rec.get("confidence") or 0.0),
                                    "action": action,
                                    "autolaunch_requested": bool(self.mainnet_autolaunch),
                                }
                            )

                        target_entry.config = self._preserve_quarantine_fields(dict(target_entry.config or {}), updated)
                        touched_bots.add(target_id)
                        actions.append({"type": "tune", "bot_id": target_id, "reason": f"{action}:{effective_symbol}:{horizon}"})

                        if action == "reduce_risk" and str(target_entry.status or "").lower() == "running":
                            metrics = self._recent_metrics(db, target_id)
                            if metrics.get("consecutive_losses", 0) > 2 or metrics.get("net_pnl", 0.0) < -5.0:
                                self.bot_manager.stop_bot(target_id)
                                target_entry.status = "stopped"
                                actions.append({"type": "stop", "bot_id": target_id, "reason": "risk_guard:reduce_risk"})

            # Quarantine managed bots with persistent unproductive metrics:
            # they stay out of active bot execution until manual reset/review.
            for entry in bot_map.values():
                cfg = dict(entry.config or {})
                is_managed = self._is_orchestrator_managed(entry.id, cfg)
                is_live_mainnet = self._is_live_mainnet_config(cfg)
                if not is_managed and not is_live_mainnet:
                    continue
                metrics = self._recent_metrics(db, entry.id)
                if not self._is_unproductive_for_autonomy(metrics):
                    continue
                if str(entry.status or "").lower() == "running":
                    self.bot_manager.stop_bot(entry.id)
                    entry.status = "stopped"
                    actions.append({"type": "stop", "bot_id": entry.id, "reason": "autonomy_quarantine_unproductive"})
                if not self._is_quarantined(cfg):
                    cfg["autonomy_status"] = "quarantined"
                    cfg["autonomy_status_reason"] = "unproductive_metrics"
                    cfg["autonomy_status_since"] = self._utc_now()
                    entry.config = cfg
                    actions.append({"type": "quarantine", "bot_id": entry.id, "reason": "unproductive_metrics"})

            if copilot_enabled:
                default_context = market_context_by_symbol.get(symbols[0], {}) if symbols else {}
                for entry in bot_map.values():
                    cfg = dict(entry.config or {})
                    is_live_executor = str(cfg.get("executor") or "paper").strip().lower() == "hyperliquid"
                    is_testnet = bool(cfg.get("hyperliquid_testnet", True))
                    if not is_live_executor or is_testnet:
                        continue
                    symbol_key = str(cfg.get("symbol") or "").strip().upper()
                    live_context = market_context_by_symbol.get(symbol_key, default_context)
                    patched_cfg = self._apply_copilot_total_policy(cfg, copilot_profile, live_context)
                    metrics = self._recent_metrics(db, entry.id)
                    patched_cfg = self._apply_copilot_capital_scaling(
                        patched_cfg,
                        metrics=metrics,
                        profile=copilot_profile,
                    )
                    open_positions_count = (
                        db.query(PositionDB)
                        .filter(PositionDB.bot_id == entry.id, PositionDB.is_open == True)
                        .count()
                    )
                    patched_cfg = self._apply_micro_entry_probe(
                        patched_cfg,
                        metrics=metrics,
                        open_positions_count=int(open_positions_count or 0),
                        attack_window_active=attack_window_active,
                    )
                    if patched_cfg != cfg:
                        changes = self._config_change_snapshot(cfg, patched_cfg)
                        reason_code = "copilot_tune"
                        reason_text = f"profile={copilot_profile}"
                        if patched_cfg.get("autopilot_probe_active"):
                            reason_code = "micro_entry_probe"
                            reason_text = f"profile={copilot_profile}; probe={patched_cfg.get('autopilot_probe_reason') or 'active'}"
                        elif str(patched_cfg.get("autopilot_scaling_reason") or "").strip():
                            reason_code = "capital_scaling"
                            reason_text = f"profile={copilot_profile}; scaling={patched_cfg.get('autopilot_scaling_reason')}"
                        decision_logs.append(
                            {
                                "trigger": trigger,
                                "bot_id": entry.id,
                                "symbol": str(patched_cfg.get("symbol") or symbol_key or "").upper() or None,
                                "profile": copilot_profile,
                                "reason_code": reason_code,
                                "reason_text": reason_text,
                                "market_context": dict(live_context or {}),
                                "metrics": dict(metrics or {}),
                                "changes": changes,
                                "extra": {
                                    "attack_window_active": bool(attack_window_active),
                                    "open_positions_count": int(open_positions_count or 0),
                                },
                            }
                        )
                        entry.config = patched_cfg
                        actions.append(
                            {
                                "type": "copilot_tune",
                                "bot_id": entry.id,
                                "reason": f"profile:{copilot_profile}",
                            }
                        )

            running_managed = [
                b for b in bot_map.values()
                if str(b.status or "").lower() == "running" and self._is_orchestrator_managed(b.id, b.config or {})
            ]

            scored = []
            for b in running_managed:
                m = self._recent_metrics(db, b.id)
                score = (m.get("win_rate", 0.0) * 0.7) + (m.get("net_pnl", 0.0) * 0.1) - (m.get("consecutive_losses", 0) * 12)
                cfg = dict(b.config or {})
                if self._is_live_mainnet_config(cfg):
                    score += 1000.0
                if self._is_verified_for_production(cfg):
                    score += 250.0
                if str(cfg.get("executor") or "paper").strip().lower() == "paper":
                    score -= 150.0
                scored.append((score, b.id, m))

            scored.sort(reverse=True, key=lambda x: x[0])
            keep_ids = {item[1] for item in scored[: self.max_active_bots]}
            for _, bot_id, _ in scored[self.max_active_bots :]:
                self.bot_manager.stop_bot(bot_id)
                if bot_id in bot_map:
                    bot_map[bot_id].status = "stopped"
                actions.append({"type": "stop", "bot_id": bot_id, "reason": "capacity_rotation"})

            live_verified = []
            for b in bot_map.values():
                cfg = dict(b.config or {})
                if not self._is_live_mainnet_config(cfg):
                    continue
                if not self._is_verified_for_production(cfg):
                    continue
                if self._is_quarantined(cfg):
                    actions.append(
                        {
                            "type": "skip_start",
                            "bot_id": b.id,
                            "reason": "live_restart_guard_quarantined",
                        }
                    )
                    continue
                if str(b.status or "").lower() == "running":
                    conf = float(cfg.get("autoadapt_confidence") or 0.0)
                    live_verified.append((conf, b))
                    continue
                live_metrics = self._recent_metrics(db, b.id)
                if int(live_metrics.get("trade_count") or 0) <= 0:
                    warmup_ok = (
                        float(cfg.get("autoadapt_confidence") or 0.0) >= self.mainnet_min_confidence
                        and bool(
                            cfg.get("candidate_for_production")
                            or cfg.get("production_ready")
                            or cfg.get("autoadapt_mainnet_candidate")
                        )
                    )
                    if warmup_ok:
                        conf = float(cfg.get("autoadapt_confidence") or 0.0)
                        live_verified.append((conf, b))
                        continue
                    actions.append(
                        {
                            "type": "skip_start",
                            "bot_id": b.id,
                            "reason": "live_restart_guard_no_warmup_eligibility",
                        }
                    )
                    continue
                if not self._healthy_for_live_restart(live_metrics):
                    actions.append(
                        {
                            "type": "skip_start",
                            "bot_id": b.id,
                            "reason": "live_restart_guard_unhealthy_metrics",
                        }
                    )
                    continue
                conf = float(cfg.get("autoadapt_confidence") or 0.0)
                live_verified.append((conf, b))
            live_verified.sort(reverse=True, key=lambda item: item[0])

            running_live_verified_ids = {
                b.id
                for b in bot_map.values()
                if str(b.status or "").lower() == "running"
                and self._is_live_mainnet_config(dict(b.config or {}))
                and self._is_verified_for_production(dict(b.config or {}))
                and not self._is_quarantined(dict(b.config or {}))
            }

            if live_verified and not running_live_verified_ids and self.max_active_bots > 0:
                preferred_live = live_verified[0][1]
                if str(preferred_live.status or "").lower() != "running":
                    running_non_live = [
                        b for b in bot_map.values()
                        if str(b.status or "").lower() == "running"
                        and not self._is_live_mainnet_config(dict(b.config or {}))
                    ]
                    for b in running_non_live:
                        if active_count < self.max_active_bots:
                            break
                        self.bot_manager.stop_bot(b.id)
                        b.status = "stopped"
                        active_count = max(0, active_count - 1)
                        actions.append({"type": "stop", "bot_id": b.id, "reason": "prefer_live_verified"})

                    if active_count < self.max_active_bots:
                        preferred_cfg = dict(preferred_live.config or {})
                        preferred_cfg["production_policy"] = self._live_warmup_policy(
                            float(preferred_cfg.get("capital_allocation") or 0.0)
                        )
                        preferred_live.config = preferred_cfg
                        if self.bot_manager.start_bot(preferred_live.id, preferred_cfg):
                            preferred_live.status = "running"
                            active_count += 1
                            actions.append({"type": "start", "bot_id": preferred_live.id, "reason": "prefer_live_verified"})

            if decision_logs:
                for item in decision_logs:
                    db.add(
                        AutopilotDecisionLogDB(
                            trigger=str(item.get("trigger") or trigger),
                            bot_id=str(item.get("bot_id") or "unknown"),
                            symbol=item.get("symbol"),
                            profile=str(item.get("profile") or copilot_profile),
                            reason_code=str(item.get("reason_code") or "config_update"),
                            reason_text=str(item.get("reason_text") or ""),
                            market_context=dict(item.get("market_context") or {}),
                            metrics=dict(item.get("metrics") or {}),
                            changes=dict(item.get("changes") or {}),
                            extra=dict(item.get("extra") or {}),
                        )
                    )

            db.commit()

        if copilot_enabled:
            self._copilot_total["profile"] = copilot_profile
            if attack_window_active:
                self._copilot_total["reason"] = f"attack_window:{copilot_profile}"
            else:
                self._copilot_total["reason"] = f"market_regime:{copilot_profile}"
            self._copilot_total["last_updated"] = self._utc_now()
            self._save_copilot_total_state()

        if self.production_guard:
            try:
                await self.production_guard.scan_once(trigger="orchestrator-post")
            except Exception:
                pass

        running_after = list(self.bot_manager.active_bots.keys())
        report = {
            "generated_at": self._utc_now(),
            "trigger": trigger,
            "status": "ok",
            "symbols": symbols,
            "allocation": effective_allocation,
            "market_context_by_symbol": market_context_by_symbol,
            "recommendations_by_symbol": recommendations_by_symbol,
            "actions": actions,
            "opportunities": opportunities,
            "running_bots": running_after,
            "running_count": len(running_after),
            "max_active_bots": self.max_active_bots,
            "mainnet_autolaunch": self.mainnet_autolaunch,
            "mainnet_min_confidence": self.mainnet_min_confidence,
            "decision_logs_added": len(decision_logs),
            "copilot_total": self.copilot_total_status(),
        }
        self._last_report = report
        return report

    def latest_status(self):
        if not self._last_report:
            return {
                "generated_at": self._utc_now(),
                "status": "idle",
                "enabled": self.enabled,
                "running": self._running,
                "interval_sec": self.interval_sec,
                "copilot_total": self.copilot_total_status(),
            }

        return {
            **self._last_report,
            "enabled": self.enabled,
            "running": self._running,
            "interval_sec": self.interval_sec,
            "copilot_total": self.copilot_total_status(),
        }
