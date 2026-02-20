import asyncio
import os
import shutil
import unittest.mock as mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Test Database Setup
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# CRITICAL: We need to mock the engine in apps.shared.database BEFORE importing models
with mock.patch("apps.shared.database.engine", test_engine), \
     mock.patch("apps.shared.database.SessionLocal", TestingSessionLocal):
    from apps.shared.database import Base
    from apps.shared.models import TradeSignal, TradeSide, BotStatus, BotDB
    from apps.engine.market_data import MarketDataEngine
    from apps.engine.risk import RiskEngine
    from apps.bot_manager.manager import BotManager
    from apps.ai_engine.engine import AIEngine

def setup_test_db():
    print("--- [Setup] Initializing Test SQLite DB ---")
    Base.metadata.create_all(bind=test_engine)

def teardown_test_db():
    print("--- [Teardown] Cleaning up Test SQLite DB ---")
    # No file to remove for in-memory DB
    pass

async def test_core_logic():
    print("\n--- [1] Testing Core Logic (Market Data & Risk) ---")
    mde = MarketDataEngine('binance')
    try:
        price = await mde.get_latest_price('BTC/USDT')
        print(f"Latest BTC/Price (Public): {price}")
    except Exception as e:
        print(f"Market Data Error (Expected if offline): {e}")

    risk = RiskEngine(global_kill_switch=False, max_exposure=100)
    signal = TradeSignal(symbol='BTC/USDT', side=TradeSide.BUY, amount=0.001, price=40000, strategy_id='test_suite')
    res = await risk.validate(signal)
    print(f"Risk Check (OK): Approved={res.approved}")
    assert res.approved is True

async def test_bot_manager_with_sqlite():
    print("\n--- [2] Testing Bot Manager (SQLite Fallback) ---")
    # Patch SessionLocal to use our test engine
    import apps.bot_manager.manager as bm_mod
    import apps.shared.database as db_mod
    
    original_session = bm_mod.SessionLocal
    bm_mod.SessionLocal = TestingSessionLocal
    db_mod.SessionLocal = TestingSessionLocal

    manager = BotManager()
    bot_id = "test_bot_001"
    config = {"strategy": "ema_cross", "symbol": "BTC/USDT"}
    
    print(f"Starting bot {bot_id}...")
    success = manager.start_bot(bot_id, config)
    print(f"Bot started successfully: {success}")
    assert success is True
    
    await asyncio.sleep(2) # Let it run for a bit
    
    print(f"Stopping bot {bot_id}...")
    stopped = manager.stop_bot(bot_id)
    print(f"Bot stopped: {stopped}")
    assert stopped is True

    # Give it a moment to update DB status
    await asyncio.sleep(1)

    # Check DB state
    with TestingSessionLocal() as db:
        bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
        print(f"Bot status in DB: {bot.status if bot else 'None'}")
        if bot:
            print(f"Bot config: {bot.config}")
        assert bot is not None
        assert bot.status == "stopped"

    # Restore sessions
    bm_mod.SessionLocal = original_session
    db_mod.SessionLocal = original_session

async def test_ai_engine_fallback():
    print("\n--- [3] Testing AI Engine (Fallback Logic) ---")
    ai = AIEngine(model_name="non_existent_model")
    trade_data = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "price": 50000,
        "amount": 0.1,
        "bot_id": "test_ai"
    }
    
    explanation = await ai.generate_explanation(trade_data)
    print(f"AI Explanation: {explanation}")
    assert "AI Insight" in explanation

async def main():
    setup_test_db()
    try:
        await test_core_logic()
        await test_bot_manager_with_sqlite()
        await test_ai_engine_fallback()
        print("\n--- ALL TESTS PASSED ---")
    finally:
        teardown_test_db()

if __name__ == "__main__":
    asyncio.run(main())
