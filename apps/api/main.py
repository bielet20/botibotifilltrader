from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.engine.backtester import BacktestEngine
from apps.engine.ema_cross import EMACrossStrategy
from apps.engine.technical_pro import TechnicalProStrategy
from apps.engine.risk import RiskEngine
from apps.bot_manager.manager import BotManager
from apps.ai_engine.engine import AIEngine
from apps.reporting_engine.reporting import ReportingEngine, calculate_metrics
from apps.shared.database import init_db, get_db
from apps.shared.models import BotDB, TradeDB, BotStatus
from apps.engine.paper_portfolio import PaperPortfolioDB

app = FastAPI(title="Trading Platform API Gateway")

# Initialize DB on start
@app.on_event("startup")
async def startup_event():
    init_db()
    # Resume bots in background
    await bot_manager.resume_bots()

# Singleton-like instances
risk_engine = RiskEngine()
bot_manager = BotManager()
ai_engine = AIEngine()
reporting_engine = ReportingEngine()

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    # Verify DB connection
    db_ok = db.execute(text("SELECT 1")).fetchone() is not None
    return {"status": "ok", "db": db_ok, "version": "0.1.0"}

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
    bot_id = bot_config.get("id", f"bot_{len(bot_manager.active_bots) + 1}")
    success = bot_manager.start_bot(bot_id, bot_config)
    if not success:
        raise HTTPException(status_code=400, detail="Bot already exists or could not be started")
    return {"bot_id": bot_id, "status": BotStatus.RUNNING}

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
    
    success = bot_manager.start_bot(bot_id, bot_entry.config)
    if not success:
        raise HTTPException(status_code=400, detail="Bot already running or failed to start")
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
    else:
        strategy = EMACrossStrategy()
        
    engine = BacktestEngine(strategy)
    
    try:
        historical_data = await engine.fetch_historical_data(symbol, timeframe, limit)
        results = await engine.run(historical_data)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files last
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))
