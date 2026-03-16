import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from apps.engine.bot_advisor import build_bot_advice
from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB


class AdaptiveOrchestratorService:
    def __init__(self, bot_manager, production_guard=None):
        self.bot_manager = bot_manager
        self.production_guard = production_guard
        self.interval_sec = int(os.getenv("AUTO_ORCHESTRATOR_INTERVAL_SEC", "180"))
        self.enabled = os.getenv("AUTO_ORCHESTRATOR_ENABLED", "false").lower() == "true"
        self.default_symbol = os.getenv("AUTO_ORCHESTRATOR_SYMBOL", "BTC/USDT")
        self.default_allocation = float(os.getenv("AUTO_ORCHESTRATOR_ALLOCATION", "350"))
        self.max_active_bots = int(os.getenv("AUTO_ORCHESTRATOR_MAX_ACTIVE", "3"))
        self.window_trades = int(os.getenv("AUTO_ORCHESTRATOR_WINDOW_TRADES", "30"))

        self._running = False
        self._task = None
        self._last_report: Dict[str, Any] = {}

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

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
    def _is_orchestrator_managed(bot_id: str, config: Dict[str, Any]) -> bool:
        cfg = config or {}
        if str(cfg.get("managed_by") or "").lower() == "adaptive_orchestrator":
            return True
        if str(bot_id or "").upper().startswith("AUTO-ADAPT-"):
            return True
        return False

    def _managed_bot_id(self, horizon: str) -> str:
        return f"AUTO-ADAPT-{horizon.upper()}"

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
        effective_symbol = (symbol or self.default_symbol or "BTC/USDT").strip() or "BTC/USDT"
        effective_allocation = float(allocation or self.default_allocation or 350.0)
        effective_allocation = max(50.0, effective_allocation)

        actions: List[Dict[str, Any]] = []

        if self.production_guard:
            try:
                await self.production_guard.scan_once(trigger="orchestrator-pre")
            except Exception:
                pass

        with SessionLocal() as db:
            analysis = await build_bot_advice(db, symbol=effective_symbol, allocation=effective_allocation)
            recommendations = analysis.get("recommendations", [])
            touched_bots = set()

            bots = db.query(BotDB).filter(BotDB.is_archived == False).all()
            bot_map = {b.id: b for b in bots}
            active_count = sum(1 for b in bots if str(b.status or "").lower() == "running")

            for rec in recommendations:
                horizon = (rec.get("horizon") or "medio").strip().lower()
                action = rec.get("recommended_action")
                managed_id = self._managed_bot_id(horizon)

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

                    if managed_id in bot_map:
                        bot_entry = bot_map[managed_id]
                        bot_entry.config = base_cfg
                        bot_entry.strategy = base_cfg.get("strategy", bot_entry.strategy)
                        bot_entry.capital_allocation = float(base_cfg.get("capital_allocation") or 0.0)
                        if str(bot_entry.status or "").lower() != "running" and active_count < self.max_active_bots:
                            if self.bot_manager.start_bot(managed_id, base_cfg):
                                bot_entry.status = "running"
                                active_count += 1
                                actions.append({"type": "start", "bot_id": managed_id, "reason": f"create_new:{horizon}"})
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
                        actions.append({"type": "create", "bot_id": managed_id, "reason": f"create_new:{horizon}"})

                        if active_count < self.max_active_bots and self.bot_manager.start_bot(managed_id, base_cfg):
                            bot_entry.status = "running"
                            active_count += 1
                            actions.append({"type": "start", "bot_id": managed_id, "reason": f"new_managed:{horizon}"})

                elif action in {"tune_existing", "reduce_risk"}:
                    target_id = rec.get("recommended_bot_id")
                    if not target_id or target_id not in bot_map:
                        continue

                    if target_id in touched_bots:
                        actions.append({"type": "skip", "bot_id": target_id, "reason": "already_tuned_this_cycle"})
                        continue

                    target_entry = bot_map[target_id]
                    target_cfg = dict(target_entry.config or {})
                    target_executor = str(target_cfg.get("executor") or "paper").lower()
                    target_testnet = bool(target_cfg.get("hyperliquid_testnet", False))

                    if target_executor == "hyperliquid" and not target_testnet:
                        actions.append({
                            "type": "skip",
                            "bot_id": target_id,
                            "reason": "live_executor_protected",
                        })
                        continue

                    updated = dict(target_entry.config or {})
                    updated.update(rec.get("edited_config") or {})
                    updated["autoadapt_last_horizon"] = horizon
                    updated.setdefault("production_policy", self._strict_policy(float(updated.get("capital_allocation") or 0.0)))
                    target_entry.config = updated
                    touched_bots.add(target_id)
                    actions.append({"type": "tune", "bot_id": target_id, "reason": action})

                    if action == "reduce_risk" and str(target_entry.status or "").lower() == "running":
                        metrics = self._recent_metrics(db, target_id)
                        if metrics.get("consecutive_losses", 0) > 2 or metrics.get("net_pnl", 0.0) < -5.0:
                            self.bot_manager.stop_bot(target_id)
                            target_entry.status = "stopped"
                            actions.append({"type": "stop", "bot_id": target_id, "reason": "risk_guard:reduce_risk"})

            running_managed = [
                b for b in bot_map.values()
                if str(b.status or "").lower() == "running" and self._is_orchestrator_managed(b.id, b.config or {})
            ]

            scored = []
            for b in running_managed:
                m = self._recent_metrics(db, b.id)
                score = (m.get("win_rate", 0.0) * 0.7) + (m.get("net_pnl", 0.0) * 0.1) - (m.get("consecutive_losses", 0) * 12)
                scored.append((score, b.id, m))

            scored.sort(reverse=True, key=lambda x: x[0])
            keep_ids = {item[1] for item in scored[: self.max_active_bots]}
            for _, bot_id, _ in scored[self.max_active_bots :]:
                self.bot_manager.stop_bot(bot_id)
                if bot_id in bot_map:
                    bot_map[bot_id].status = "stopped"
                actions.append({"type": "stop", "bot_id": bot_id, "reason": "capacity_rotation"})

            db.commit()

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
            "symbol": effective_symbol,
            "allocation": effective_allocation,
            "market_context": analysis.get("market_context", {}),
            "recommendations": recommendations,
            "actions": actions,
            "running_bots": running_after,
            "running_count": len(running_after),
            "max_active_bots": self.max_active_bots,
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
            }

        return {
            **self._last_report,
            "enabled": self.enabled,
            "running": self._running,
            "interval_sec": self.interval_sec,
        }
