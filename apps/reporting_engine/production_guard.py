import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, BotAlertDB


class ProductionGuardService:
    def __init__(self, bot_manager):
        self.bot_manager = bot_manager
        self.interval_sec = int(os.getenv("PRODUCTION_GUARD_INTERVAL_SEC", "60"))
        self.enabled = os.getenv("PRODUCTION_GUARD_ENABLED", "true").lower() == "true"
        self._task = None
        self._running = False
        self._last_status: List[Dict[str, Any]] = []
        self._last_emitted_key: Dict[str, str] = {}

    async def start(self):
        if not self.enabled or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self.scan_once(trigger="scheduled")
            except Exception as e:
                print(f"[ProductionGuard] scan error: {e}")
            await asyncio.sleep(self.interval_sec)

    def _policy(self, bot: BotDB) -> Dict[str, Any]:
        config = dict(bot.config or {})
        policy = dict(config.get("production_policy") or {})
        capital_allocation = float(config.get("capital_allocation") or bot.capital_allocation or 0.0)
        return {
            "enabled": bool(policy.get("enabled", True)),
            "window_trades": int(policy.get("window_trades", 30)),
            "min_trades": int(policy.get("min_trades", 8)),
            "min_win_rate": float(policy.get("min_win_rate", 50.0)),
            "min_net_pnl": float(policy.get("min_net_pnl", 0.0)),
            "max_consecutive_losses": int(policy.get("max_consecutive_losses", 2)),
            "max_loss_abs": float(policy.get("max_loss_abs", 5.0)),
            "max_loss_pct_of_allocation": float(policy.get("max_loss_pct_of_allocation", 0.01)),
            "capital_allocation": capital_allocation,
            "stop_on_unproductive": bool(policy.get("stop_on_unproductive", True)),
        }

    def _calc_metrics(self, trades: List[TradeDB]) -> Dict[str, Any]:
        total = len(trades)
        if total == 0:
            return {
                "trade_count": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "consecutive_losses": 0,
                "last_trade_at": None,
            }

        wins = sum(1 for t in trades if (t.pnl or 0) > 0)
        net_pnl = sum((t.pnl or 0) - (t.fee or 0) for t in trades)

        consecutive_losses = 0
        for trade in trades:
            if (trade.pnl or 0) <= 0:
                consecutive_losses += 1
            else:
                break

        return {
            "trade_count": total,
            "win_rate": round((wins / total) * 100, 2),
            "net_pnl": round(net_pnl, 4),
            "consecutive_losses": consecutive_losses,
            "last_trade_at": trades[0].time.isoformat() if trades and trades[0].time else None,
        }

    def _append_event_file(self, event: Dict[str, Any]):
        os.makedirs("reports", exist_ok=True)
        date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = os.path.join("reports", f"production_guard_events_{date_tag}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _emit_alert(self, db, bot_id: str, level: str, title: str, message: str, reason_code: str, data: Dict[str, Any]):
        key = f"{bot_id}|{level}|{reason_code}|{round(float(data.get('net_pnl', 0.0) or 0.0), 2)}|{int(data.get('consecutive_losses', 0) or 0)}"
        if self._last_emitted_key.get(bot_id) == key:
            return
        self._last_emitted_key[bot_id] = key

        alert = BotAlertDB(
            bot_id=bot_id,
            level=level,
            title=title,
            message=message,
            reason_code=reason_code,
            data=data,
            acknowledged=False,
        )
        db.add(alert)

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "bot_id": bot_id,
            "level": level,
            "title": title,
            "message": message,
            "reason_code": reason_code,
            "data": data,
        }
        self._append_event_file(event)

    async def scan_once(self, trigger: str = "manual"):
        status_rows: List[Dict[str, Any]] = []

        with SessionLocal() as db:
            running_bots = db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all()

            for bot in running_bots:
                policy = self._policy(bot)
                if not policy["enabled"]:
                    continue

                trades = (
                    db.query(TradeDB)
                    .filter(TradeDB.bot_id == bot.id)
                    .order_by(TradeDB.time.desc())
                    .limit(policy["window_trades"])
                    .all()
                )
                metrics = self._calc_metrics(trades)

                decision = "ok"
                reason_code = "healthy"
                reason_msg = "Producción dentro de umbrales"

                if metrics["trade_count"] < policy["min_trades"]:
                    decision = "warmup"
                    reason_code = "insufficient_trades"
                    reason_msg = f"Calentamiento: {metrics['trade_count']}/{policy['min_trades']} trades"
                else:
                    max_loss_abs = abs(float(policy.get("max_loss_abs", 5.0) or 5.0))
                    max_loss_pct = abs(float(policy.get("max_loss_pct_of_allocation", 0.01) or 0.01))
                    capital_allocation = abs(float(policy.get("capital_allocation", 0.0) or 0.0))
                    dynamic_loss_cap = (capital_allocation * max_loss_pct) if capital_allocation > 0 else None
                    effective_loss_cap = max_loss_abs
                    if dynamic_loss_cap is not None:
                        effective_loss_cap = min(max_loss_abs, dynamic_loss_cap)

                    if metrics["net_pnl"] <= -effective_loss_cap:
                        decision = "stop" if policy["stop_on_unproductive"] else "warn"
                        reason_code = "loss_cap_breached"
                        reason_msg = (
                            f"Límite de pérdida excedido: net_pnl {metrics['net_pnl']} <= -{round(effective_loss_cap, 4)}"
                        )
                    elif metrics["consecutive_losses"] >= policy["max_consecutive_losses"]:
                        decision = "stop" if policy["stop_on_unproductive"] else "warn"
                        reason_code = "consecutive_losses"
                        reason_msg = f"Pérdidas consecutivas altas: {metrics['consecutive_losses']}"
                    else:
                        low_win = metrics["win_rate"] < policy["min_win_rate"]
                        low_pnl = metrics["net_pnl"] < policy["min_net_pnl"]

                        if low_win and low_pnl:
                            decision = "stop" if policy["stop_on_unproductive"] else "warn"
                            reason_code = "multi_factor_underperformance"
                            reason_msg = (
                                f"Baja productividad multifactor: win_rate {metrics['win_rate']}% < {policy['min_win_rate']}% "
                                f"y net_pnl {metrics['net_pnl']} < {policy['min_net_pnl']}"
                            )
                        elif low_win:
                            decision = "warn"
                            reason_code = "low_win_rate"
                            reason_msg = f"Win rate bajo: {metrics['win_rate']}% < {policy['min_win_rate']}%"
                        elif low_pnl:
                            decision = "warn"
                            reason_code = "negative_net_pnl"
                            reason_msg = f"Net PnL bajo: {metrics['net_pnl']} < {policy['min_net_pnl']}"

                row = {
                    "bot_id": bot.id,
                    "decision": decision,
                    "reason_code": reason_code,
                    "reason": reason_msg,
                    "policy": policy,
                    "metrics": metrics,
                    "trigger": trigger,
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                }
                status_rows.append(row)

                if decision == "warn":
                    self._emit_alert(
                        db,
                        bot.id,
                        "warning",
                        "Productividad baja",
                        reason_msg,
                        reason_code,
                        {**metrics, "policy": policy, "trigger": trigger},
                    )
                elif decision == "stop":
                    self.bot_manager.stop_bot(bot.id)
                    self._emit_alert(
                        db,
                        bot.id,
                        "critical",
                        "Bot detenido automáticamente",
                        f"Parado por baja productividad: {reason_msg}",
                        reason_code,
                        {**metrics, "policy": policy, "trigger": trigger, "auto_stopped": True},
                    )
                elif decision == "warmup":
                    self._emit_alert(
                        db,
                        bot.id,
                        "info",
                        "Bot en calentamiento",
                        reason_msg,
                        reason_code,
                        {**metrics, "policy": policy, "trigger": trigger},
                    )

            db.commit()

        self._last_status = status_rows
        return {
            "trigger": trigger,
            "count": len(status_rows),
            "items": status_rows,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def latest_status(self):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(self._last_status),
            "items": self._last_status,
        }
