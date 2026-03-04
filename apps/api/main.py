from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import uuid
import json
import csv
import io
import urllib.request
from sqlalchemy import text
from sqlalchemy.orm import Session
import ccxt.async_support as ccxt

from apps.engine.backtester import BacktestEngine
from apps.engine.ema_cross import EMACrossStrategy
from apps.engine.technical_pro import TechnicalProStrategy
from apps.engine.algo_expert import AlgoExpertStrategy
from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
from apps.engine.risk import RiskEngine
from apps.engine.bot_advisor import build_bot_advice
from apps.bot_manager.manager import BotManager
from apps.ai_engine.engine import AIEngine
from apps.ai_engine.adaptive_orchestrator import AdaptiveOrchestratorService
from apps.reporting_engine.reporting import ReportingEngine, calculate_metrics
from apps.reporting_engine.production_guard import ProductionGuardService
from apps.reporting_engine.paper_monitor_runtime import PaperMonitorRuntimeService
from apps.shared.database import init_db, get_db
from apps.shared.models import BotDB, TradeDB, BotStatus, OrderLogDB, PositionDB, BotAlertDB, BotLearningStateDB
from apps.shared.bot_presets import list_bot_presets, get_bot_preset
from apps.engine.paper_portfolio import PaperPortfolioDB
from apps.engine.position_sync import PositionSyncService
from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.engine.market_data import MarketDataEngine

app = FastAPI(title="Trading Platform API Gateway")

# Initialize singletons BEFORE startup event so they are available
from datetime import datetime, timezone
import time as _time

_startup_time = _time.time()

# Singleton-like instances
risk_engine = RiskEngine()
bot_manager = BotManager()
ai_engine = AIEngine()
reporting_engine = ReportingEngine()
production_guard = ProductionGuardService(bot_manager)
adaptive_orchestrator = AdaptiveOrchestratorService(bot_manager, production_guard)
paper_monitor_runtime = PaperMonitorRuntimeService()


def _project_root_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _env_file_path() -> str:
    return os.path.join(_project_root_path(), ".env")


def _sanitize_asset_key(value: str) -> str:
    key = (value or "").strip().upper()
    safe = []
    for ch in key:
        safe.append(ch if ch.isalnum() else "_")
    out = "".join(safe).strip("_")
    return out or "ASSET"


def _import_data_dir() -> str:
    path = os.path.join(_project_root_path(), "reports", "imported_market_data")
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_candles(candles: list) -> list:
    normalized = []
    for item in candles or []:
        try:
            time_v = int(float(item.get("time")))
            normalized.append(
                {
                    "time": time_v,
                    "open": float(item.get("open")),
                    "high": float(item.get("high")),
                    "low": float(item.get("low")),
                    "close": float(item.get("close")),
                    "volume": float(item.get("volume", 0.0) or 0.0),
                }
            )
        except Exception:
            continue
    normalized.sort(key=lambda c: c["time"])
    return normalized


def _parse_csv_candles(data_str: str) -> list:
    reader = csv.DictReader(io.StringIO(data_str or ""))
    rows = []
    for row in reader:
        rows.append(
            {
                "time": row.get("time"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume", 0.0),
            }
        )
    return _normalize_candles(rows)


def _candles_to_csv(candles: list) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["time", "open", "high", "low", "close", "volume"])
    writer.writeheader()
    for row in candles:
        writer.writerow(row)
    return output.getvalue()


def _import_file_path(symbol: str, timeframe: str) -> str:
    file_name = f"{_sanitize_asset_key(symbol)}__{_sanitize_asset_key(timeframe)}.json"
    return os.path.join(_import_data_dir(), file_name)


