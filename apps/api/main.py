from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.engine.backtester import BacktestEngine
from apps.engine.ema_cross import EMACrossStrategy
from apps.engine.technical_pro import TechnicalProStrategy
from apps.engine.algo_expert import AlgoExpertStrategy
from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
from apps.engine.risk import RiskEngine
from apps.bot_manager.manager import BotManager
from apps.ai_engine.engine import AIEngine
from apps.reporting_engine.reporting import ReportingEngine, calculate_metrics
from apps.shared.database import init_db, get_db
from apps.shared.models import BotDB, TradeDB, BotStatus, OrderLogDB, PositionDB
from apps.engine.paper_portfolio import PaperPortfolioDB
from apps.engine.position_sync import PositionSyncService
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
market_data_engine = MarketDataEngine() # Instance for live market data

@app.on_event("startup")
async def startup_event():
    init_db()
    await bot_manager.resume_bots()

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
        }
    ]

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).all()
    total_trades = len(trades)
    total_fees = sum(t.fee or 0 for t in trades)
    total_pnl = sum(t.pnl or 0 for t in trades)
    total_volume = sum((t.price or 0) * (t.amount or 0) for t in trades)
    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
    win_rate = round((wins / total_trades * 100), 2) if total_trades > 0 else 0
    open_positions = db.query(PositionDB).filter(PositionDB.is_open == True).count()
    open_orders = db.query(OrderLogDB).filter(OrderLogDB.status == "open").count()
    return {
        "total_trades": total_trades,
        "total_fees": round(total_fees, 4),
        "total_pnl": round(total_pnl, 4),
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
