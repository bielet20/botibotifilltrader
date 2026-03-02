from copy import deepcopy
from statistics import mean, pstdev
from typing import Dict, Any, List

from apps.engine.market_data import MarketDataEngine
from apps.shared.bot_presets import get_bot_preset
from apps.shared.models import BotDB, TradeDB


HORIZON_PROFILES = {
    "corto": {
        "strategy_weight": {
            "adaptive_learning": 81,
            "grid_trading": 78,
            "technical_pro": 72,
            "algo_expert": 70,
            "ema_cross": 66,
            "dynamic_reinvest": 58,
        },
        "default_preset": "preset_grid_btc_tight",
        "eth_preset": "preset_grid_eth_stable",
    },
    "medio": {
        "strategy_weight": {
            "technical_pro": 80,
            "adaptive_learning": 74,
            "algo_expert": 76,
            "ema_cross": 72,
            "dynamic_reinvest": 70,
            "grid_trading": 66,
        },
        "default_preset": "preset_technical_pro_balanced",
        "eth_preset": "preset_ema_conservador_eth",
    },
    "largo": {
        "strategy_weight": {
            "ema_cross": 82,
            "dynamic_reinvest": 76,
            "adaptive_learning": 71,
            "technical_pro": 70,
            "algo_expert": 68,
            "grid_trading": 58,
        },
        "default_preset": "preset_ema_swing_defensivo",
        "eth_preset": "preset_ema_conservador_eth",
    },
}


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))


def _horizon_tuned_config(base_config: Dict[str, Any], horizon: str, symbol: str, allocation: float) -> Dict[str, Any]:
    config = deepcopy(base_config or {})
    config["symbol"] = symbol
    config["capital_allocation"] = allocation

    strategy = (config.get("strategy") or "ema_cross").lower()
    risk_cfg = dict(config.get("risk_config") or {})

    if horizon == "corto":
        if strategy == "ema_cross":
            config["fast_ema"] = 7
            config["slow_ema"] = 19
        elif strategy == "grid_trading":
            config["num_grids"] = int(max(8, min(24, int(config.get("num_grids", 10)) + 2)))
        elif strategy == "dynamic_reinvest":
            config["take_profit_pct"] = 0.012
        elif strategy == "adaptive_learning":
            config["adaptive_short_window"] = 10
            config["adaptive_long_window"] = 36
            config["adaptive_base_amount"] = 0.012
        risk_cfg["max_drawdown"] = 0.04

    elif horizon == "medio":
        if strategy == "ema_cross":
            config["fast_ema"] = 12
            config["slow_ema"] = 26
        elif strategy == "grid_trading":
            config["num_grids"] = 10
        elif strategy == "dynamic_reinvest":
            config["take_profit_pct"] = 0.02
        elif strategy == "adaptive_learning":
            config["adaptive_short_window"] = 12
            config["adaptive_long_window"] = 48
            config["adaptive_base_amount"] = 0.01
        risk_cfg["max_drawdown"] = 0.05

    elif horizon == "largo":
        if strategy == "ema_cross":
            config["fast_ema"] = 20
            config["slow_ema"] = 50
        elif strategy == "grid_trading":
            config["num_grids"] = int(max(6, min(12, int(config.get("num_grids", 10)) - 2)))
        elif strategy == "dynamic_reinvest":
            config["take_profit_pct"] = 0.03
        elif strategy == "adaptive_learning":
            config["adaptive_short_window"] = 18
            config["adaptive_long_window"] = 72
            config["adaptive_base_amount"] = 0.008
        risk_cfg["max_drawdown"] = 0.06

    config["risk_config"] = risk_cfg
    config.setdefault("executor", "paper")
    return config


def _get_bot_metrics(db, bot_id: str) -> Dict[str, Any]:
    recent_trades = (
        db.query(TradeDB)
        .filter(TradeDB.bot_id == bot_id)
        .order_by(TradeDB.time.desc())
        .limit(30)
        .all()
    )

    if not recent_trades:
        return {"trade_count": 0, "net_pnl": 0.0, "win_rate": 50.0}

    wins = sum(1 for trade in recent_trades if (trade.pnl or 0) > 0)
    total = len(recent_trades)
    pnl = sum((trade.pnl or 0) - (trade.fee or 0) for trade in recent_trades)
    win_rate = (wins / total) * 100 if total > 0 else 50.0

    consecutive_losses = 0
    for trade in recent_trades:
        if (trade.pnl or 0) <= 0:
            consecutive_losses += 1
        else:
            break

    return {
        "trade_count": total,
        "net_pnl": pnl,
        "win_rate": win_rate,
        "consecutive_losses": consecutive_losses,
    }