def _save_imported_candles(symbol: str, timeframe: str, candles: list):
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "candles": candles,
    }
    with open(_import_file_path(symbol, timeframe), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _load_imported_candles(symbol: str, timeframe: str) -> list:
    path = _import_file_path(symbol, timeframe)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return _normalize_candles(payload.get("candles") or [])


def _read_env_values() -> dict:
    path = _env_file_path()
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _write_env_values(updates: dict):
    path = _env_file_path()
    existing = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read().splitlines()

    found = set()
    out = []
    for raw in existing:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in raw:
            key, _ = raw.split("=", 1)
            key = key.strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                found.add(key)
                continue
        out.append(raw)

    for key, value in updates.items():
        if key not in found:
            out.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")


def _mask_wallet(wallet: str) -> str:
    if not wallet or len(wallet) < 10:
        return ""
    return f"{wallet[:8]}...{wallet[-6:]}"


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _compute_consecutive_losses(scored_pnls: list[float]) -> int:
    streak = 0
    for pnl in reversed(scored_pnls or []):
        if pnl < 0:
            streak += 1
        else:
            break
    return streak


def _compute_max_drawdown_abs(scored_pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in scored_pnls or []:
        equity += float(pnl)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _adaptive_parameter_recommendation(strategy: str, config: dict, metrics: dict) -> dict:
    strategy = (strategy or "").lower()
    cfg = dict(config or {})
    scored_trades = int(metrics.get("scored_trades") or 0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    net_pnl = float(metrics.get("net_pnl") or 0.0)
    consecutive_losses = int(metrics.get("consecutive_losses") or 0)
    max_drawdown_abs = float(metrics.get("max_drawdown_abs") or 0.0)

    suggested_params = {}
    rationale = []
    level = "maintain"

    if scored_trades < 5:
        level = "insufficient_data"
        rationale.append("Muestra corta: menos de 5 trades con PnL real.")
        if "pair" in strategy:
            suggested_params["pair_entry_z"] = round(max(1.0, float(cfg.get("pair_entry_z", 1.4)) - 0.1), 3)
            suggested_params["pair_min_correlation"] = round(max(0.15, float(cfg.get("pair_min_correlation", 0.35)) - 0.05), 3)
            rationale.append("Reducir levemente filtros del pair para acelerar validación estadística.")
        return {
            "level": level,
            "summary": "Datos insuficientes para un ajuste fuerte.",
            "suggested_params": suggested_params,
            "rationale": rationale,
        }

    if win_rate < 45 or net_pnl < 0 or consecutive_losses >= 4:
        level = "defensive"
        rationale.append("Rendimiento débil o racha de pérdidas detectada.")

        current_alloc = float(cfg.get("allocation", cfg.get("capital_allocation", 100.0)) or 100.0)
        suggested_alloc = max(20.0, current_alloc * 0.85)
        suggested_params["allocation"] = round(suggested_alloc, 4)
        suggested_params["capital_allocation"] = round(suggested_alloc, 4)

        current_risk = dict(cfg.get("risk_config") or {})
        current_dd = float(current_risk.get("max_drawdown", 0.05) or 0.05)
        current_risk["max_drawdown"] = round(max(0.015, current_dd - 0.005), 4)
        suggested_params["risk_config"] = current_risk

        if "ema_cross" in strategy:
            fast = int(cfg.get("fast_ema", 9) or 9)
            slow = int(cfg.get("slow_ema", 21) or 21)
            suggested_params["fast_ema"] = min(30, fast + 1)
            suggested_params["slow_ema"] = min(80, max(slow + 3, fast + 5))
            rationale.append("EMA más conservadora para reducir sobre-operación.")
        elif "grid_trading" in strategy:
            grids = int(cfg.get("num_grids", 10) or 10)
            suggested_params["num_grids"] = min(30, grids + 2)
            rationale.append("Mayor densidad de rejilla para mejorar promedio de entradas.")
        elif "adaptive_learning" in strategy:
            min_flip = float(cfg.get("adaptive_min_flip_move_pct", 0.002) or 0.002)
            min_reentry = float(cfg.get("adaptive_min_reentry_move_pct", 0.0012) or 0.0012)
            suggested_params["adaptive_min_flip_move_pct"] = round(min_flip * 1.2, 6)
            suggested_params["adaptive_min_reentry_move_pct"] = round(min_reentry * 1.15, 6)
            suggested_params["adaptive_base_amount"] = round(max(0.001, float(cfg.get("adaptive_base_amount", 0.01) or 0.01) * 0.9), 6)
            rationale.append("Subir umbral de flip y bajar tamaño base para controlar drawdown.")
        elif "pair" in strategy:
            suggested_params["pair_entry_z"] = round(min(2.2, float(cfg.get("pair_entry_z", 1.4) or 1.4) + 0.1), 3)
            suggested_params["pair_exit_z"] = round(min(0.8, float(cfg.get("pair_exit_z", 0.25) or 0.25) + 0.05), 3)
            suggested_params["pair_min_correlation"] = round(min(0.85, float(cfg.get("pair_min_correlation", 0.35) or 0.35) + 0.05), 3)
            rationale.append("Endurecer filtro de entrada pair para evitar setups débiles.")
    elif win_rate >= 58 and net_pnl > 0 and consecutive_losses <= 2:
        level = "offensive"
        rationale.append("Rendimiento sólido y consistente en ventana reciente.")

        current_alloc = float(cfg.get("allocation", cfg.get("capital_allocation", 100.0)) or 100.0)
        suggested_alloc = min(current_alloc * 1.12, current_alloc + max(20.0, abs(net_pnl) * 0.35))
        suggested_params["allocation"] = round(suggested_alloc, 4)
        suggested_params["capital_allocation"] = round(suggested_alloc, 4)

        if "adaptive_learning" in strategy:
            suggested_params["reinvest_ratio"] = round(min(0.5, float(cfg.get("reinvest_ratio", 0.35) or 0.35) + 0.05), 4)
        if "pair" in strategy:
            suggested_params["pair_entry_z"] = round(max(1.0, float(cfg.get("pair_entry_z", 1.4) or 1.4) - 0.05), 3)
            suggested_params["pair_take_profit_pct"] = round(min(0.02, float(cfg.get("pair_take_profit_pct", 0.01) or 0.01) + 0.001), 4)
    else:
        rationale.append("Desempeño mixto: mantener configuración con ajustes menores.")

    summary = (
        f"win_rate={win_rate:.2f}% · net_pnl={net_pnl:.4f} · "
        f"loss_streak={consecutive_losses} · max_dd={max_drawdown_abs:.4f}"
    )
    return {
        "level": level,
        "summary": summary,
        "suggested_params": suggested_params,
        "rationale": rationale,
    }


def _bot_config_from_prompt(prompt: str, symbol: str, allocation: float) -> dict:
    prompt_text = (prompt or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="prompt is required")

    p = prompt_text.lower()
    normalized_symbol = (symbol or "BTC/USDT").strip() or "BTC/USDT"
    safe_allocation = max(20.0, float(allocation or 500.0))

    strategy = "ema_cross"
    if any(k in p for k in ["pair", "paired", "cointegration", "zscore", "z-score", "correl"]):
        strategy = "paired_balanced"
    elif any(k in p for k in ["grid", "rejilla", "rango", "range"]):
        strategy = "grid_trading"
    elif any(k in p for k in ["adaptive", "aprendiz", "learning", "reinvert"]):
        strategy = "adaptive_learning"
    elif any(k in p for k in ["rsi", "macd", "fib", "fibonacci", "technical"]):
        strategy = "technical_pro"

    risk_level = "medium"
    if any(k in p for k in ["conserv", "bajo riesgo", "defens", "estable", "segur"]):
        risk_level = "low"
    elif any(k in p for k in ["agres", "alto riesgo", "ofens", "volatil", "apalanc"]):
        risk_level = "high"

    horizon = "medio"
    if any(k in p for k in ["scalp", "intradia", "intradía", "corto", "rápido", "rapido"]):
        horizon = "corto"
    elif any(k in p for k in ["largo", "swing", "seman", "mensual", "tendencia larga"]):
        horizon = "largo"

    cfg = {
        "strategy": strategy,
        "symbol": normalized_symbol,
        "executor": "paper",
        "capital_allocation": round(safe_allocation, 4),
        "allocation": round(safe_allocation, 4),
        "risk_config": {"max_drawdown": 0.05},
    }

    if strategy == "ema_cross":
        if horizon == "corto":
            cfg.update({"fast_ema": 7, "slow_ema": 18})
        elif horizon == "largo":
            cfg.update({"fast_ema": 20, "slow_ema": 55})
        else:
            cfg.update({"fast_ema": 9, "slow_ema": 21})
    elif strategy == "grid_trading":
        cfg.update({"upper_limit": 70000, "lower_limit": 60000, "num_grids": 10})
        if risk_level == "low":
            cfg["num_grids"] = 14
        elif risk_level == "high":
            cfg["num_grids"] = 8
    elif strategy == "paired_balanced":
        cfg.update(
            {
                "allow_short": True,
                "pair_symbol_a": normalized_symbol,
                "pair_symbol_b": "ETH/USDT",
                "pair_entry_z": 1.4,
                "pair_exit_z": 0.25,
                "pair_stop_loss_pct": 0.015,
                "pair_take_profit_pct": 0.01,
                "pair_profit_lock_pct": 0.004,
                "pair_min_correlation": 0.35,
            }
        )
        if risk_level == "low":
            cfg["pair_entry_z"] = 1.6
            cfg["pair_min_correlation"] = 0.45
        elif risk_level == "high":
            cfg["pair_entry_z"] = 1.2
            cfg["pair_min_correlation"] = 0.25

    if risk_level == "low":
        cfg["risk_config"] = {"max_drawdown": 0.03}
    elif risk_level == "high":
        cfg["risk_config"] = {"max_drawdown": 0.08}

    return {
        "config": cfg,
        "meta": {
            "detected_strategy": strategy,
            "risk_level": risk_level,
            "horizon": horizon,
            "source": "prompt",
        },
    }


def _build_monitoring_test_results(db: Session, lookback_hours: int, min_scored_trades: int) -> dict:
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    bots = db.query(BotDB).filter(BotDB.is_archived == False).all()
    trades = db.query(TradeDB).filter(TradeDB.time >= since).order_by(TradeDB.time.asc()).all()
    open_critical_alerts = (
        db.query(BotAlertDB)
        .filter(BotAlertDB.acknowledged == False, BotAlertDB.level == "critical")
        .all()
    )

    critical_map = {}
    for alert in open_critical_alerts:
        critical_map.setdefault(alert.bot_id, 0)
        critical_map[alert.bot_id] += 1

    grouped = {}
    for trade in trades:
        grouped.setdefault(trade.bot_id, []).append(trade)

    results = []
    for bot in bots:
        bot_trades = grouped.get(bot.id, [])
        scored = [float(t.pnl or 0.0) for t in bot_trades if float(t.pnl or 0.0) != 0.0]
        wins = sum(1 for pnl in scored if pnl > 0)
        losses = sum(1 for pnl in scored if pnl < 0)
        total_pnl = sum(float(t.pnl or 0.0) for t in bot_trades)
        total_fees = sum(float(t.fee or 0.0) for t in bot_trades)
        net_pnl = total_pnl - total_fees
        win_rate = (wins / len(scored) * 100) if scored else 0.0
        consecutive_losses = _compute_consecutive_losses(scored)
        max_drawdown_abs = _compute_max_drawdown_abs(scored)
        gross_profit = sum(pnl for pnl in scored if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in scored if pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        last_trade_at = bot_trades[-1].time if bot_trades else None

        metrics = {
            "total_trades": len(bot_trades),
            "scored_trades": len(scored),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 6),
            "total_fees": round(total_fees, 6),
            "net_pnl": round(net_pnl, 6),
            "avg_pnl_scored": round((sum(scored) / len(scored)) if scored else 0.0, 6),
            "consecutive_losses": consecutive_losses,
            "max_drawdown_abs": round(max_drawdown_abs, 6),
            "profit_factor": round(profit_factor, 4),
        }

        recommendation = _adaptive_parameter_recommendation(
            strategy=str(bot.strategy or ""),
            config=dict(bot.config or {}),
            metrics=metrics,
        )

        critical_open_count = int(critical_map.get(bot.id, 0) or 0)
        candidate_core = (
            metrics["scored_trades"] >= min_scored_trades
            and metrics["win_rate"] >= 58
            and metrics["net_pnl"] > 0
            and float(metrics.get("profit_factor") or 0.0) >= 1.05
            and metrics["consecutive_losses"] <= 2
            and critical_open_count == 0
        )
        runtime_ready = str(bot.status or "").lower() == BotStatus.RUNNING

        results.append(
            {
                "bot_id": bot.id,
                "strategy": bot.strategy,
                "status": bot.status,
                "last_trade_at": last_trade_at,
                "critical_open_alerts": critical_open_count,
                "candidate_for_production": candidate_core,
                "runtime_ready": runtime_ready,
                "metrics": metrics,
                "recommendation": recommendation,
            }
        )

    results.sort(
        key=lambda item: (
            bool(item.get("candidate_for_production")),
            float(item.get("metrics", {}).get("net_pnl", 0.0)),
            float(item.get("metrics", {}).get("win_rate", 0.0)),
        ),
        reverse=True,
    )

    top_candidates = [item for item in results if item.get("candidate_for_production")][:5]
    profitable_count = sum(1 for item in results if float(item.get("metrics", {}).get("net_pnl", 0.0)) > 0)

    return {
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "bots_analyzed": len(results),
            "profitable_bots": profitable_count,
            "production_candidates": len(top_candidates),
            "critical_alerts_open": len(open_critical_alerts),
        },
        "top_candidates": top_candidates,
        "results": results,
    }


def _public_account_value(wallet: str, use_testnet: bool) -> float:
    return float(_public_account_snapshot(wallet, use_testnet).get("account_value") or 0.0)


def _public_account_snapshot(wallet: str, use_testnet: bool) -> dict:
    if not wallet:
        return {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }

    url = "https://api.hyperliquid-testnet.xyz/info" if use_testnet else "https://api.hyperliquid.xyz/info"
    payload = json.dumps({"type": "clearinghouseState", "user": wallet}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    margin = data.get("marginSummary") or {}
    account_value = float(margin.get("accountValue") or 0.0)
    withdrawable = float(data.get("withdrawable") or 0.0)
    exposure_notional = abs(float(margin.get("totalNtlPos") or 0.0))
    margin_used = max(account_value - withdrawable, 0.0)

    return {
        "account_value": account_value,
        "withdrawable": withdrawable,
        "margin_used": margin_used,
        "exposure_notional": exposure_notional,
    }


def _margin_usage_pct(snapshot: dict) -> float:
    try:
        account_value = float(snapshot.get("account_value") or 0.0)
        margin_used = float(snapshot.get("margin_used") or 0.0)
        if account_value <= 0:
            return 0.0
        return round((margin_used / account_value) * 100, 4)
    except Exception:
        return 0.0


async def _check_private_auth(wallet: str, signing_key: str, use_testnet: bool) -> tuple[bool, str]:
    exchange = ccxt.hyperliquid({"privateKey": signing_key, "walletAddress": wallet})
    if use_testnet:
        exchange.set_sandbox_mode(True)
    try:
        await exchange.fetch_balance()
        return True, "ok"
    except Exception as e:
        return False, str(e)
    finally:
        await exchange.close()


async def _sync_positions_with_best_executor() -> dict:
    env = _read_env_values()
    wallet = env.get("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = env.get("HYPERLIQUID_SIGNING_KEY", "")
    use_testnet = str(env.get("HYPERLIQUID_USE_TESTNET", "True")).strip().lower() == "true"

    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)

    executor_name = "paper"
    if wallet_ok and key_ok:
        os.environ["HYPERLIQUID_WALLET_ADDRESS"] = wallet
        os.environ["HYPERLIQUID_SIGNING_KEY"] = signing_key
        os.environ["HYPERLIQUID_USE_TESTNET"] = "True" if use_testnet else "False"
        executor = HyperliquidExecutor(use_testnet=use_testnet)
        executor_name = "hyperliquid_testnet" if use_testnet else "hyperliquid_mainnet"
    else:
        from apps.engine.paper_executor import PaperTradingExecutor

        executor = PaperTradingExecutor()

    sync_service = PositionSyncService(executor)
    results = await sync_service.sync_positions()
    results["executor"] = executor_name
    return results


def _append_production_activation_event(event: dict) -> None:
    try:
        reports_dir = os.path.join(_project_root_path(), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        file_path = os.path.join(reports_dir, f"production_activation_events_{day}.jsonl")
        with open(file_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        pass


def _audit_production_activation(
    db: Session,
    *,
    bot_id: str,
    trigger: str,
    activated: bool,
    reason: str,
    details: dict,
) -> None:
    timestamp = datetime.now(timezone.utc)
    title = "Auto activación a producción" if trigger.startswith("auto") else "Activación a producción"
    level = "info" if activated else "warning"
    message = (
        f"{title}: bot {bot_id} ACTIVADO en real market"
        if activated
        else f"{title}: bot {bot_id} BLOQUEADO ({reason})"
    )
    reason_code = "auto_prod_activated" if activated else "auto_prod_blocked"

    alert = BotAlertDB(
        bot_id=bot_id,
        level=level,
        title=title,
        message=message,
        reason_code=reason_code,
        data={"trigger": trigger, "reason": reason, "details": details},
        acknowledged=False,
    )
    db.add(alert)

    _append_production_activation_event(
        {
            "time": timestamp.isoformat(),
            "bot_id": bot_id,
            "trigger": trigger,
            "activated": activated,
            "reason": reason,
            "details": details,
        }
    )


async def _activate_bot_for_production_internal(
    db: Session,
    *,
    bot_id: str,
    lookback_hours: int,
    min_scored_trades: int,
    trigger: str,
) -> dict:
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        result = {"activated": False, "bot_id": bot_id, "reason": "bot_not_found"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_not_found", details={})
        db.commit()
        return result
    if bot_entry.is_archived:
        result = {"activated": False, "bot_id": bot_id, "reason": "bot_archived"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_archived", details={})
        db.commit()
        return result

    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    selected = next((item for item in monitoring.get("results", []) if item.get("bot_id") == bot_id), None)
    if not selected:
        result = {"activated": False, "bot_id": bot_id, "reason": "no_monitoring_data"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="no_monitoring_data", details={})
        db.commit()
        return result

    if not selected.get("candidate_for_production"):
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "bot_not_ready_for_production",
            "metrics": selected.get("metrics"),
            "critical_open_alerts": selected.get("critical_open_alerts"),
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="bot_not_ready_for_production",
            details={
                "metrics": selected.get("metrics"),
                "critical_open_alerts": selected.get("critical_open_alerts"),
            },
        )
        db.commit()
        return result

    cfg = dict(bot_entry.config or {})
    executor = str(cfg.get("executor") or "paper").lower()
    if executor != "hyperliquid":
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "executor_not_hyperliquid",
            "message": "Bot must use hyperliquid executor for real production activation",
            "suggested_patch": {"executor": "hyperliquid", "hyperliquid_testnet": False},
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="executor_not_hyperliquid", details={"executor": executor})
        db.commit()
        return result

    if _as_bool(cfg.get("hyperliquid_testnet"), default=False):
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "bot_configured_for_testnet",
            "message": "Set hyperliquid_testnet=false to allow real market production activation",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_configured_for_testnet", details={})
        db.commit()
        return result

    env = _read_env_values()
    wallet = env.get("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = env.get("HYPERLIQUID_SIGNING_KEY", "")
    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)
    if not wallet_ok or not key_ok:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "invalid_hyperliquid_credentials",
            "message": "Hyperliquid credentials are not valid in settings",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="invalid_hyperliquid_credentials", details={})
        db.commit()
        return result

    mainnet_auth_ok, mainnet_auth_error = await _check_private_auth(wallet, signing_key, False)
    if not mainnet_auth_ok:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_auth_failed",
            "message": f"Mainnet auth failed: {mainnet_auth_error}",
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="mainnet_auth_failed",
            details={"error": mainnet_auth_error},
        )
        db.commit()
        return result

    try:
        mainnet_account_value = _public_account_value(wallet, False)
    except Exception as e:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_account_check_failed",
            "message": str(e),
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="mainnet_account_check_failed", details={"error": str(e)})
        db.commit()
        return result

    if mainnet_account_value <= 0:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_account_empty",
            "message": "Mainnet account value is 0. Fund account before production activation",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="mainnet_account_empty", details={"mainnet_account_value": mainnet_account_value})
        db.commit()
        return result

    if bot_id in bot_manager.active_bots:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "already_running",
            "mainnet_account_value": mainnet_account_value,
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="already_running",
            details={"mainnet_account_value": mainnet_account_value},
        )
        db.commit()
        return result

    started = bot_manager.start_bot(bot_id, cfg)
    if not started:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "start_failed",
            "message": "Bot failed to start in production mode",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="start_failed", details={})
        db.commit()
        return result

    bot_entry.status = BotStatus.RUNNING
    result = {
        "activated": True,
        "bot_id": bot_id,
        "mode": "production",
        "mainnet_account_value": round(mainnet_account_value, 4),
        "monitoring_snapshot": {
            "win_rate": selected.get("metrics", {}).get("win_rate"),
            "net_pnl": selected.get("metrics", {}).get("net_pnl"),
            "scored_trades": selected.get("metrics", {}).get("scored_trades"),
        },
    }
    _audit_production_activation(
        db,
        bot_id=bot_id,
        trigger=trigger,
        activated=True,
        reason="activated",
        details={
            "mainnet_account_value": result.get("mainnet_account_value"),
            "monitoring_snapshot": result.get("monitoring_snapshot"),
        },
    )
    db.commit()
    return result

