import asyncio
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import time
import os
import math

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env", override=False)
from apps.engine.market_data import MarketDataEngine
from apps.engine.paper_executor import PaperTradingExecutor
from apps.engine.paper_portfolio import PaperTradingPortfolio
from apps.engine.risk import RiskEngine
from apps.ai_engine.engine import AIEngine
from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, BotStatus, TradeSide, OrderLogDB, PositionDB, BotLearningStateDB, TradeSignal


def _to_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if value is None:
        return default
    return bool(value)

class BotInstance:
    def __init__(self, bot_id: str, config: Dict):
        self.bot_id = bot_id
        self.config = config
        self._ensure_self_management_defaults()
        self.status = BotStatus.STOPPED
        self._task = None
        
        # Strategy Factory
        strategy_name = config.get("strategy", "ema_cross")
        if "technical_pro" in strategy_name.lower():
            from apps.engine.technical_pro import TechnicalProStrategy
            self.strategy = TechnicalProStrategy()
        elif "algo_expert" in strategy_name.lower():
            from apps.engine.algo_expert import AlgoExpertStrategy
            self.strategy = AlgoExpertStrategy()
        elif "dynamic_reinvest" in strategy_name.lower():
            from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
            tp = config.get("take_profit_pct", 0.02)
            self.strategy = DynamicReinvestStrategy(take_profit_pct=tp)
        elif "grid_trading" in strategy_name.lower():
            from apps.engine.grid_trading import GridTradingStrategy
            upper = float(config.get("upper_limit", 70000))
            lower = float(config.get("lower_limit", 60000))
            grids = int(config.get("num_grids", 10))
            self.strategy = GridTradingStrategy(upper_limit=upper, lower_limit=lower, num_grids=grids)
        elif "adaptive_learning" in strategy_name.lower() or "arbitrario" in strategy_name.lower():
            from apps.engine.adaptive_learning import AdaptiveLearningStrategy
            short_window = int(config.get("adaptive_short_window", 12))
            long_window = int(config.get("adaptive_long_window", 48))
            base_amount = float(config.get("adaptive_base_amount", 0.01))
            self.strategy = AdaptiveLearningStrategy(
                short_window=short_window,
                long_window=long_window,
                base_amount=base_amount,
            )
        elif "paired_balanced" in strategy_name.lower() or "pair" in strategy_name.lower():
            from apps.engine.paired_balanced import PairedBalancedStrategy
            lookback = int(config.get("pair_lookback", 120) or 120)
            self.strategy = PairedBalancedStrategy(lookback=lookback)
        else:
            from apps.engine.ema_cross import EMACrossStrategy
            fast = config.get("fast_ema", 9)
            slow = config.get("slow_ema", 21)
            amount = float(config.get("trade_amount", config.get("amount", 0.002)) or 0.002)
            min_spread = float(config.get("ema_min_spread_pct", 0.0004) or 0.0004)
            min_slope = float(config.get("ema_min_slope_pct", 0.00015) or 0.00015)
            self.strategy = EMACrossStrategy(
                fast_ema=fast,
                slow_ema=slow,
                trade_amount=amount,
                min_spread_pct=min_spread,
                min_slope_pct=min_slope,
            )

        # Executor Factory — 'hyperliquid' for live trading, else paper
        executor_type = config.get("executor", "paper").lower()
        if executor_type == "hyperliquid":
            from apps.engine.hyperliquid_executor import HyperliquidExecutor
            env_testnet_default = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
            use_testnet = _to_bool(config.get("hyperliquid_testnet"), default=env_testnet_default)
            self.executor = HyperliquidExecutor(use_testnet=use_testnet)
            self.config["symbol"] = self.executor.normalize_symbol(self.config.get("symbol", "BTC/USDC:USDC"))
            self.mde = MarketDataEngine(exchange_id='hyperliquid', use_testnet=use_testnet)
            self.portfolio = None  # Live trading doesn't use a paper portfolio
            print(f"[BotManager] Bot {bot_id} using LIVE Hyperliquid executor ⚡ ({'TESTNET' if use_testnet else 'MAINNET'})")
        else:
            self.executor = PaperTradingExecutor(fee_rate=0.001)
            self.mde = MarketDataEngine()
            initial_balance = config.get("initial_balance", 10000.0)
            self.portfolio = PaperTradingPortfolio(bot_id, initial_balance=initial_balance)

        self.risk_engine = RiskEngine()
        self.ai_engine = AIEngine(model_name=str(config.get("ai_model") or "llama3"))

    def _position_snapshot(self, symbol: str, last_price: float):
        if last_price <= 0:
            return None

        if self.portfolio is not None:
            payload = dict((self.portfolio.positions or {}).get(symbol) or {})
            amount = float(payload.get("amount") or 0.0)
            entry_price = float(payload.get("avg_price") or 0.0)
            side = str(payload.get("side") or "long").lower()
            if amount <= 0 or entry_price <= 0:
                return None
        else:
            with SessionLocal() as db:
                pos = db.query(PositionDB).filter(
                    PositionDB.bot_id == self.bot_id,
                    PositionDB.symbol == symbol,
                    PositionDB.is_open == True,
                ).first()
                if not pos:
                    return None
                amount = float(pos.quantity or 0.0)
                entry_price = float(pos.entry_price or 0.0)
                side = str(pos.side or "long").lower()
                if amount <= 0 or entry_price <= 0:
                    return None

        if side == "short":
            profit_pct = (entry_price - last_price) / max(entry_price, 1e-12)
            unrealized_pnl = (entry_price - last_price) * amount
        else:
            profit_pct = (last_price - entry_price) / max(entry_price, 1e-12)
            unrealized_pnl = (last_price - entry_price) * amount

        return {
            "side": side,
            "amount": amount,
            "entry_price": entry_price,
            "profit_pct": float(profit_pct),
            "unrealized_pnl": float(unrealized_pnl),
        }

    def _is_live_mainnet_executor(self) -> bool:
        executor = str(self.config.get("executor") or "paper").strip().lower()
        is_testnet = _to_bool(self.config.get("hyperliquid_testnet"), default=False)
        return executor == "hyperliquid" and (not is_testnet)

    def _live_execution_guard(self, signal, symbol: str, last_price: float) -> tuple[bool, str]:
        """
        Evita churn en live:
        - no cerrar en zona gris (ni suficiente profit neto ni pérdida relevante)
        - no reentrar demasiado rápido o sin desplazamiento real de precio
        """
        if not self._is_live_mainnet_executor():
            return True, ""
        if not bool(self.config.get("live_execution_guard_enabled", True)):
            return True, ""
        if signal.side == TradeSide.HOLD:
            return True, ""

        state = self._load_learning_state(symbol)
        now_ts = float(time.time())
        min_trade_interval_sec = float(self.config.get("live_min_trade_interval_sec", 45.0) or 45.0)
        min_reentry_move_pct = float(self.config.get("live_min_reentry_move_pct", 0.001) or 0.001)
        min_close_profit_pct = float(self.config.get("live_min_close_profit_pct", 0.0012) or 0.0012)
        force_close_loss_pct = float(self.config.get("live_force_close_loss_pct", 0.0035) or 0.0035)
        taker_fee_pct = float(self.config.get("live_taker_fee_pct", os.getenv("HYPERLIQUID_TAKER_FEE_PCT", "0.00045")) or 0.00045)
        min_profit_from_costs = max((2.0 * taker_fee_pct) + 0.00035, min_close_profit_pct)

        last_exec_at = float(state.get("last_exec_at", 0.0) or 0.0)
        last_exec_price = float(state.get("last_exec_price", 0.0) or 0.0)

        snapshot = self._position_snapshot(symbol, last_price)
        if snapshot:
            side = str(snapshot.get("side") or "").lower()
            closing_signal = (
                (side == "long" and signal.side == TradeSide.SELL)
                or (side == "short" and signal.side == TradeSide.BUY)
            )
            if closing_signal:
                profit_pct = float(snapshot.get("profit_pct", 0.0) or 0.0)
                in_gray_zone = (-force_close_loss_pct < profit_pct < min_profit_from_costs)
                if in_gray_zone:
                    return False, (
                        f"close_guard_gray_zone profit_pct={round(profit_pct, 6)} "
                        f"(min_close={round(min_profit_from_costs, 6)}, force_loss={round(force_close_loss_pct, 6)})"
                    )
                return True, ""

        if last_exec_at > 0 and (now_ts - last_exec_at) < min_trade_interval_sec:
            return False, f"cooldown_guard {(now_ts - last_exec_at):.1f}s < {min_trade_interval_sec:.1f}s"

        if last_price > 0 and last_exec_price > 0:
            moved_pct = abs(last_price - last_exec_price) / max(last_exec_price, 1e-12)
            if moved_pct < min_reentry_move_pct:
                return False, f"reentry_guard move_pct={round(moved_pct, 6)} < {round(min_reentry_move_pct, 6)}"

        return True, ""

    def _position_execution_guard(self, signal, symbol: str, last_price: float, allow_short: bool) -> tuple[bool, str]:
        if signal.side == TradeSide.HOLD:
            return True, ""
        if signal.side != TradeSide.SELL:
            return True, ""

        snapshot = self._position_snapshot(symbol, last_price)
        if snapshot:
            side = str(snapshot.get("side") or "").lower()
            if side in {"long", "short"}:
                return True, ""

        if allow_short:
            return True, ""
        return False, "blocked_naked_short"

    def _is_ai_take_profit_scope_allowed(self) -> bool:
        # By default, AI TP only runs for bots that are live-mainnet and production-ready.
        only_production = bool(self.config.get("ai_take_profit_only_production", True))
        if not only_production:
            return True

        executor = str(self.config.get("executor") or "paper").strip().lower()
        is_live_mainnet = executor == "hyperliquid" and (not _to_bool(self.config.get("hyperliquid_testnet"), default=False))
        if not is_live_mainnet:
            return False

        prepared = bool(
            self.config.get("production_ready")
            or self.config.get("candidate_for_production")
            or self.config.get("analysis_approved")
        )
        return prepared

    async def _maybe_apply_ai_take_profit(self, signal, symbol: str, last_price: float, history: list):
        if not bool(self.config.get("ai_take_profit_enabled", True)):
            return signal
        if not self._is_ai_take_profit_scope_allowed():
            return signal
        if signal.side != TradeSide.HOLD:
            return signal

        snapshot = self._position_snapshot(symbol, last_price)
        if not snapshot or snapshot["unrealized_pnl"] <= 0:
            return signal

        state = self._load_learning_state(symbol)
        now_ts = float(time.time())
        cooldown_sec = float(self.config.get("ai_take_profit_cooldown_sec", 120) or 120)
        last_tp_ts = float(state.get("ai_last_take_profit_ts", 0.0) or 0.0)
        if (now_ts - last_tp_ts) < cooldown_sec:
            return signal

        closes = []
        for row in (history or []):
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                try:
                    closes.append(float(row[4]))
                except Exception:
                    pass
        returns = []
        for idx in range(1, len(closes)):
            prev = closes[idx - 1]
            cur = closes[idx]
            if prev > 0:
                returns.append((cur - prev) / prev)
        volatility_pct = 0.0
        trend_strength = 0.0
        if returns:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            volatility_pct = math.sqrt(max(variance, 0.0))
            trend_strength = mean_ret

        decision = await self.ai_engine.evaluate_take_profit(
            {
                "profit_pct": snapshot["profit_pct"],
                "unrealized_pnl": snapshot["unrealized_pnl"],
                "volatility_pct": volatility_pct,
                "trend_strength": trend_strength,
                "min_profit_pct": float(self.config.get("ai_min_take_profit_pct", 0.006) or 0.006),
                "hard_take_profit_pct": float(self.config.get("ai_hard_take_profit_pct", 0.02) or 0.02),
            }
        )

        if not bool(decision.get("should_take_profit")):
            return signal

        close_side = TradeSide.SELL if snapshot["side"] == "long" else TradeSide.BUY
        tp_signal = TradeSignal(
            symbol=symbol,
            side=close_side,
            amount=float(snapshot["amount"]),
            price=float(last_price),
            strategy_id=f"{signal.strategy_id}_ai_tp",
            meta={
                "reason": "ai_take_profit",
                "ai_decision": decision,
                "profit_pct": round(float(snapshot["profit_pct"]), 6),
                "unrealized_pnl": round(float(snapshot["unrealized_pnl"]), 8),
            },
        )
        state["ai_last_take_profit_ts"] = round(now_ts, 3)
        self._save_learning_state(symbol, state)
        print(f"[{self.bot_id}] AI take-profit triggered: {decision.get('reason')}")
        return tp_signal

    def _ensure_self_management_defaults(self):
        base_alloc = float(self.config.get("allocation", self.config.get("capital_allocation", 100.0)) or 100.0)
        self.config.setdefault("self_managed", True)
        self.config.setdefault("reinvest_ratio", 0.35)
        self.config.setdefault("min_allocation", max(10.0, round(base_alloc * 0.4, 2)))
        self.config.setdefault("max_allocation", max(round(base_alloc * 6.0, 2), 200.0))
        self.config.setdefault("experience_boost", True)
        self.config.setdefault(
            "live_execution_guard_enabled",
            _to_bool(os.getenv("LIVE_EXECUTION_GUARD_ENABLED"), default=True),
        )
        self.config.setdefault(
            "live_min_trade_interval_sec",
            float(os.getenv("LIVE_MIN_TRADE_INTERVAL_SEC", "45") or 45),
        )
        self.config.setdefault(
            "live_min_reentry_move_pct",
            float(os.getenv("LIVE_MIN_REENTRY_MOVE_PCT", "0.001") or 0.001),
        )
        self.config.setdefault(
            "live_min_close_profit_pct",
            float(os.getenv("LIVE_MIN_CLOSE_PROFIT_PCT", "0.0012") or 0.0012),
        )
        self.config.setdefault(
            "live_force_close_loss_pct",
            float(os.getenv("LIVE_FORCE_CLOSE_LOSS_PCT", "0.0035") or 0.0035),
        )
        self.config.setdefault(
            "live_taker_fee_pct",
            float(os.getenv("HYPERLIQUID_TAKER_FEE_PCT", "0.00045") or 0.00045),
        )
        self.config.setdefault(
            "ema_min_spread_pct",
            float(os.getenv("EMA_MIN_SPREAD_PCT", "0.0004") or 0.0004),
        )
        self.config.setdefault(
            "ema_min_slope_pct",
            float(os.getenv("EMA_MIN_SLOPE_PCT", "0.00015") or 0.00015),
        )

    def _load_learning_state(self, symbol: str):
        with SessionLocal() as db:
            row = (
                db.query(BotLearningStateDB)
                .filter(BotLearningStateDB.bot_id == self.bot_id, BotLearningStateDB.symbol == symbol)
                .first()
            )
            return dict(row.state or {}) if row else {}

    def _save_learning_state(self, symbol: str, state: Dict):
        if not isinstance(state, dict) or not state:
            return
        with SessionLocal() as db:
            row = (
                db.query(BotLearningStateDB)
                .filter(BotLearningStateDB.bot_id == self.bot_id, BotLearningStateDB.symbol == symbol)
                .first()
            )
            if not row:
                row = BotLearningStateDB(
                    bot_id=self.bot_id,
                    symbol=symbol,
                    strategy=self.config.get("strategy"),
                    state=state,
                )
                db.add(row)
            else:
                row.strategy = self.config.get("strategy")
                merged = dict(row.state or {})
                merged.update(state)
                row.state = merged
            db.commit()

    def _apply_self_management(
        self,
        symbol: str,
        realized_pnl: float,
        executed_side: str = "",
        executed_price: float = 0.0,
    ):
        if not bool(self.config.get("self_managed", True)):
            return

        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == self.bot_id).first()
            if not bot_entry:
                return

            row = (
                db.query(BotLearningStateDB)
                .filter(BotLearningStateDB.bot_id == self.bot_id, BotLearningStateDB.symbol == symbol)
                .first()
            )

            state = dict(row.state or {}) if row else {}
            total_trades = int(state.get("total_trades", 0) or 0) + 1
            wins = int(state.get("wins", 0) or 0)
            losses = int(state.get("losses", 0) or 0)
            if realized_pnl > 0:
                wins += 1
                state["loss_streak"] = 0
                state["win_streak"] = int(state.get("win_streak", 0) or 0) + 1
            elif realized_pnl < 0:
                losses += 1
                state["win_streak"] = 0
                state["loss_streak"] = int(state.get("loss_streak", 0) or 0) + 1

            cumulative_pnl = float(state.get("cumulative_pnl", 0.0) or 0.0) + float(realized_pnl)
            win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0

            history = list(state.get("recent_pnl", []) or [])
            history.append(round(float(realized_pnl), 8))
            history = history[-40:]

            cfg = dict(bot_entry.config or {})
            current_alloc = float(cfg.get("allocation", cfg.get("capital_allocation", 100.0)) or 100.0)
            reinvest_ratio = float(cfg.get("reinvest_ratio", self.config.get("reinvest_ratio", 0.35)) or 0.35)
            min_alloc = float(cfg.get("min_allocation", self.config.get("min_allocation", 10.0)) or 10.0)
            max_alloc = float(cfg.get("max_allocation", self.config.get("max_allocation", 200.0)) or 200.0)

            if realized_pnl > 0:
                alloc_delta = float(realized_pnl) * reinvest_ratio
                new_alloc = min(max_alloc, current_alloc + alloc_delta)
            elif realized_pnl < 0:
                alloc_delta = min(abs(float(realized_pnl)) * 0.2, current_alloc * 0.1)
                new_alloc = max(min_alloc, current_alloc - alloc_delta)
            else:
                new_alloc = current_alloc

            risk_cfg = dict(cfg.get("risk_config") or {})
            current_dd = float(risk_cfg.get("max_drawdown", 0.05) or 0.05)
            if win_rate >= 58 and cumulative_pnl > 0:
                current_dd = min(0.06, current_dd + 0.002)
            elif win_rate < 42 or int(state.get("loss_streak", 0) or 0) >= 3:
                current_dd = max(0.02, current_dd - 0.004)
            risk_cfg["max_drawdown"] = round(current_dd, 4)

            lev = float(cfg.get("leverage", 1.0) or 1.0)
            if int(state.get("win_streak", 0) or 0) >= 4 and win_rate > 55:
                lev = min(5.0, lev + 0.5)
            elif int(state.get("loss_streak", 0) or 0) >= 3:
                lev = max(1.0, lev - 0.5)

            cfg["allocation"] = round(new_alloc, 4)
            cfg["capital_allocation"] = round(new_alloc, 4)
            cfg["risk_config"] = risk_cfg
            cfg["leverage"] = round(lev, 2)

            state.update(
                {
                    "total_trades": total_trades,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(win_rate, 4),
                    "cumulative_pnl": round(cumulative_pnl, 8),
                    "recent_pnl": history,
                    "current_allocation": round(new_alloc, 8),
                    "risk_max_drawdown": round(current_dd, 6),
                    "leverage": round(lev, 4),
                    "last_realized_pnl": round(float(realized_pnl), 8),
                    "last_exec_side": str(executed_side or "").lower(),
                    "last_exec_price": round(float(executed_price or 0.0), 8),
                    "last_exec_at": round(float(time.time()), 3),
                }
            )

            bot_entry.config = cfg
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(bot_entry, "config")

            if not row:
                row = BotLearningStateDB(
                    bot_id=self.bot_id,
                    symbol=symbol,
                    strategy=self.config.get("strategy"),
                    state=state,
                )
                db.add(row)
            else:
                row.strategy = self.config.get("strategy")
                row.state = state

            db.commit()
            self.config.update(cfg)

    async def shutdown(self):
        """Gracefully close async resources used by this bot."""
        try:
            if getattr(self, "mde", None) and hasattr(self.mde, "close"):
                await self.mde.close()
        except Exception as e:
            print(f"[BotInstance] Warning closing market data engine for {self.bot_id}: {e}")

        try:
            if getattr(self, "executor", None) and hasattr(self.executor, "close"):
                await self.executor.close()
        except Exception as e:
            print(f"[BotInstance] Warning closing executor for {self.bot_id}: {e}")

    def reconfigure(self, new_config: Dict):
        """Update bot configuration and re-initialize strategy."""
        self.config.update(new_config)

        # Local imports keep startup lighter and avoid circular import issues.
        from apps.engine.technical_pro import TechnicalProStrategy
        from apps.engine.algo_expert import AlgoExpertStrategy
        from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
        from apps.engine.grid_trading import GridTradingStrategy
        from apps.engine.adaptive_learning import AdaptiveLearningStrategy
        from apps.engine.paired_balanced import PairedBalancedStrategy
        from apps.engine.ema_cross import EMACrossStrategy

        if self.config.get("executor", "paper").lower() == "hyperliquid" and getattr(self, "executor", None):
            if "symbol" in self.config:
                self.config["symbol"] = self.executor.normalize_symbol(self.config.get("symbol"))
        
        # Re-initialize Strategy with new parameters
        strategy_name = self.config.get("strategy", "ema_cross")
        if "technical_pro" in strategy_name.lower():
            self.strategy = TechnicalProStrategy()
        elif "algo_expert" in strategy_name.lower():
            self.strategy = AlgoExpertStrategy()
        elif "dynamic_reinvest" in strategy_name.lower():
            tp = self.config.get("take_profit_pct", 0.02)
            self.strategy = DynamicReinvestStrategy(take_profit_pct=tp)
        elif "grid_trading" in strategy_name.lower():
            upper = float(self.config.get("upper_limit", 70000))
            lower = float(self.config.get("lower_limit", 60000))
            grids = int(self.config.get("num_grids", 10))
            self.strategy = GridTradingStrategy(upper_limit=upper, lower_limit=lower, num_grids=grids)
        elif "adaptive_learning" in strategy_name.lower() or "arbitrario" in strategy_name.lower():
            short_window = int(self.config.get("adaptive_short_window", 12))
            long_window = int(self.config.get("adaptive_long_window", 48))
            base_amount = float(self.config.get("adaptive_base_amount", 0.01))
            self.strategy = AdaptiveLearningStrategy(
                short_window=short_window,
                long_window=long_window,
                base_amount=base_amount,
            )
        elif "paired_balanced" in strategy_name.lower() or "pair" in strategy_name.lower():
            lookback = int(self.config.get("pair_lookback", 120) or 120)
            self.strategy = PairedBalancedStrategy(lookback=lookback)
        else:
            fast = self.config.get("fast_ema", 9)
            slow = self.config.get("slow_ema", 21)
            amount = float(self.config.get("trade_amount", self.config.get("amount", 0.002)) or 0.002)
            min_spread = float(self.config.get("ema_min_spread_pct", 0.0004) or 0.0004)
            min_slope = float(self.config.get("ema_min_slope_pct", 0.00015) or 0.00015)
            self.strategy = EMACrossStrategy(
                fast_ema=fast,
                slow_ema=slow,
                trade_amount=amount,
                min_spread_pct=min_spread,
                min_slope_pct=min_slope,
            )
        
        print(f"[BotInstance] Bot {self.bot_id} reconfigured with new parameters.")

    async def _execute_and_persist_signal(self, signal, strategy_name: str, executor_type: str, allow_short: bool = False):
        execution = await self.executor.execute(signal)
        if execution.status == "failed":
            return False, 0.0, 0.0

        fee_amount = 0.0
        pnl_amount = 0.0
        execution_accepted = True

        if self.portfolio is not None:
            portfolio_update = await self.portfolio.process_execution(
                execution,
                signal.side,
                signal.symbol,
                allow_short=allow_short,
            )
            if portfolio_update.get("success"):
                fee_amount = float(portfolio_update.get("fee", 0.0) or 0.0)
                pnl_amount = float(portfolio_update.get("pnl", 0.0) or 0.0)
                with SessionLocal() as db:
                    trade_entry = TradeDB(
                        bot_id=self.bot_id,
                        symbol=signal.symbol,
                        side=signal.side,
                        price=execution.avg_price,
                        amount=execution.filled_amount,
                        fee=fee_amount,
                        pnl=pnl_amount,
                        meta=signal.meta,
                    )
                    db.add(trade_entry)
                    db.commit()
                print(f"[{self.bot_id}] Trade: {signal.side} {signal.symbol} | P&L: ${pnl_amount:.2f}")
            else:
                execution_accepted = False
                print(f"[{self.bot_id}] Trade rejected by portfolio: {portfolio_update.get('reason')}")
        else:
            fee_amount = float(getattr(execution, 'fee', 0.0) or 0.0)
            pnl_amount = 0.0
            with SessionLocal() as db:
                existing_pos = db.query(PositionDB).filter(
                    PositionDB.bot_id == self.bot_id,
                    PositionDB.symbol == signal.symbol,
                    PositionDB.is_open == True
                ).first()

                if signal.side == TradeSide.SELL and existing_pos:
                    closed_qty = min(existing_pos.quantity, execution.filled_amount)
                    pnl_amount = (execution.avg_price - existing_pos.entry_price) * closed_qty

                trade_entry = TradeDB(
                    bot_id=self.bot_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    price=execution.avg_price,
                    amount=execution.filled_amount,
                    fee=fee_amount,
                    pnl=pnl_amount,
                    meta={"order_id": execution.order_id, "status": execution.status},
                )
                db.add(trade_entry)
                db.commit()
            print(f"[{self.bot_id}] ⚡ LIVE: {signal.side} {signal.symbol} @ ${execution.avg_price:,.2f} | Order #{execution.order_id}")

        if execution_accepted:
            with SessionLocal() as db:
                order_log = OrderLogDB(
                    bot_id=self.bot_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    status="closed",
                    price=execution.avg_price,
                    amount=signal.amount,
                    filled_amount=execution.filled_amount,
                    fee=fee_amount,
                    pnl=pnl_amount,
                    exchange_order_id=execution.order_id,
                    strategy=strategy_name,
                    executor=executor_type,
                    meta=signal.meta,
                )
                db.add(order_log)

                existing_pos = db.query(PositionDB).filter(
                    PositionDB.bot_id == self.bot_id,
                    PositionDB.symbol == signal.symbol,
                    PositionDB.is_open == True
                ).first()

                if signal.side == TradeSide.BUY:
                    if existing_pos and existing_pos.side == "short":
                        new_qty = existing_pos.quantity - execution.filled_amount
                        existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                        existing_pos.current_price = execution.avg_price
                        if new_qty <= 0.0001:
                            existing_pos.is_open = False
                            existing_pos.quantity = 0
                            existing_pos.unrealized_pnl = pnl_amount
                        else:
                            existing_pos.quantity = new_qty
                    elif existing_pos:
                        total_qty = existing_pos.quantity + execution.filled_amount
                        avg_price = (existing_pos.entry_price * existing_pos.quantity + execution.avg_price * execution.filled_amount) / max(total_qty, 1e-12)
                        existing_pos.entry_price = avg_price
                        existing_pos.quantity = total_qty
                        existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                        existing_pos.current_price = execution.avg_price
                    else:
                        new_pos = PositionDB(
                            bot_id=self.bot_id,
                            symbol=signal.symbol,
                            side="long",
                            entry_price=execution.avg_price,
                            quantity=execution.filled_amount,
                            current_price=execution.avg_price,
                            fee_paid=fee_amount,
                            is_open=True,
                        )
                        db.add(new_pos)
                elif signal.side == TradeSide.SELL:
                    if existing_pos and existing_pos.side == "long":
                        new_qty = existing_pos.quantity - execution.filled_amount
                        if new_qty <= 0.0001:
                            existing_pos.is_open = False
                            existing_pos.quantity = 0
                        else:
                            existing_pos.quantity = new_qty
                        existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                        existing_pos.current_price = execution.avg_price
                        existing_pos.unrealized_pnl = pnl_amount
                    elif allow_short:
                        if existing_pos and existing_pos.side == "short":
                            total_qty = existing_pos.quantity + execution.filled_amount
                            avg_price = (existing_pos.entry_price * existing_pos.quantity + execution.avg_price * execution.filled_amount) / max(total_qty, 1e-12)
                            existing_pos.entry_price = avg_price
                            existing_pos.quantity = total_qty
                            existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                            existing_pos.current_price = execution.avg_price
                        else:
                            new_pos = PositionDB(
                                bot_id=self.bot_id,
                                symbol=signal.symbol,
                                side="short",
                                entry_price=execution.avg_price,
                                quantity=execution.filled_amount,
                                current_price=execution.avg_price,
                                fee_paid=fee_amount,
                                is_open=True,
                            )
                            db.add(new_pos)

                db.commit()

            self._apply_self_management(
                signal.symbol,
                float(pnl_amount) - float(fee_amount),
                executed_side=(signal.side.value if hasattr(signal.side, "value") else str(signal.side)),
                executed_price=float(execution.avg_price or 0.0),
            )

        return execution_accepted, pnl_amount, fee_amount

    async def _run_paired_balanced(self):
        strategy_name = self.config.get("strategy", "paired_balanced")
        executor_type = self.config.get("executor", "paper")

        symbol_a = str(self.config.get("pair_symbol_a") or self.config.get("symbol") or "BTC/USDT")
        symbol_b = str(self.config.get("pair_symbol_b") or "ETH/USDT")
        pair_key = f"{symbol_a}|{symbol_b}"
        min_hold_sec = float(self.config.get("pair_min_hold_sec", 90.0) or 90.0)
        min_rebalance_sec = float(self.config.get("pair_rebalance_sec", 30.0) or 30.0)

        print(f"Bot {self.bot_id} paired-balanced loop: {symbol_a} vs {symbol_b}")

        while self.status == BotStatus.RUNNING:
            try:
                ticker_a = await self.mde.fetch_ticker(symbol_a)
                ticker_b = await self.mde.fetch_ticker(symbol_b)
                price_a = float(ticker_a.get("last") or 0.0)
                price_b = float(ticker_b.get("last") or 0.0)

                if price_a <= 0 or price_b <= 0:
                    await asyncio.sleep(10)
                    continue

                if self.portfolio:
                    self.portfolio.update_market_prices({symbol_a: price_a, symbol_b: price_b})

                history_a = await self.mde.fetch_ohlcv(symbol_a, limit=int(self.config.get("pair_lookback", 120) or 120) + 20)
                history_b = await self.mde.fetch_ohlcv(symbol_b, limit=int(self.config.get("pair_lookback", 120) or 120) + 20)
                pair_state = self._load_learning_state(pair_key)

                decision = self.strategy.evaluate({
                    "history_a": history_a,
                    "history_b": history_b,
                    "entry_z": float(self.config.get("pair_entry_z", 1.4) or 1.4),
                    "exit_z": float(self.config.get("pair_exit_z", 0.25) or 0.25),
                    "min_correlation": float(self.config.get("pair_min_correlation", 0.35) or 0.35),
                    "enable_cadf": bool(self.config.get("pair_enable_cadf", True)),
                    "cadf_alpha": float(self.config.get("pair_cadf_alpha", 0.05) or 0.05),
                })

                portfolio_summary = self.portfolio.get_summary() if self.portfolio else {}
                positions = dict(portfolio_summary.get("positions") or {})
                pos_a = dict(positions.get(symbol_a) or {})
                pos_b = dict(positions.get(symbol_b) or {})
                has_pair = bool(pos_a) and bool(pos_b)

                pnl_a = 0.0
                pnl_b = 0.0
                if pos_a:
                    side_a = str(pos_a.get("side") or "long")
                    amt_a = float(pos_a.get("amount") or 0.0)
                    entry_a = float(pos_a.get("avg_price") or 0.0)
                    pnl_a = ((price_a - entry_a) * amt_a) if side_a == "long" else ((entry_a - price_a) * amt_a)
                if pos_b:
                    side_b = str(pos_b.get("side") or "long")
                    amt_b = float(pos_b.get("amount") or 0.0)
                    entry_b = float(pos_b.get("avg_price") or 0.0)
                    pnl_b = ((price_b - entry_b) * amt_b) if side_b == "long" else ((entry_b - price_b) * amt_b)
                pair_unrealized = pnl_a + pnl_b

                allocation = float(self.config.get("allocation", self.config.get("capital_allocation", 100.0)) or 100.0)
                stop_loss_abs = max(1.0, allocation * float(self.config.get("pair_stop_loss_pct", 0.015) or 0.015))
                take_profit_abs = max(1.0, allocation * float(self.config.get("pair_take_profit_pct", 0.01) or 0.01))
                profit_lock_abs = max(0.5, allocation * float(self.config.get("pair_profit_lock_pct", 0.004) or 0.004))

                best_pair_pnl = float(pair_state.get("best_pair_pnl", 0.0) or 0.0)
                if has_pair:
                    best_pair_pnl = max(best_pair_pnl, pair_unrealized)

                now_ts = float(time.time())
                last_action_ts = float(pair_state.get("last_action_ts", 0.0) or 0.0)
                can_react = (now_ts - last_action_ts) >= min_rebalance_sec

                should_close = False
                close_reason = ""
                if has_pair and can_react:
                    if pair_unrealized <= -stop_loss_abs:
                        should_close = True
                        close_reason = "pair_stop_loss"
                    elif pair_unrealized >= take_profit_abs:
                        should_close = True
                        close_reason = "pair_take_profit"
                    elif best_pair_pnl > 0 and pair_unrealized > 0 and pair_unrealized <= (best_pair_pnl - profit_lock_abs):
                        should_close = True
                        close_reason = "pair_profit_lock"
                    elif decision.action == "close_pair":
                        opened_at = float(pair_state.get("pair_opened_at", 0.0) or 0.0)
                        if opened_at <= 0 or (now_ts - opened_at) >= min_hold_sec:
                            should_close = True
                            close_reason = decision.reason

                if should_close:
                    close_signals = []
                    if pos_a:
                        close_signals.append((symbol_a, TradeSide.SELL if str(pos_a.get("side") or "long") == "long" else TradeSide.BUY, float(pos_a.get("amount") or 0.0), price_a))
                    if pos_b:
                        close_signals.append((symbol_b, TradeSide.SELL if str(pos_b.get("side") or "long") == "long" else TradeSide.BUY, float(pos_b.get("amount") or 0.0), price_b))

                    all_closed = True
                    for sym, side, amount, px in close_signals:
                        sig = TradeSignal(
                            symbol=sym,
                            side=side,
                            amount=round(amount, 6),
                            price=px,
                            strategy_id="Paired_Balanced_v1",
                            meta={
                                "pair_key": pair_key,
                                "pair_action": "close",
                                "reduce_only": True,
                                "close_reason": close_reason,
                                "zscore": round(float(decision.zscore), 6),
                                "correlation": round(float(decision.correlation), 6),
                            },
                        )
                        ok, _, _ = await self._execute_and_persist_signal(sig, strategy_name, executor_type, allow_short=True)
                        all_closed = all_closed and ok

                    if all_closed:
                        pair_state.update({
                            "pair_open": False,
                            "pair_opened_at": 0.0,
                            "last_action_ts": now_ts,
                            "best_pair_pnl": 0.0,
                            "last_pair_close_reason": close_reason,
                            "last_pair_unrealized": round(pair_unrealized, 8),
                        })
                        self._save_learning_state(pair_key, pair_state)
                        await asyncio.sleep(10)
                        continue

                if (not has_pair) and can_react and decision.action == "open_pair":
                    factor = self.strategy.allocation_factor(decision.correlation, decision.zscore)
                    leg_usd = max(8.0, allocation * 0.48 * factor)
                    qty_a = max(0.000001, leg_usd / price_a)
                    qty_b = max(0.000001, leg_usd / price_b)

                    sig_a = TradeSignal(
                        symbol=symbol_a,
                        side=decision.side_a,
                        amount=round(qty_a, 6),
                        price=price_a,
                        strategy_id="Paired_Balanced_v1",
                        meta={
                            "pair_key": pair_key,
                            "pair_action": "open",
                            "leg": "A",
                            "zscore": round(float(decision.zscore), 6),
                            "correlation": round(float(decision.correlation), 6),
                        },
                    )
                    sig_b = TradeSignal(
                        symbol=symbol_b,
                        side=decision.side_b,
                        amount=round(qty_b, 6),
                        price=price_b,
                        strategy_id="Paired_Balanced_v1",
                        meta={
                            "pair_key": pair_key,
                            "pair_action": "open",
                            "leg": "B",
                            "zscore": round(float(decision.zscore), 6),
                            "correlation": round(float(decision.correlation), 6),
                        },
                    )

                    ok_a, _, _ = await self._execute_and_persist_signal(sig_a, strategy_name, executor_type, allow_short=True)
                    ok_b, _, _ = await self._execute_and_persist_signal(sig_b, strategy_name, executor_type, allow_short=True)

                    if ok_a and ok_b:
                        pair_state.update({
                            "pair_open": True,
                            "pair_opened_at": now_ts,
                            "last_action_ts": now_ts,
                            "best_pair_pnl": 0.0,
                            "last_open_zscore": round(float(decision.zscore), 8),
                            "last_open_corr": round(float(decision.correlation), 8),
                            "last_pair_unrealized": 0.0,
                        })
                    else:
                        pair_state.update({
                            "pair_open": False,
                            "last_action_ts": now_ts,
                            "last_open_error": "partial_or_failed_execution",
                        })
                    self._save_learning_state(pair_key, pair_state)
                    await asyncio.sleep(10)
                    continue

                pair_state.update({
                    "last_eval_at": now_ts,
                    "last_action_ts": last_action_ts,
                    "pair_open": has_pair,
                    "best_pair_pnl": round(best_pair_pnl, 8),
                    "last_pair_unrealized": round(pair_unrealized, 8),
                    "last_zscore": round(float(decision.zscore), 8),
                    "last_correlation": round(float(decision.correlation), 8),
                    "last_decision": decision.reason,
                })
                self._save_learning_state(pair_key, pair_state)
                await asyncio.sleep(10)

            except Exception as pair_error:
                print(f"[{self.bot_id}] Paired loop error: {pair_error}")
                await asyncio.sleep(10)

    async def run(self):
        self.status = BotStatus.RUNNING
        strategy_name = self.config.get("strategy", "ema_cross")
        
        # Sync initial state to DB
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == self.bot_id).first()
            if not bot_entry:
                bot_entry = BotDB(id=self.bot_id, strategy=self.config.get("strategy"), status="running", config=self.config)
                db.add(bot_entry)
            else:
                bot_entry.status = "running"
            db.commit()

        print(f"Bot {self.bot_id} starting loop...")
        try:
            if "paired_balanced" in strategy_name.lower() or "pair" in strategy_name.lower():
                await self._run_paired_balanced()
                return

            while self.status == BotStatus.RUNNING:
                symbol = self.config.get("symbol", "BTC/USDT")
                executor_type = str(self.config.get("executor", "paper") or "paper").lower()
                default_loop_sleep = 20.0 if executor_type == "hyperliquid" else 10.0
                loop_sleep_sec = max(5.0, float(self.config.get("loop_interval_sec", default_loop_sleep) or default_loop_sleep))
                # 1. Fetch data
                ticker = await self.mde.fetch_ticker(symbol)
                last_price = ticker.get('last', 0.0)

                if self.portfolio is not None and last_price:
                    self.portfolio.update_market_prices({symbol: float(last_price)})
                
                # Fetch history for technical analysis if needed
                history = await self.mde.fetch_ohlcv(symbol, limit=250)
                learning_state = self._load_learning_state(symbol)
                
                # 2. Analyze
                signal = await self.strategy.analyze({
                    'last_price': last_price, 
                    'symbol': symbol,
                    'history': history,
                    'portfolio': self.portfolio.get_summary() if self.portfolio else {},
                    'allocation': float(self.config.get('allocation', self.config.get('capital_allocation', 100.0)) or 100.0),
                    'adaptive_min_flip_move_pct': float(self.config.get('adaptive_min_flip_move_pct', 0.0012) or 0.0012),
                    'adaptive_min_reentry_move_pct': float(self.config.get('adaptive_min_reentry_move_pct', 0.0008) or 0.0008),
                    'adaptive_min_flip_interval_sec': float(self.config.get('adaptive_min_flip_interval_sec', 45.0) or 45.0),
                    'adaptive_bootstrap_unlock_sec': float(self.config.get('adaptive_bootstrap_unlock_sec', 2700.0) or 2700.0),
                    'adaptive_bootstrap_probe_interval_sec': float(self.config.get('adaptive_bootstrap_probe_interval_sec', 1800.0) or 1800.0),
                    'learning_state': learning_state,
                })

                updated_learning_state = (signal.meta or {}).get('learning_state') if getattr(signal, 'meta', None) else None
                if isinstance(updated_learning_state, dict):
                    self._save_learning_state(symbol, updated_learning_state)

                signal = await self._maybe_apply_ai_take_profit(signal, symbol, float(last_price or 0.0), history)
                
                # 3. Validate with Risk Engine
                risk_result = await self.risk_engine.validate(signal)
                
                if risk_result.approved and signal.side != TradeSide.HOLD:
                    pos_ok, pos_reason = self._position_execution_guard(
                        signal,
                        symbol,
                        float(last_price or 0.0),
                        bool(self.config.get("allow_short", False)),
                    )
                    if not pos_ok:
                        print(f"[{self.bot_id}] Signal blocked by position guard: {pos_reason}")
                        await asyncio.sleep(loop_sleep_sec)
                        continue
                    guard_ok, guard_reason = self._live_execution_guard(signal, symbol, float(last_price or 0.0))
                    if not guard_ok:
                        print(f"[{self.bot_id}] Live execution skipped by guard: {guard_reason}")
                        await asyncio.sleep(loop_sleep_sec)
                        continue
                    await self._execute_and_persist_signal(
                        signal,
                        strategy_name,
                        executor_type,
                        allow_short=bool(self.config.get("allow_short", False)),
                    )
                elif not risk_result.approved:
                    print(f"[{self.bot_id}] Trade rejected by risk engine: {risk_result.reason}")
                else:
                    print(f"[{self.bot_id}] Holding position...")
                    
                await asyncio.sleep(loop_sleep_sec)
        except Exception as e:
            print(f"Bot {self.bot_id} failed: {e}")
        finally:
            self.status = BotStatus.STOPPED
            with SessionLocal() as db:
                bot_entry = db.query(BotDB).filter(BotDB.id == self.bot_id).first()
                if bot_entry:
                    bot_entry.status = "stopped"
                    db.commit()
            await self.shutdown()
            print(f"Bot {self.bot_id} loop ended.")