def _risk_reduced_config(base_config: Dict[str, Any], symbol: str, allocation: float) -> Dict[str, Any]:
    config = deepcopy(base_config or {})
    current_alloc = float(config.get("capital_allocation") or allocation or 500)
    config["capital_allocation"] = round(max(50.0, current_alloc * 0.7), 2)
    config["symbol"] = symbol

    strategy = (config.get("strategy") or "ema_cross").lower()
    risk_cfg = dict(config.get("risk_config") or {})
    current_dd = float(risk_cfg.get("max_drawdown", 0.05) or 0.05)
    risk_cfg["max_drawdown"] = round(max(0.02, min(current_dd, 0.04)), 4)

    if strategy == "grid_trading":
        current_grids = int(config.get("num_grids", 10) or 10)
        config["num_grids"] = int(max(8, min(20, current_grids + 2)))
    elif strategy == "dynamic_reinvest":
        current_tp = float(config.get("take_profit_pct", 0.02) or 0.02)
        config["take_profit_pct"] = round(max(0.01, min(current_tp, 0.018)), 4)
    elif strategy == "adaptive_learning":
        current_base = float(config.get("adaptive_base_amount", 0.01) or 0.01)
        config["adaptive_base_amount"] = round(max(0.004, min(current_base * 0.85, 0.012)), 4)
        config["adaptive_short_window"] = int(max(10, int(config.get("adaptive_short_window", 12) or 12)))
        config["adaptive_long_window"] = int(max(36, int(config.get("adaptive_long_window", 48) or 48)))
    elif strategy == "ema_cross":
        fast = int(config.get("fast_ema", 9) or 9)
        slow = int(config.get("slow_ema", 21) or 21)
        config["fast_ema"] = max(9, fast)
        config["slow_ema"] = max(26, slow)

    config["risk_config"] = risk_cfg
    config.setdefault("executor", "paper")
    return config


def _pick_preset_for_horizon(horizon: str, symbol: str):
    profile = HORIZON_PROFILES[horizon]
    symbol_upper = (symbol or "").upper()
    if symbol_upper.startswith("ETH/"):
        preset_id = profile.get("eth_preset")
    else:
        preset_id = profile.get("default_preset")
    return get_bot_preset(preset_id), preset_id


def _detect_market_regime(ohlcv: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not ohlcv or len(ohlcv) < 12:
        return {
            "regime": "mixto",
            "volatility_pct": 0.0,
            "trend_pct": 0.0,
            "preferred_horizon": "medio",
            "source": "fallback",
        }

    closes = [float(c.get("close", 0.0) or 0.0) for c in ohlcv if float(c.get("close", 0.0) or 0.0) > 0]
    if len(closes) < 12:
        return {
            "regime": "mixto",
            "volatility_pct": 0.0,
            "trend_pct": 0.0,
            "preferred_horizon": "medio",
            "source": "fallback",
        }

    returns_abs = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev > 0:
            returns_abs.append(abs((cur - prev) / prev) * 100)

    volatility_pct = float(pstdev(returns_abs)) if len(returns_abs) > 1 else float(mean(returns_abs) if returns_abs else 0.0)
    trend_pct = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] > 0 else 0.0
    abs_trend = abs(trend_pct)

    if volatility_pct < 0.6 and abs_trend >= 1.5:
        regime = "tendencia_estable"
        preferred_horizon = "largo"
    elif volatility_pct < 0.8 and abs_trend < 1.5:
        regime = "lateral_estable"
        preferred_horizon = "corto"
    elif volatility_pct >= 1.2 and abs_trend < 2.0:
        regime = "lateral_volatil"
        preferred_horizon = "corto"
    elif volatility_pct >= 1.2 and abs_trend >= 2.0:
        regime = "tendencia_volatil"
        preferred_horizon = "medio"
    else:
        regime = "mixto"
        preferred_horizon = "medio"

    return {
        "regime": regime,
        "volatility_pct": round(volatility_pct, 3),
        "trend_pct": round(trend_pct, 3),
        "preferred_horizon": preferred_horizon,
        "source": "ohlcv_1h_72",
    }


def _market_bonus_for_horizon(horizon: str, market_context: Dict[str, Any]) -> float:
    regime = (market_context or {}).get("regime", "mixto")
    volatility = float((market_context or {}).get("volatility_pct", 0.0) or 0.0)

    if horizon == "corto":
        bonus = 0.0
        if regime in {"lateral_estable", "lateral_volatil"}:
            bonus += 8
        if volatility >= 1.0:
            bonus += 3
        return bonus

    if horizon == "medio":
        bonus = 0.0
        if regime in {"mixto", "tendencia_volatil"}:
            bonus += 6
        if 0.6 <= volatility <= 1.4:
            bonus += 2
        return bonus

    if horizon == "largo":
        bonus = 0.0
        if regime == "tendencia_estable":
            bonus += 9
        if volatility < 0.8:
            bonus += 3
        if regime == "lateral_volatil":
            bonus -= 4
        return bonus

    return 0.0