@app.on_event("startup")
async def startup_event():
    init_db()
    await bot_manager.resume_bots()
    await production_guard.start()
    if adaptive_orchestrator.enabled:
        await adaptive_orchestrator.start()
    if paper_monitor_runtime.enabled:
        await paper_monitor_runtime.start(trigger="startup")


@app.on_event("shutdown")
async def shutdown_event():
    await paper_monitor_runtime.stop(trigger="shutdown")
    await adaptive_orchestrator.stop()
    await production_guard.stop()

@app.get("/api/market/price/{symbol:path}")
async def get_market_price(symbol: str):
    """Obtiene el precio real de mercado para un símbolo dado."""
    try:
        # Re-initialize engine to ensure fresh connection if closed
        engine = MarketDataEngine()
        ticker = await engine.fetch_ticker(symbol)
        if not ticker:
            raise HTTPException(status_code=404, detail=f"Ticker not found for {symbol}")
        return {
            "symbol": symbol,
            "last": ticker.get('last'),
            "bid": ticker.get('bid'),
            "ask": ticker.get('ask'),
            "timestamp": ticker.get('timestamp')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    db_ok = db.execute(text("SELECT 1")).fetchone() is not None
    running_bots = db.query(BotDB).filter(BotDB.status == "running").count()
    uptime_s = int(_time.time() - _startup_time)
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    return {
        "status": "ok",
        "db": db_ok,
        "version": "1.2.0",
        "uptime": f"{h}h {m}m {s}s",
        "running_bots": running_bots,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/settings/hyperliquid")
async def get_hyperliquid_settings():
    env = _read_env_values()
    wallet = env.get("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = env.get("HYPERLIQUID_SIGNING_KEY", "")
    use_testnet = env.get("HYPERLIQUID_USE_TESTNET", "True").strip().lower() == "true"

    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)

    testnet_snapshot = {
        "account_value": 0.0,
        "withdrawable": 0.0,
        "margin_used": 0.0,
        "exposure_notional": 0.0,
    }
    testnet_snapshot_error = ""
    mainnet_snapshot = {
        "account_value": 0.0,
        "withdrawable": 0.0,
        "margin_used": 0.0,
        "exposure_notional": 0.0,
    }
    mainnet_snapshot_error = ""
    if wallet_ok:
        try:
            testnet_snapshot = _public_account_snapshot(wallet, True)
        except Exception as e:
            testnet_snapshot_error = str(e)
        try:
            mainnet_snapshot = _public_account_snapshot(wallet, False)
        except Exception as e:
            mainnet_snapshot_error = str(e)

    mainnet_auth_ok = False
    mainnet_auth_error = ""
    selected_env_auth_ok = False
    selected_env_auth_error = ""
    if wallet_ok and key_ok:
        mainnet_auth_ok, mainnet_auth_error = await _check_private_auth(wallet, signing_key, False)
        selected_env_auth_ok, selected_env_auth_error = await _check_private_auth(wallet, signing_key, use_testnet)

    selected_env = "testnet" if use_testnet else "mainnet"
    selected_snapshot = testnet_snapshot if use_testnet else mainnet_snapshot
    selected_snapshot_error = testnet_snapshot_error if use_testnet else mainnet_snapshot_error

    return {
        "wallet_address": wallet,
        "wallet_masked": _mask_wallet(wallet),
        "signing_key_present": bool(signing_key),
        "use_testnet": use_testnet,
        "checks": {
            "selected_env": selected_env,
            "selected_env_auth_ok": selected_env_auth_ok,
            "selected_env_auth_error": selected_env_auth_error if not selected_env_auth_ok else "",
            "wallet_format_ok": wallet_ok,
            "signing_key_format_ok": key_ok,
            "mainnet_auth_ok": mainnet_auth_ok,
            "mainnet_auth_error": mainnet_auth_error if not mainnet_auth_ok else "",
            "selected_env_account_value": selected_snapshot.get("account_value", 0.0),
            "selected_env_withdrawable": selected_snapshot.get("withdrawable", 0.0),
            "selected_env_margin_used": selected_snapshot.get("margin_used", 0.0),
            "selected_env_margin_usage_pct": _margin_usage_pct(selected_snapshot),
            "selected_env_exposure_notional": selected_snapshot.get("exposure_notional", 0.0),
            "selected_env_account_error": selected_snapshot_error,
            "testnet_account_value": testnet_snapshot.get("account_value", 0.0),
            "testnet_withdrawable": testnet_snapshot.get("withdrawable", 0.0),
            "testnet_margin_used": testnet_snapshot.get("margin_used", 0.0),
            "testnet_margin_usage_pct": _margin_usage_pct(testnet_snapshot),
            "mainnet_account_value": mainnet_snapshot.get("account_value", 0.0),
            "mainnet_withdrawable": mainnet_snapshot.get("withdrawable", 0.0),
            "mainnet_margin_used": mainnet_snapshot.get("margin_used", 0.0),
            "mainnet_margin_usage_pct": _margin_usage_pct(mainnet_snapshot),
            "mainnet_exposure_notional": mainnet_snapshot.get("exposure_notional", 0.0),
            "ready_for_real_market": bool(wallet_ok and key_ok and mainnet_auth_ok and float(mainnet_snapshot.get("account_value", 0.0)) > 0),
        },
    }


@app.post("/api/settings/hyperliquid/save")
async def save_hyperliquid_settings(payload: dict = None):
    payload = payload or {}
    wallet = str(payload.get("wallet_address") or "").strip()
    signing_key = str(payload.get("signing_key") or "").strip()
    use_testnet = bool(payload.get("use_testnet", True))

    if not HyperliquidExecutor._is_valid_wallet(wallet):
        raise HTTPException(status_code=400, detail="Wallet inválida. Debe ser 0x + 40 hex")
    if not HyperliquidExecutor._is_valid_private_key(signing_key):
        raise HTTPException(status_code=400, detail="Signing key inválida. Debe ser 0x + 64 hex")

    _write_env_values(
        {
            "HYPERLIQUID_WALLET_ADDRESS": wallet,
            "HYPERLIQUID_SIGNING_KEY": signing_key,
            "HYPERLIQUID_USE_TESTNET": "True" if use_testnet else "False",
        }
    )

    selected_auth_ok, selected_auth_error = await _check_private_auth(wallet, signing_key, use_testnet)

    try:
        testnet_snapshot = _public_account_snapshot(wallet, True)
        testnet_snapshot_error = ""
    except Exception as e:
        testnet_snapshot_error = str(e)
        testnet_snapshot = {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }
    try:
        mainnet_snapshot = _public_account_snapshot(wallet, False)
        mainnet_snapshot_error = ""
    except Exception as e:
        mainnet_snapshot_error = str(e)
        mainnet_snapshot = {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }

    mainnet_auth_ok, _ = await _check_private_auth(wallet, signing_key, False)
    selected_env = "testnet" if use_testnet else "mainnet"
    selected_snapshot = testnet_snapshot if use_testnet else mainnet_snapshot
    selected_snapshot_error = testnet_snapshot_error if use_testnet else mainnet_snapshot_error

    return {
        "saved": True,
        "wallet_masked": _mask_wallet(wallet),
        "use_testnet": use_testnet,
        "checks": {
            "selected_env": selected_env,
            "selected_env_auth_ok": selected_auth_ok,
            "selected_env_auth_error": selected_auth_error if not selected_auth_ok else "",
            "selected_env_account_value": selected_snapshot.get("account_value", 0.0),
            "selected_env_withdrawable": selected_snapshot.get("withdrawable", 0.0),
            "selected_env_margin_used": selected_snapshot.get("margin_used", 0.0),
            "selected_env_margin_usage_pct": _margin_usage_pct(selected_snapshot),
            "selected_env_exposure_notional": selected_snapshot.get("exposure_notional", 0.0),
            "selected_env_account_error": selected_snapshot_error,
            "testnet_account_value": testnet_snapshot.get("account_value", 0.0),
            "testnet_withdrawable": testnet_snapshot.get("withdrawable", 0.0),
            "testnet_margin_used": testnet_snapshot.get("margin_used", 0.0),
            "testnet_margin_usage_pct": _margin_usage_pct(testnet_snapshot),
            "mainnet_account_value": mainnet_snapshot.get("account_value", 0.0),
            "mainnet_withdrawable": mainnet_snapshot.get("withdrawable", 0.0),
            "mainnet_margin_used": mainnet_snapshot.get("margin_used", 0.0),
            "mainnet_margin_usage_pct": _margin_usage_pct(mainnet_snapshot),
            "mainnet_exposure_notional": mainnet_snapshot.get("exposure_notional", 0.0),
            "mainnet_auth_ok": mainnet_auth_ok,
            "ready_for_real_market": bool(mainnet_auth_ok and float(mainnet_snapshot.get("account_value", 0.0)) > 0),
        },
    }


@app.get("/api/production/status")
async def get_production_status():
    return production_guard.latest_status()


@app.post("/api/production/scan")
async def run_production_scan():
    return await production_guard.scan_once(trigger="manual")


@app.get("/api/autotrader/orchestrator/status")
async def autotrader_orchestrator_status():
    return adaptive_orchestrator.latest_status()


@app.post("/api/autotrader/orchestrator/run-once")
async def autotrader_orchestrator_run_once(payload: dict = None):
    payload = payload or {}
    symbol = payload.get("symbol")
    allocation = payload.get("allocation")
    return await adaptive_orchestrator.run_once(trigger="manual", symbol=symbol, allocation=allocation)


@app.post("/api/autotrader/orchestrator/start")
async def autotrader_orchestrator_start():
    await adaptive_orchestrator.start()
    return {
        "started": True,
        "running": True,
        "enabled": adaptive_orchestrator.enabled,
        "interval_sec": adaptive_orchestrator.interval_sec,
    }


@app.post("/api/autotrader/orchestrator/stop")
async def autotrader_orchestrator_stop():
    await adaptive_orchestrator.stop()
    return {
        "stopped": True,
        "running": False,
        "enabled": adaptive_orchestrator.enabled,
    }


@app.get("/api/paper-monitor/status")
async def paper_monitor_status():
    return paper_monitor_runtime.latest_status()


@app.post("/api/paper-monitor/start")
async def paper_monitor_start(payload: dict = None):
    payload = payload or {}
    hours = payload.get("hours")
    interval_sec = payload.get("interval_sec")
    prefix = payload.get("prefix")
    return await paper_monitor_runtime.start(hours=hours, interval_sec=interval_sec, prefix=prefix)


@app.post("/api/paper-monitor/stop")
async def paper_monitor_stop():
    return await paper_monitor_runtime.stop(trigger="manual")


@app.get("/api/production/alerts")
async def get_production_alerts(limit: int = 50, only_open: bool = False, db: Session = Depends(get_db)):
    query = db.query(BotAlertDB).order_by(BotAlertDB.created_at.desc())
    if only_open:
        query = query.filter(BotAlertDB.acknowledged == False)
    alerts = query.limit(limit).all()
    return [
        {
            "id": alert.id,
            "created_at": alert.created_at,
            "bot_id": alert.bot_id,
            "level": alert.level,
            "title": alert.title,
            "message": alert.message,
            "reason_code": alert.reason_code,
            "data": alert.data,
            "acknowledged": alert.acknowledged,
        }
        for alert in alerts
    ]


@app.post("/api/production/alerts/{alert_id}/ack")
async def acknowledge_production_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(BotAlertDB).filter(BotAlertDB.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"message": f"Alert {alert_id} acknowledged"}


@app.get("/api/monitoring/recommendations/{bot_id}/why-not-running")
async def explain_why_not_running(bot_id: str, symbol: str = "", db: Session = Depends(get_db)):
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        raise HTTPException(status_code=404, detail="Bot not found")

    now = datetime.utcnow()
    cfg = dict(bot_entry.config or {})
    strategy = str(bot_entry.strategy or cfg.get("strategy") or "").strip().lower()
    target_symbol = (symbol or cfg.get("symbol") or "").strip()
    runtime_in_memory = bot_id in bot_manager.active_bots

    last_trade = (
        db.query(TradeDB)
        .filter(TradeDB.bot_id == bot_id)
        .order_by(TradeDB.time.desc())
        .first()
    )
    last_order = (
        db.query(OrderLogDB)
        .filter(OrderLogDB.bot_id == bot_id)
        .order_by(OrderLogDB.created_at.desc())
        .first()
    )
    open_positions = (
        db.query(PositionDB)
        .filter(PositionDB.bot_id == bot_id, PositionDB.is_open == True)
        .count()
    )
    recent_alerts = (
        db.query(BotAlertDB)
        .filter(BotAlertDB.bot_id == bot_id)
        .order_by(BotAlertDB.created_at.desc())
        .limit(5)
        .all()
    )

    state_query = db.query(BotLearningStateDB).filter(BotLearningStateDB.bot_id == bot_id)
    if target_symbol:
        state_query = state_query.filter(BotLearningStateDB.symbol == target_symbol)
    learning_rows = state_query.order_by(BotLearningStateDB.updated_at.desc()).limit(3).all()

    checks = {
        "is_archived": bool(bot_entry.is_archived),
        "db_status": str(bot_entry.status or "unknown").lower(),
        "in_memory_running": runtime_in_memory,
        "has_strategy": bool(strategy),
        "has_symbol": bool(target_symbol),
        "has_executor": bool(str(cfg.get("executor") or "").strip()),
        "open_positions": int(open_positions),
        "last_order_status": (str(last_order.status).lower() if last_order and last_order.status else "none"),
        "recent_alerts_count": len(recent_alerts),
    }

    reasons = []
    suggested_actions = []

    if checks["is_archived"]:
        reasons.append("bot_archived")
        suggested_actions.append("Restore bot before trying to start it")

    if checks["db_status"] != BotStatus.RUNNING:
        reasons.append("db_status_not_running")
        suggested_actions.append("Start bot with POST /api/bots/{bot_id}/start")

    if checks["db_status"] == BotStatus.RUNNING and not checks["in_memory_running"]:
        reasons.append("running_in_db_but_missing_in_memory")
        suggested_actions.append("Restart API or call start endpoint to resync bot runtime")

    if not checks["has_strategy"]:
        reasons.append("missing_strategy")
        suggested_actions.append("Set valid strategy in bot config")

    if not checks["has_symbol"] and ("pair" not in strategy):
        reasons.append("missing_symbol")
        suggested_actions.append("Set symbol in bot config (example: BTC/USDT)")

    if "pair" in strategy and not str(cfg.get("pair_symbol_b") or "").strip():
        reasons.append("missing_pair_symbol_b")
        suggested_actions.append("Set pair_symbol_b for paired strategy")

    if checks["last_order_status"] in {"failed", "cancelled"}:
        reasons.append("last_order_not_executed")
        suggested_actions.append("Review executor credentials, market symbol and order constraints")

    critical_alert = next((a for a in recent_alerts if str(a.level or "").lower() == "critical"), None)
    if critical_alert:
        reasons.append("critical_alert_recent")
        suggested_actions.append("Inspect /api/production/alerts and resolve critical conditions")

    if checks["db_status"] == BotStatus.RUNNING and checks["in_memory_running"] and not checks["is_archived"]:
        if last_trade:
            idle_minutes = int(max(0, (now - last_trade.time).total_seconds() // 60))
            if idle_minutes >= 120:
                reasons.append("running_but_no_recent_trades")
                suggested_actions.append("Tune thresholds or lower entry filters for current market regime")
        elif open_positions == 0:
            reasons.append("running_without_trade_history")
            suggested_actions.append("Allow warm-up time or loosen entry conditions")

    if not reasons:
        reasons.append("no_blocking_issue_detected")
        suggested_actions.append("Bot appears healthy; monitor more sample time for signal frequency")

    learning_state = []
    for row in learning_rows:
        state = dict(row.state or {})
        learning_state.append(
            {
                "symbol": row.symbol,
                "updated_at": row.updated_at,
                "last_decision": state.get("last_decision"),
                "last_open_error": state.get("last_open_error"),
                "last_pair_close_reason": state.get("last_pair_close_reason"),
                "win_rate": state.get("win_rate"),
                "cumulative_pnl": state.get("cumulative_pnl"),
            }
        )

    summary = {
        "bot_id": bot_id,
        "strategy": strategy,
        "symbol": target_symbol,
        "status": checks["db_status"],
        "in_memory_running": checks["in_memory_running"],
        "open_positions": checks["open_positions"],
        "last_trade_at": last_trade.time if last_trade else None,
        "last_order_status": checks["last_order_status"],
        "latest_alert": {
            "level": recent_alerts[0].level,
            "title": recent_alerts[0].title,
            "reason_code": recent_alerts[0].reason_code,
            "created_at": recent_alerts[0].created_at,
        } if recent_alerts else None,
    }

    return {
        "summary": summary,
        "checks": checks,
        "reasons": reasons,
        "suggested_actions": list(dict.fromkeys(suggested_actions)),
        "learning_state": learning_state,
    }

@app.get("/api/strategies")
async def list_strategies():
    return [
        {
            "id": "ema_cross",
            "name": "EMA Cross",
            "description": "Genera señales cuando la media móvil rápida cruza la lenta.",
            "params": [{"key": "fast_ema", "default": 9}, {"key": "slow_ema", "default": 21}]
        },
        {
            "id": "technical_pro",
            "name": "Technical Pro (RSI/MACD/Fib)",
            "description": "Combinación de RSI, MACD y niveles de Fibonacci.",
            "params": []
        },
        {
            "id": "algo_expert",
            "name": "AlgoExpert",
            "description": "EMA + RSI + ATR + VWAP multi-confirmación.",
            "params": []
        },
        {
            "id": "dynamic_reinvest",
            "name": "Dynamic Reinvestment",
            "description": "Reinvierte las ganancias automáticamente con un take profit configurable.",
            "params": [{"key": "take_profit_pct", "default": 0.02}]
        },
        {
            "id": "grid_trading",
            "name": "Grid Trading",
            "description": "Compra barato y vende caro dentro de un rango de precio con rejillas.",
            "params": [
                {"key": "upper_limit", "default": 70000},
                {"key": "lower_limit", "default": 60000},
                {"key": "num_grids", "default": 10}
            ]
        },
        {
            "id": "adaptive_learning",
            "name": "Adaptive Learning",
            "description": "Autogestión con aprendizaje de tendencia/histórico y reinversión dinámica.",
            "params": [
                {"key": "adaptive_short_window", "default": 12},
                {"key": "adaptive_long_window", "default": 48},
                {"key": "adaptive_base_amount", "default": 0.01},
                {"key": "reinvest_ratio", "default": 0.35},
                {"key": "self_managed", "default": True}
            ]
        }
    ]


@app.post("/api/market/compare")
async def compare_market_symbols(payload: dict = None):
    payload = payload or {}
    symbol_a = (payload.get("symbol_a") or "BTC/USDT").strip() or "BTC/USDT"
    symbol_b = (payload.get("symbol_b") or "ETH/USDT").strip() or "ETH/USDT"

    mde = MarketDataEngine('binance')
    try:
        ticker_a = await mde.fetch_ticker(symbol_a)
        ticker_b = await mde.fetch_ticker(symbol_b)

        price_a = float(ticker_a.get("last") or 0.0)
        price_b = float(ticker_b.get("last") or 0.0)

        if price_a <= 0 or price_b <= 0:
            raise HTTPException(status_code=400, detail="Could not fetch real market prices for one or both symbols")

        return {
            "symbol_a": symbol_a,
            "price_a": price_a,
            "symbol_b": symbol_b,
            "price_b": price_b,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "binance",
        }
    finally:
        await mde.close()


async def _resolve_market_candles(symbol: str, timeframe: str, limit: int, source: str) -> tuple[list, str]:
    src = (source or "live").strip().lower()
    if src == "imported":
        imported = _load_imported_candles(symbol, timeframe)
        return imported[-limit:] if limit > 0 else imported, "imported"

    mde = MarketDataEngine("binance")
    try:
        candles = await mde.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return _normalize_candles(candles), "live"
    finally:
        await mde.close()


@app.post("/api/market/data/import")
async def import_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    data_format = (payload.get("format") or "json").strip().lower()
    data_raw = payload.get("data")

    if not data_raw:
        raise HTTPException(status_code=400, detail="Missing import data")

    try:
        if data_format == "csv":
            candles = _parse_csv_candles(str(data_raw))
        else:
            parsed = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            if isinstance(parsed, dict) and "candles" in parsed:
                parsed = parsed.get("candles")
            if not isinstance(parsed, list):
                raise ValueError("Invalid JSON format; expected array of candles")
            candles = _normalize_candles(parsed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid import format: {e}")

    if not candles:
        raise HTTPException(status_code=400, detail="No valid candles found in imported data")

    _save_imported_candles(symbol, timeframe, candles)
    return {
        "imported": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": len(candles),
        "first_time": candles[0]["time"],
        "last_time": candles[-1]["time"],
        "source": "imported",
    }


@app.post("/api/market/data/fetch")
async def fetch_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    source = (payload.get("source") or "live").strip().lower()
    limit = int(payload.get("limit") or 300)
    limit = max(20, min(limit, 2000))

    candles, resolved_source = await _resolve_market_candles(symbol, timeframe, limit, source)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candles available for {symbol} ({resolved_source})")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": resolved_source,
        "rows": len(candles),
        "candles": candles,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/market/data/export")
async def export_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    source = (payload.get("source") or "live").strip().lower()
    data_format = (payload.get("format") or "json").strip().lower()
    limit = int(payload.get("limit") or 500)
    limit = max(20, min(limit, 5000))

    candles, resolved_source = await _resolve_market_candles(symbol, timeframe, limit, source)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candles available for {symbol} ({resolved_source})")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"{_sanitize_asset_key(symbol)}_{_sanitize_asset_key(timeframe)}_{resolved_source}_{stamp}"

    if data_format == "csv":
        content = _candles_to_csv(candles)
        filename = f"{base_name}.csv"
    else:
        content = json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": resolved_source,
                "rows": len(candles),
                "candles": candles,
            },
            ensure_ascii=False,
            indent=2,
        )
        filename = f"{base_name}.json"

    return {
        "exported": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "source": resolved_source,
        "format": data_format,
        "rows": len(candles),
        "filename": filename,
        "content": content,
    }

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).all()
    total_trades = len(trades)
    total_fees = sum(t.fee or 0 for t in trades)
    total_pnl = sum(t.pnl or 0 for t in trades)
    net_pnl = total_pnl - total_fees
    total_volume = sum((t.price or 0) * (t.amount or 0) for t in trades)
    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
    win_rate = round((wins / total_trades * 100), 2) if total_trades > 0 else 0
    open_positions = db.query(PositionDB).filter(PositionDB.is_open == True).count()
    open_orders = db.query(OrderLogDB).filter(OrderLogDB.status == "open").count()
    return {
        "total_trades": total_trades,
        "total_fees": round(total_fees, 4),
        "total_pnl": round(total_pnl, 4),
        "net_pnl": round(net_pnl, 4),
        "total_volume": round(total_volume, 2),
        "win_rate": win_rate,
        "wins": wins,
        "losses": total_trades - wins,
        "open_positions": open_positions,
        "open_orders": open_orders
    }


@app.post("/api/monitoring/recommendations")
async def monitoring_recommendations(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 8) or 8)
    top_n = int(payload.get("top_n", 3) or 3)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))
    top_n = max(1, min(top_n, 20))

    activate = _as_bool(payload.get("activate", False), default=False)
    only_stopped = _as_bool(payload.get("only_stopped", True), default=True)
    require_positive_score = _as_bool(payload.get("require_positive_score", True), default=True)

    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    trades = db.query(TradeDB).filter(TradeDB.time >= since).all()
    bots = db.query(BotDB).filter(BotDB.is_archived == False).all()

    stats_by_bot = {
        bot.id: {
            "bot_id": bot.id,
            "status": bot.status,
            "strategy": bot.strategy,
            "total_trades": 0,
            "scored_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_volume": 0.0,
        }
        for bot in bots
    }

    for trade in trades:
        bot_metrics = stats_by_bot.get(trade.bot_id)
        if not bot_metrics:
            continue
        trade_fee = float(trade.fee or 0.0)
        trade_pnl = float(trade.pnl or 0.0)
        bot_metrics["total_trades"] += 1
        bot_metrics["total_fees"] += trade_fee
        bot_metrics["total_pnl"] += trade_pnl
        bot_metrics["total_volume"] += float((trade.price or 0.0) * (trade.amount or 0.0))

        if trade_pnl != 0.0:
            bot_metrics["scored_trades"] += 1
            if trade_pnl > 0:
                bot_metrics["wins"] += 1
            else:
                bot_metrics["losses"] += 1

    recommendations = []
    for bot in bots:
        bot_metrics = stats_by_bot[bot.id]
        scored_trades = bot_metrics["scored_trades"]
        total_pnl = bot_metrics["total_pnl"]
        total_fees = bot_metrics["total_fees"]
        net_pnl = total_pnl - total_fees
        win_rate = (bot_metrics["wins"] / scored_trades * 100) if scored_trades > 0 else 0.0
        activity_bonus = min(scored_trades, 20) * 0.5
        score = (win_rate * 0.35) + (net_pnl * 5.0) + activity_bonus

        eligible = scored_trades >= min_scored_trades
        if only_stopped and bot.status == BotStatus.RUNNING:
            eligible = False
        if require_positive_score and score <= 0:
            eligible = False
        if win_rate < 50:
            eligible = False
        if net_pnl <= 0:
            eligible = False

        recommendations.append(
            {
                **bot_metrics,
                "win_rate": round(win_rate, 2),
                "net_pnl": round(net_pnl, 6),
                "score": round(score, 4),
                "eligible": eligible,
            }
        )

    recommendations.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    suggested = [item for item in recommendations if item["eligible"]][:top_n]

    activation_results = []
    if activate:
        for item in suggested:
            bot_id = item["bot_id"]
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id, BotDB.is_archived == False).first()
            if not bot_entry:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "bot_not_found"})
                continue
            if bot_entry.status == BotStatus.RUNNING:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "already_running"})
                continue

            started = bot_manager.start_bot(bot_id, bot_entry.config or {})
            if started:
                bot_entry.status = BotStatus.RUNNING
                db.commit()
                activation_results.append({"bot_id": bot_id, "activated": True, "reason": "started"})
            else:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "start_failed"})

    return {
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "top_n": top_n,
        "activate": activate,
        "only_stopped": only_stopped,
        "require_positive_score": require_positive_score,
        "sampled_bots": len(bots),
        "sampled_trades": len(trades),
        "suggested_to_activate": suggested,
        "activation_results": activation_results,
        "ranking": recommendations,
    }


