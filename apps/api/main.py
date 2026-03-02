from datetime import datetime
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
from apps.reporting_engine.reporting import ReportingEngine, calculate_metrics
from apps.reporting_engine.production_guard import ProductionGuardService
from apps.shared.database import init_db, get_db
from apps.shared.models import BotDB, TradeDB, BotStatus, OrderLogDB, PositionDB, BotAlertDB
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


def _public_account_value(wallet: str, use_testnet: bool) -> float:
    if not wallet:
        return 0.0
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
    return float(margin.get("accountValue") or 0.0)


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

@app.on_event("startup")
async def startup_event():
    init_db()
    await bot_manager.resume_bots()
    await production_guard.start()


@app.on_event("shutdown")
async def shutdown_event():
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

    testnet_value = 0.0
    mainnet_value = 0.0
    if wallet_ok:
        try:
            testnet_value = _public_account_value(wallet, True)
        except Exception:
            pass
        try:
            mainnet_value = _public_account_value(wallet, False)
        except Exception:
            pass

    mainnet_auth_ok = False
    mainnet_auth_error = ""
    if wallet_ok and key_ok:
        mainnet_auth_ok, mainnet_auth_error = await _check_private_auth(wallet, signing_key, False)

    return {
        "wallet_address": wallet,
        "wallet_masked": _mask_wallet(wallet),
        "signing_key_present": bool(signing_key),
        "use_testnet": use_testnet,
        "checks": {
            "wallet_format_ok": wallet_ok,
            "signing_key_format_ok": key_ok,
            "mainnet_auth_ok": mainnet_auth_ok,
            "mainnet_auth_error": mainnet_auth_error if not mainnet_auth_ok else "",
            "testnet_account_value": testnet_value,
            "mainnet_account_value": mainnet_value,
            "ready_for_real_market": bool(wallet_ok and key_ok and mainnet_auth_ok and mainnet_value > 0),
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
        testnet_value = _public_account_value(wallet, True)
    except Exception:
        testnet_value = 0.0
    try:
        mainnet_value = _public_account_value(wallet, False)
    except Exception:
        mainnet_value = 0.0

    mainnet_auth_ok, _ = await _check_private_auth(wallet, signing_key, False)

    return {
        "saved": True,
        "wallet_masked": _mask_wallet(wallet),
        "use_testnet": use_testnet,
        "checks": {
            "selected_env": "testnet" if use_testnet else "mainnet",
            "selected_env_auth_ok": selected_auth_ok,
            "selected_env_auth_error": selected_auth_error if not selected_auth_ok else "",
            "testnet_account_value": testnet_value,
            "mainnet_account_value": mainnet_value,
            "mainnet_auth_ok": mainnet_auth_ok,
            "ready_for_real_market": bool(mainnet_auth_ok and mainnet_value > 0),
        },
    }


@app.get("/api/production/status")
async def get_production_status():
    return production_guard.latest_status()


@app.post("/api/production/scan")
async def run_production_scan():
    return await production_guard.scan_once(trigger="manual")


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

@app.get("/api/positions")
async def get_positions(db: Session = Depends(get_db)):
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
    # En una implementación real, elegiríamos el executor según la configuración
    from apps.engine.paper_executor import PaperTradingExecutor
    executor = PaperTradingExecutor() 
    sync_service = PositionSyncService(executor)
    results = await sync_service.sync_positions()
    return results

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