def _score_bot_for_horizon(bot: BotDB, metrics: Dict[str, Any], horizon: str, market_context: Dict[str, Any]) -> float:
    profile = HORIZON_PROFILES[horizon]
    strategy = (bot.strategy or "ema_cross").lower()
    base = profile["strategy_weight"].get(strategy, 55)

    perf = 0.0
    perf += _clamp((metrics.get("win_rate", 50.0) - 50.0) * 0.35, -15, 15)
    perf += _clamp(metrics.get("net_pnl", 0.0) * 0.08, -10, 10)
    perf += 4 if (bot.status or "").lower() == "running" else 0
    perf += _market_bonus_for_horizon(horizon, market_context)

    return base + perf


async def build_bot_advice(db, symbol: str, allocation: float) -> Dict[str, Any]:
    symbol = (symbol or "BTC/USDT").strip() or "BTC/USDT"
    allocation = float(allocation or 500)
    allocation = max(50.0, allocation)

    market_context = {
        "regime": "mixto",
        "volatility_pct": 0.0,
        "trend_pct": 0.0,
        "preferred_horizon": "medio",
        "source": "fallback",
    }

    mde = MarketDataEngine()
    try:
        market_ohlcv = await mde.fetch_ohlcv(symbol, timeframe="1h", limit=72)
        market_context = _detect_market_regime(market_ohlcv)
    except Exception:
        market_context = {
            "regime": "mixto",
            "volatility_pct": 0.0,
            "trend_pct": 0.0,
            "preferred_horizon": "medio",
            "source": "fallback-error",
        }
    finally:
        try:
            await mde.close()
        except Exception:
            pass

    bots: List[BotDB] = db.query(BotDB).filter(BotDB.is_archived == False).all()

    horizons = ["corto", "medio", "largo"]
    recommendations: List[Dict[str, Any]] = []

    for horizon in horizons:
        best_bot = None
        best_score = -10_000.0

        for bot in bots:
            metrics = _get_bot_metrics(db, bot.id)
            score = _score_bot_for_horizon(bot, metrics, horizon, market_context)
            if score > best_score:
                best_score = score
                best_bot = (bot, metrics)

        preset, preset_id = _pick_preset_for_horizon(horizon, symbol)
        new_bot_config = _horizon_tuned_config((preset or {}).get("config", {}), horizon, symbol, allocation)

        if best_bot:
            selected_bot, metrics = best_bot
            edited_config = _horizon_tuned_config(selected_bot.config or {}, horizon, symbol, allocation)
            risk_reduce_config = _risk_reduced_config(selected_bot.config or {}, symbol, allocation)

            underperforming = (
                metrics.get("trade_count", 0) >= 8 and (
                    metrics.get("consecutive_losses", 0) >= 3
                    or (
                        metrics.get("win_rate", 50.0) < 42.0
                        and metrics.get("net_pnl", 0.0) < -2.0
                    )
                )
            )

            if underperforming:
                recommended_action = "reduce_risk"
            else:
                recommended_action = "tune_existing" if best_score >= 58 else "create_new"

            confidence = int(_clamp(best_score, 35, 95))
            if recommended_action == "reduce_risk":
                reason = (
                    f"Prioridad defensiva: {selected_bot.id} con señales de bajo rendimiento "
                    f"(win_rate={metrics.get('win_rate', 50):.1f}%, net_pnl={metrics.get('net_pnl', 0):.2f}, "
                    f"losses_consecutivas={metrics.get('consecutive_losses', 0)}). "
                    f"Se recomienda reducir riesgo antes de escalar o detener."
                )
            else:
                reason = (
                    f"Mejor candidato actual: {selected_bot.id} | estrategia={selected_bot.strategy} | "
                    f"win_rate={metrics.get('win_rate', 50):.1f}% | net_pnl={metrics.get('net_pnl', 0):.2f} | "
                    f"régimen={market_context.get('regime')}"
                )

            recommendations.append(
                {
                    "horizon": horizon,
                    "recommended_action": recommended_action,
                    "confidence": confidence,
                    "recommended_bot_id": selected_bot.id,
                    "reason": reason,
                    "edited_config": risk_reduce_config if recommended_action == "reduce_risk" else edited_config,
                    "new_bot_config": new_bot_config,
                    "new_bot_preset_id": preset_id,
                    "new_bot_preset_name": (preset or {}).get("name", "Preset sugerido"),
                }
            )
        else:
            recommendations.append(
                {
                    "horizon": horizon,
                    "recommended_action": "create_new",
                    "confidence": 70,
                    "recommended_bot_id": None,
                    "reason": "No hay bots en Mis Bots; conviene crear uno nuevo para este horizonte.",
                    "edited_config": None,
                    "new_bot_config": new_bot_config,
                    "new_bot_preset_id": preset_id,
                    "new_bot_preset_name": (preset or {}).get("name", "Preset sugerido"),
                }
            )

    return {
        "symbol": symbol,
        "allocation": allocation,
        "generated_at": "advisor-runtime",
        "market_context": market_context,
        "recommendations": recommendations,
    }