@app.post("/api/monitoring/test-results")
async def monitoring_test_results(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 5) or 5)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))

    return _build_monitoring_test_results(db, lookback_hours, min_scored_trades)


@app.post("/api/monitoring/activate-production")
async def activate_bot_for_production(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    bot_id = str(payload.get("bot_id") or "").strip()
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 8) or 8)

    if not bot_id:
        raise HTTPException(status_code=400, detail="bot_id is required")

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))

    result = await _activate_bot_for_production_internal(
        db,
        bot_id=bot_id,
        lookback_hours=lookback_hours,
        min_scored_trades=min_scored_trades,
        trigger="manual_activate_production",
    )

    if result.get("reason") == "bot_not_found":
        raise HTTPException(status_code=404, detail="Bot not found")
    if result.get("reason") == "bot_archived":
        raise HTTPException(status_code=400, detail="Bot is archived. Restore it first.")

    return result


@app.post("/api/monitoring/auto-activate-ready")
async def auto_activate_ready_bots(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 12) or 12)
    top_n = int(payload.get("top_n", 2) or 2)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))
    top_n = max(1, min(top_n, 20))

    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    candidates = [item for item in monitoring.get("results", []) if item.get("candidate_for_production")]
    selected = candidates[:top_n]

    activation_results = []
    for item in selected:
        bot_id = str(item.get("bot_id") or "").strip()
        if not bot_id:
            continue
        activation_results.append(
            await _activate_bot_for_production_internal(
                db,
                bot_id=bot_id,
                lookback_hours=lookback_hours,
                min_scored_trades=min_scored_trades,
                trigger="auto_mode_on",
            )
        )

    activated_count = sum(1 for item in activation_results if item.get("activated"))
    blocked_count = len(activation_results) - activated_count

    return {
        "trigger": "auto_mode_on",
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "top_n": top_n,
        "production_candidates_detected": len(candidates),
        "attempted": len(activation_results),
        "activated": activated_count,
        "blocked": blocked_count,
        "results": activation_results,
    }

