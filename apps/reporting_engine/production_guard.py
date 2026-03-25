import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, BotAlertDB, OrderLogDB, PositionDB
from apps.engine.production_policy import is_live_mainnet_config
from apps.shared.notifications import notify_event


class ProductionGuardService:
    def __init__(self, bot_manager):
        self.bot_manager = bot_manager
        self.interval_sec = int(os.getenv("PRODUCTION_GUARD_INTERVAL_SEC", "60"))
        self.enabled = os.getenv("PRODUCTION_GUARD_ENABLED", "true").lower() == "true"
        self.kill_switch_enabled = os.getenv("PRODUCTION_KILL_SWITCH_ENABLED", "true").lower() == "true"
        self.daily_loss_cap_abs = abs(float(os.getenv("PRODUCTION_KILL_DAILY_LOSS_ABS", "25")))
        self.failed_orders_threshold = max(1, int(os.getenv("PRODUCTION_KILL_FAILED_ORDERS_THRESHOLD", "5")))
        self.failed_orders_window_min = max(1, int(os.getenv("PRODUCTION_KILL_FAILED_ORDERS_WINDOW_MIN", "20")))
        self._task = None
        self._running = False
        self._last_status: List[Dict[str, Any]] = []
        self._last_emitted_key: Dict[str, str] = {}
        self._last_global_guard_key: str = ""

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
            except asyncio.CancelledError:
                pass
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
            "min_profit_factor": float(policy.get("min_profit_factor", 1.02)),
            "max_consecutive_losses": int(policy.get("max_consecutive_losses", 2)),
            "max_loss_abs": float(policy.get("max_loss_abs", 5.0)),
            "max_loss_pct_of_allocation": float(policy.get("max_loss_pct_of_allocation", 0.01)),
            "capital_allocation": capital_allocation,
            "stop_on_unproductive": bool(policy.get("stop_on_unproductive", True)),
        }

    def _is_live_mainnet(self, bot: BotDB) -> bool:
        return is_live_mainnet_config(dict(bot.config or {}))

    def _calc_metrics(self, trades: List[TradeDB]) -> Dict[str, Any]:
        total = len(trades)
        if total == 0:
            return {
                "trade_count": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "profit_factor": 0.0,
                "consecutive_losses": 0,
                "last_trade_at": None,
            }

        # Métricas neto-aware: el objetivo es net_pnl positivo (p&l - comisiones).
        net_values = [(float(t.pnl or 0.0) - float(t.fee or 0.0)) for t in trades]
        wins = sum(1 for n in net_values if n > 0)
        net_pnl = sum(net_values)
        gross_profit = sum(max(n, 0.0) for n in net_values)
        gross_loss = sum(abs(min(n, 0.0)) for n in net_values)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        consecutive_losses = 0
        for n in net_values:
            if n <= 0:
                consecutive_losses += 1
            else:
                break

        return {
            "trade_count": total,
            "win_rate": round((wins / total) * 100, 2),
            "net_pnl": round(net_pnl, 4),
            "profit_factor": round(profit_factor, 4),
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
        notify_event(
            "PRODUCTION_ALERT",
            {
                "bot_id": bot_id,
                "level": level,
                "title": title,
                "reason_code": reason_code,
                "message": message,
                "net_pnl": data.get("net_pnl"),
                "consecutive_losses": data.get("consecutive_losses"),
            },
        )

    def _emit_global_alert(self, db, level: str, title: str, message: str, reason_code: str, data: Dict[str, Any]):
        key = f"GLOBAL|{reason_code}|{round(float(data.get('daily_net_pnl', 0.0) or 0.0), 2)}|{int(data.get('failed_orders_recent', 0) or 0)}"
        if self._last_global_guard_key == key:
            return
        self._last_global_guard_key = key

        alert = BotAlertDB(
            bot_id="SYSTEM",
            level=level,
            title=title,
            message=message,
            reason_code=reason_code,
            data=data,
            acknowledged=False,
        )
        db.add(alert)
        self._append_event_file(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "bot_id": "SYSTEM",
                "level": level,
                "title": title,
                "message": message,
                "reason_code": reason_code,
                "data": data,
            }
        )
        notify_event(
            "GLOBAL_GUARD_ALERT",
            {
                "level": level,
                "title": title,
                "reason_code": reason_code,
                "message": message,
                "daily_net_pnl": data.get("daily_net_pnl"),
                "failed_orders_recent": data.get("failed_orders_recent"),
            },
        )

    def _apply_global_kill_switch(self, db, trigger: str) -> Dict[str, Any]:
        if not self.kill_switch_enabled:
            return {"checked": False, "triggered": False}

        live_bots = [b for b in db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all() if self._is_live_mainnet(b)]
        live_ids = [b.id for b in live_bots]
        if not live_ids:
            return {"checked": True, "triggered": False, "live_bots": 0}

        now = datetime.now(timezone.utc)
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).replace(tzinfo=None)
        window_start = (now - timedelta(minutes=self.failed_orders_window_min)).replace(tzinfo=None)

        day_trades = (
            db.query(TradeDB)
            .filter(TradeDB.bot_id.in_(live_ids), TradeDB.time >= day_start)
            .all()
        )
        daily_net_pnl = round(sum((float(t.pnl or 0.0) - float(t.fee or 0.0)) for t in day_trades), 6)

        failed_recent = (
            db.query(OrderLogDB)
            .filter(
                OrderLogDB.bot_id.in_(live_ids),
                OrderLogDB.created_at >= window_start,
                OrderLogDB.status.in_(["failed", "cancelled"]),
            )
            .count()
        )

        should_stop_loss = daily_net_pnl <= -self.daily_loss_cap_abs
        should_stop_failures = failed_recent >= self.failed_orders_threshold
        triggered = should_stop_loss or should_stop_failures
        if not triggered:
            return {
                "checked": True,
                "triggered": False,
                "live_bots": len(live_ids),
                "daily_net_pnl": daily_net_pnl,
                "failed_orders_recent": int(failed_recent),
            }

        stopped = []
        for bot in live_bots:
            if self.bot_manager.stop_bot(bot.id):
                bot.status = "stopped"
                stopped.append(bot.id)

        reason = "global_daily_loss_cap" if should_stop_loss else "global_failed_orders_spike"
        message = (
            f"Kill switch activado: PnL diario {daily_net_pnl} <= -{self.daily_loss_cap_abs}"
            if should_stop_loss
            else f"Kill switch activado: {failed_recent} órdenes fallidas/canceladas en {self.failed_orders_window_min}m"
        )
        self._emit_global_alert(
            db,
            level="critical",
            title="Kill Switch Global Activado",
            message=message,
            reason_code=reason,
            data={
                "trigger": trigger,
                "live_bots_before": len(live_ids),
                "stopped_bots": stopped,
                "daily_net_pnl": daily_net_pnl,
                "daily_loss_cap_abs": self.daily_loss_cap_abs,
                "failed_orders_recent": int(failed_recent),
                "failed_orders_threshold": self.failed_orders_threshold,
                "failed_orders_window_min": self.failed_orders_window_min,
            },
        )
        return {
            "checked": True,
            "triggered": True,
            "reason": reason,
            "message": message,
            "stopped_bots": stopped,
            "daily_net_pnl": daily_net_pnl,
            "failed_orders_recent": int(failed_recent),
        }

    async def scan_once(self, trigger: str = "manual"):
        status_rows: List[Dict[str, Any]] = []

        with SessionLocal() as db:
            global_guard = self._apply_global_kill_switch(db, trigger=trigger)
            running_bots = db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all()

            for bot in running_bots:
                if not self._is_live_mainnet(bot):
                    continue

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
                        low_pf = float(metrics.get("profit_factor") or 0.0) < float(policy.get("min_profit_factor") or 0.0)

                        if low_win and low_pnl:
                            decision = "stop" if policy["stop_on_unproductive"] else "warn"
                            reason_code = "multi_factor_underperformance"
                            reason_msg = (
                                f"Baja productividad multifactor: win_rate {metrics['win_rate']}% < {policy['min_win_rate']}% "
                                f"y net_pnl {metrics['net_pnl']} < {policy['min_net_pnl']}"
                            )
                        elif low_pf and low_pnl:
                            decision = "stop" if policy["stop_on_unproductive"] else "warn"
                            reason_code = "low_profit_factor"
                            reason_msg = (
                                f"Ratio beneficio bajo: profit_factor {metrics['profit_factor']} < {policy['min_profit_factor']} "
                                f"con net_pnl {metrics['net_pnl']} < {policy['min_net_pnl']}"
                            )
                        elif low_pf:
                            decision = "warn"
                            reason_code = "low_profit_factor"
                            reason_msg = f"Profit factor bajo: {metrics['profit_factor']} < {policy['min_profit_factor']}"
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
                open_positions = (
                    db.query(PositionDB)
                    .filter(PositionDB.bot_id == bot.id, PositionDB.is_open == True)
                    .count()
                )
                row["open_positions"] = int(open_positions)
                if decision == "stop" and open_positions > 0:
                    decision = "warn"
                    reason_code = f"{reason_code}_open_position_protected"
                    reason_msg = (
                        f"{reason_msg}. Stop automático diferido: bot mantiene {open_positions} posición(es) abierta(s)."
                    )
                    row["decision"] = decision
                    row["reason_code"] = reason_code
                    row["reason"] = reason_msg
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
            "global_guard": global_guard,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def latest_status(self):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(self._last_status),
            "items": self._last_status,
        }
