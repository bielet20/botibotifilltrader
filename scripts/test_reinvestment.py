import asyncio
from datetime import datetime
import unittest.mock as mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1. Setup in-memory DB and patch early
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

with mock.patch("apps.shared.database.engine", test_engine), \
     mock.patch("apps.shared.database.SessionLocal", TestingSessionLocal):
    from apps.shared.database import Base
    from apps.shared.models import TradeSide, ExecutionResult
    from apps.engine.paper_portfolio import PaperTradingPortfolio, PaperPortfolioDB
    from apps.engine.dynamic_reinvest import DynamicReinvestStrategy

async def test_profit_split():
    print("\n--- Testing Profit Split Logic ---")
    Base.metadata.create_all(bind=test_engine)
    
    bot_id = "test_reinvest_001"
    # 50% savings ratio
    with TestingSessionLocal() as db:
        p = PaperPortfolioDB(bot_id=bot_id, cash_balance=1000, savings_ratio=0.5)
        db.add(p)
        db.commit()
    
    portfolio = PaperTradingPortfolio(bot_id)
    
    # 1. Simulate a BUY
    exec_buy = ExecutionResult(
        order_id="buy_1", 
        status="filled", 
        filled_amount=1.0, 
        avg_price=100.0, 
        timestamp=datetime.utcnow()
    )
    await portfolio.process_execution(exec_buy, TradeSide.BUY, "BTC/USDT")
    
    # 2. Simulate a SELL with Profit
    # Buy value: 100. Fee (0.001): 0.1. Total cost: 100.1
    # Sell value: 120. Fee (0.001): 0.12. Net Revenue: 119.88
    # Gross Profit: 120 - 100 = 20. Net PnL: 20 - 0.1 - 0.12 = 19.78
    # Savings (0.5): 19.78 * 0.5 = 9.89
    # Reinvestable addition: 119.88 - 9.89 = 109.99
    
    exec_sell = ExecutionResult(
        order_id="sell_1", 
        status="filled", 
        filled_amount=1.0, 
        avg_price=120.0, 
        timestamp=datetime.utcnow()
    )
    res = await portfolio.process_execution(exec_sell, TradeSide.SELL, "BTC/USDT")
    
    print(f"PnL: {res['pnl']}")
    print(f"Saved Profits: {portfolio.saved_profits}")
    print(f"Cash Balance: {portfolio.cash_balance}")
    
    # Net PnL: (120 - 100.1) - 0.12 = 19.78
    assert abs(res['pnl'] - 19.78) < 0.01
    assert abs(portfolio.saved_profits - 9.89) < 0.01
    assert abs(portfolio.cash_balance - 1009.89) < 0.01
    print("Profit Split Test PASSED")

async def test_dynamic_strategy():
    print("\n--- Testing Dynamic Strategy Take Profit ---")
    strategy = DynamicReinvestStrategy(take_profit_pct=0.1) # 10% TP
    
    # Context with open position at 100
    context = {
        'symbol': 'BTC/USDT',
        'last_price': 111.0, # 11% profit
        'history': [{'close': 100} for _ in range(50)],
        'portfolio': {
            'positions': {'BTC/USDT': {'avg_price': 100.0, 'amount': 1.0}},
            'cash_balance': 1000
        }
    }
    
    signal = await strategy.analyze(context)
    print(f"Signal: {signal.side}")
    assert signal.side == TradeSide.SELL
    assert signal.meta['reason'] == "target_profit_reached"
    print("Dynamic Strategy TP Test PASSED")

async def main():
    try:
        await test_profit_split()
        await test_dynamic_strategy()
    finally:
        pass

if __name__ == "__main__":
    asyncio.run(main())