@app.get("/api/positions")
async def get_positions(sync: bool = True, db: Session = Depends(get_db)):
    if sync:
        try:
            await _sync_positions_with_best_executor()
        except Exception as e:
            print(f"[Positions] sync failed before read: {e}")

    positions = db.query(PositionDB).filter(PositionDB.is_open == True).order_by(PositionDB.opened_at.desc()).all()
    result = []
    for p in positions:
        result.append({
            "id": p.id,
            "bot_id": p.bot_id,
            "symbol": p.symbol,
            "side": p.side,
            "entry_price": p.entry_price,
            "quantity": p.quantity,
            "current_price": p.current_price,
            "unrealized_pnl": round(p.unrealized_pnl or 0, 4),
            "fee_paid": round(p.fee_paid or 0, 4),
            "opened_at": p.opened_at
        })
    return result

@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str, db: Session = Depends(get_db)):
    position = db.query(PositionDB).filter(PositionDB.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    
    position.is_open = False
    position.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"Position {position_id} closed manually"}

@app.get("/api/orders")
async def get_order_log(limit: int = 100, db: Session = Depends(get_db)):
    orders = db.query(OrderLogDB).order_by(OrderLogDB.created_at.desc()).limit(limit).all()
    return [
        {
            "id": o.id,
            "bot_id": o.bot_id,
            "symbol": o.symbol,
            "side": o.side,
            "status": o.status,
            "price": o.price,
            "amount": o.amount,
            "filled_amount": o.filled_amount,
            "fee": round(o.fee or 0, 6),
            "pnl": round(o.pnl or 0, 4),
            "strategy": o.strategy,
            "executor": o.executor,
            "created_at": o.created_at,
            "updated_at": o.updated_at
        }
        for o in orders
    ]