class BotManager:
    def __init__(self):
        self.active_bots: Dict[str, BotInstance] = {}

    def start_bot(self, bot_id: str, config: Dict):
        if bot_id in self.active_bots:
            return False
        
        bot = BotInstance(bot_id, config)
        self.active_bots[bot_id] = bot
        bot._task = asyncio.create_task(bot.run())
        return True

    async def adopt_position(self, bot_id: str, symbol: str, strategy: str, config: Dict):
        """
        Asocia una posición abierta existente con un nuevo bot.
        """
        with SessionLocal() as db:
            # 1. Crear el bot
            bot_entry = BotDB(
                id=bot_id,
                strategy=strategy,
                status="running",
                config=config,
                created_at=datetime.utcnow()
            )
            db.add(bot_entry)
            
            # 2. Buscar posición huérfana en PositionDB (bot_id='ORPHAN') o simplemente crear vínculo si no existe
            existing_pos = db.query(PositionDB).filter(
                PositionDB.symbol == symbol,
                PositionDB.bot_id == "ORPHAN",
                PositionDB.is_open == True
            ).first()
            
            if existing_pos:
                existing_pos.bot_id = bot_id
                print(f"[BotManager] Position for {symbol} adopted by bot {bot_id}")
            
            db.commit()
            
            # 3. Iniciar el bot en memoria
            return self.start_bot(bot_id, config)

    def stop_bot(self, bot_id: str):
        bot = self.active_bots.get(bot_id)
        if bot:
            bot.status = BotStatus.STOPPED
            if bot._task:
                bot._task.cancel()
            del self.active_bots[bot_id]

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(bot.shutdown())
            except RuntimeError:
                try:
                    asyncio.run(bot.shutdown())
                except Exception as e:
                    print(f"[BotManager] Warning during shutdown for {bot_id}: {e}")

        # Always update DB status, even if bot wasn't in active memory
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.status = "stopped"
                db.commit()
                return True

        return bool(bot)  # Return True only if was in memory but not in DB

    def delete_bot(self, bot_id: str):
        # 1. Stop if running
        self.stop_bot(bot_id)
        # 2. Delete from DB and close positions
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                db.delete(bot_entry)
            
            # Close associate positions too
            db.query(PositionDB).filter(PositionDB.bot_id == bot_id).update({"is_open": False, "updated_at": datetime.utcnow()})
            db.query(BotLearningStateDB).filter(BotLearningStateDB.bot_id == bot_id).delete()
            
            db.commit()
            return True
        return False

    def archive_bot(self, bot_id: str):
        # 1. Stop if running
        self.stop_bot(bot_id)
        # 2. Mark as archived in DB
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.is_archived = True
                db.commit()
                return True
        return False

    def restore_bot(self, bot_id: str):
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.is_archived = False
                db.commit()
                return True
        return False

    def update_bot_config(self, bot_id: str, new_config: Dict):
        """Update bot configuration in DB and update active instance if running."""
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if not bot_entry:
                return False
            
            # Merge configs - copy to ensure SQLAlchemy detects change
            current_config = dict(bot_entry.config or {})
            current_config.update(new_config)
            
            # Explicitly flag as modified by re-assigning
            bot_entry.config = current_config
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(bot_entry, "config")
            db.commit()
            
            # If bot is running, update it in memory
            if bot_id in self.active_bots:
                self.active_bots[bot_id].reconfigure(current_config)
                
            return True

    async def resume_bots(self):
        print("[BotManager] Resuming active bots from database...")
        with SessionLocal() as db:
            active_db_bots = db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all()
            if not active_db_bots:
                print("[BotManager] No bots to resume.")
                return
            for db_bot in active_db_bots:
                if db_bot.id not in self.active_bots:
                    print(f"[BotManager] Resuming bot: {db_bot.id} (strategy={db_bot.strategy})")
                    self.start_bot(db_bot.id, db_bot.config)
                else:
                    print(f"[BotManager] Bot {db_bot.id} already in memory — skipping.")
        print(f"[BotManager] {len(self.active_bots)} bot(s) running.")

if __name__ == "__main__":
    async def main():
        print("Bot Manager Worker started. Standby mode.")
        while True:
            await asyncio.sleep(3600)
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