@app.post("/risk/kill-switch")
async def activate_kill_switch():
    risk_engine.trigger_kill_switch()
    # Stop all bots in manager as well
    for bot_id in list(bot_manager.active_bots.keys()):
        bot_manager.stop_bot(bot_id)
    return {"message": "Global Kill Switch activated. All trades and bots stopped."}

@app.get("/api/bots")
async def list_bots(db: Session = Depends(get_db)):
    db_bots = db.query(BotDB).all()
    return db_bots


@app.get("/api/bot-presets")
async def list_bot_presets_api():
    return {"presets": list_bot_presets()}


@app.post("/api/bot-advisor/analyze")
async def analyze_bot_options(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    symbol = payload.get("symbol", "BTC/USDT")
    allocation = payload.get("allocation", 500)
    return await build_bot_advice(db, symbol=symbol, allocation=allocation)


@app.post("/api/bot-advisor/from-text")
async def build_bot_from_text(payload: dict = None):
    payload = payload or {}
    prompt = str(payload.get("prompt") or "").strip()
    symbol = str(payload.get("symbol") or "BTC/USDT").strip()
    allocation = float(payload.get("allocation") or 500)
    return _bot_config_from_prompt(prompt=prompt, symbol=symbol, allocation=allocation)


@app.post("/api/bot-advisor/execute")
async def execute_bot_advisor(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    horizon = (payload.get("horizon") or "").strip().lower()
    symbol = payload.get("symbol", "BTC/USDT")
    allocation = payload.get("allocation", 500)

    if horizon not in {"corto", "medio", "largo"}:
        raise HTTPException(status_code=400, detail="horizon must be one of: corto, medio, largo")

    analysis = await build_bot_advice(db, symbol=symbol, allocation=allocation)
    rec = next((item for item in analysis.get("recommendations", []) if item.get("horizon") == horizon), None)
    if not rec:
        raise HTTPException(status_code=404, detail="No recommendation available for selected horizon")

    if rec.get("recommended_action") in {"tune_existing", "reduce_risk"} and rec.get("recommended_bot_id") and rec.get("edited_config"):
        bot_id = rec.get("recommended_bot_id")
        success = bot_manager.update_bot_config(bot_id, rec.get("edited_config") or {})
        if not success:
            raise HTTPException(status_code=404, detail=f"Recommended bot {bot_id} not found")

        return {
            "executed": True,
            "action": rec.get("recommended_action"),
            "bot_id": bot_id,
            "horizon": horizon,
            "message": f"Bot {bot_id} updated using advisor recommendation ({rec.get('recommended_action')})",
        }

    config = (rec.get("new_bot_config") or {}).copy()
    new_bot_id = f"advisor_{horizon}_{uuid.uuid4().hex[:6]}"
    config["id"] = new_bot_id

    success = bot_manager.start_bot(new_bot_id, config)
    if not success:
        raise HTTPException(status_code=400, detail="Unable to create advisor bot")

    return {
        "executed": True,
        "action": "create_new",
        "bot_id": new_bot_id,
        "horizon": horizon,
        "message": f"Advisor created bot {new_bot_id}",
    }


@app.post("/api/bot-presets/{preset_id}/create")
async def create_bot_from_preset(preset_id: str, payload: dict = None):
    preset = get_bot_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    payload = payload or {}
    overrides = payload.get("overrides", {}) if isinstance(payload, dict) else {}

    base_config = preset.get("config", {}).copy()
    base_config.update(overrides)

    bot_id = (payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not bot_id:
        bot_id = f"{preset_id}_{uuid.uuid4().hex[:6]}"

    base_config["id"] = bot_id

    success = bot_manager.start_bot(bot_id, base_config)
    if not success:
        raise HTTPException(status_code=400, detail="Bot already exists or could not be started")

    return {
        "bot_id": bot_id,
        "status": BotStatus.RUNNING,
        "preset_id": preset_id,
        "preset_name": preset.get("name"),
    }


@app.post("/api/bot-presets/{preset_id}/save")
async def save_bot_from_preset_to_vault(
    preset_id: str,
    payload: dict = None,
    db: Session = Depends(get_db),
):
    preset = get_bot_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    payload = payload or {}
    overrides = payload.get("overrides", {}) if isinstance(payload, dict) else {}

    base_config = preset.get("config", {}).copy()
    base_config.update(overrides)

    bot_id = (payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not bot_id:
        bot_id = f"{preset_id}_{uuid.uuid4().hex[:6]}"

    existing = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bot ID already exists")

    base_config["id"] = bot_id

    bot_entry = BotDB(
        id=bot_id,
        strategy=base_config.get("strategy", preset.get("strategy", "ema_cross")),
        status=BotStatus.STOPPED,
        config=base_config,
        is_archived=True,
    )
    db.add(bot_entry)
    db.commit()

    return {
        "bot_id": bot_id,
        "status": BotStatus.STOPPED,
        "is_archived": True,
        "preset_id": preset_id,
        "preset_name": preset.get("name"),
        "message": "Bot saved in Vault without launch",
    }

@app.post("/api/bots")
async def create_bot(bot_config: dict):
    bot_id = bot_config.get("id", "").strip()
    if not bot_id:
        # Fallback to auto-generation if not provided at all, but only if empty string wasn't explicitly sent
        if "id" not in bot_config or not bot_config["id"]:
            bot_id = f"bot_{len(bot_manager.active_bots) + 1}"
        else:
            raise HTTPException(status_code=400, detail="Bot ID cannot be empty or whitespace")
            
    success = bot_manager.start_bot(bot_id, bot_config)
    if not success:
        raise HTTPException(status_code=400, detail="Bot already exists or could not be started")
    return {"bot_id": bot_id, "status": BotStatus.RUNNING}

@app.patch("/api/bots/{bot_id}")
async def update_bot(bot_id: str, new_config: dict):
    success = bot_manager.update_bot_config(bot_id, new_config)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    return {"message": f"Bot {bot_id} configuration updated", "id": bot_id}

@app.post("/api/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    success = bot_manager.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found or not running")
    return {"message": f"Bot {bot_id} stopped"}

@app.delete("/api/bots/{bot_id}")
async def delete_bot(bot_id: str):
    success = bot_manager.delete_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} deleted"}

@app.post("/api/bots/{bot_id}/archive")
async def archive_bot(bot_id: str):
    success = bot_manager.archive_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} archived"}

@app.post("/api/bots/{bot_id}/restore")
async def restore_bot(bot_id: str):
    success = bot_manager.restore_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} restored"}

@app.post("/api/bots/{bot_id}/start")
async def start_existing_bot(bot_id: str, db: Session = Depends(get_db)):
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        raise HTTPException(status_code=404, detail="Bot not found in database")
    
    if bot_entry.is_archived:
        raise HTTPException(status_code=400, detail="Cannot start an archived bot. Restore it first.")
    
    # If already running in memory, treat as success (idempotent)
    if bot_id in bot_manager.active_bots:
        return {"message": f"Bot {bot_id} is already running"}

    success = bot_manager.start_bot(bot_id, bot_entry.config)
    if not success:
        raise HTTPException(status_code=400, detail="Bot failed to start")
    return {"message": f"Bot {bot_id} started"}

@app.get("/api/trades")
async def list_trades(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).limit(50).all()
    return trades

@app.get("/api/portfolio/{bot_id}")
async def get_portfolio(bot_id: str, db: Session = Depends(get_db)):
    """Obtiene el portfolio de paper trading de un bot específico"""
    portfolio = db.query(PaperPortfolioDB).filter(PaperPortfolioDB.bot_id == bot_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found for this bot")
    
    return {
        "bot_id": portfolio.bot_id,
        "cash_balance": portfolio.cash_balance,
        "positions": portfolio.positions,
        "total_equity": portfolio.total_equity,
        "realized_pnl": portfolio.realized_pnl,
        "updated_at": portfolio.updated_at
    }

@app.get("/api/ai/explain/{trade_id}")
async def explain_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(TradeDB).filter(TradeDB.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    explanation = await ai_engine.generate_explanation({
        "symbol": trade.symbol,
        "side": trade.side,
        "price": trade.price,
        "amount": trade.amount,
        "bot_id": trade.bot_id
    })
    return {"explanation": explanation}

@app.get("/api/reports/json")
async def get_json_report(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).all()
    metrics = calculate_metrics(trades)
    return reporting_engine.generate_json_report(trades, metrics)

@app.get("/api/reports/pdf")
async def get_pdf_report(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).all()
    metrics = calculate_metrics(trades)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    file_path = reporting_engine.generate_pdf_report(filename, trades, metrics)
    return FileResponse(file_path, filename=filename, media_type="application/pdf")

@app.post("/api/backtest/run")
async def run_backtest(params: dict):
    symbol = params.get("symbol", "BTC/USDT")
    timeframe = params.get("timeframe", "1h")
    limit = params.get("limit", 100)
    
    strategy_name = params.get("strategy", "ema_cross")
    if "technical_pro" in strategy_name.lower():
        strategy = TechnicalProStrategy()
    elif "algo_expert" in strategy_name.lower():
        strategy = AlgoExpertStrategy()
    elif "dynamic_reinvest" in strategy_name.lower():
        tp = params.get("take_profit_pct", 0.02)
        strategy = DynamicReinvestStrategy(take_profit_pct=tp)
    else:
        strategy = EMACrossStrategy()
        
    engine = BacktestEngine(strategy)
    
    try:
        historical_data = await engine.fetch_historical_data(symbol, timeframe, limit)
        results = await engine.run(historical_data)
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync/positions")
async def sync_positions():
    """Sincroniza las posiciones del exchange con la DB local."""
    return await _sync_positions_with_best_executor()

@app.post("/api/bots/adopt")
async def adopt_bot(bot_id: str, symbol: str, strategy: str = "algo_expert"):
    """Adopta una posición huérfana con un nuevo bot."""
    config = {
        "symbol": symbol,
        "strategy": strategy,
        "executor": "paper" # Por defecto para esta versión
    }
    success = await bot_manager.adopt_position(bot_id, symbol, strategy, config)
    if success:
        return {"message": f"Bot {bot_id} adopted position for {symbol}"}
    raise HTTPException(status_code=400, detail="Could not adopt position")

# Mount static files last
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon_path = os.path.join(static_dir, "favicon.svg")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="favicon_not_found")
