import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from apps.engine.grid_trading import GridTradingStrategy
from apps.shared.models import TradeSide

async def test_grid():
    # Setup: 60k to 66k, 6 grids (1k each)
    # Levels: 60, 61, 62, 63, 64, 65, 66
    strategy = GridTradingStrategy(upper_limit=66000.0, lower_limit=60000.0, num_grids=6)
    
    print("\n--- Starting Grid Strategy Test ---")
    
    # 1. Price starts at 63.5k (Level 4: between 63 and 64)
    price = 63500
    signal = await strategy.analyze({'last_price': price, 'symbol': 'BTC/USDT'})
    print(f"Price: {price} | Signal: {signal.side}") # Expected: HOLD (first run)
    
    # 2. Price drops to 62.5k (Level 3: between 62 and 63)
    price = 62500
    signal = await strategy.analyze({'last_price': price, 'symbol': 'BTC/USDT'})
    print(f"Price: {price} | Signal: {signal.side}") # Expected: BUY
    
    # 3. Price drops further to 61.5k (Level 2)
    price = 61500
    signal = await strategy.analyze({'last_price': price, 'symbol': 'BTC/USDT'})
    print(f"Price: {price} | Signal: {signal.side}") # Expected: BUY
    
    # 4. Price recovers to 62.5k (Level 3)
    price = 62500
    signal = await strategy.analyze({'last_price': price, 'symbol': 'BTC/USDT'})
    print(f"Price: {price} | Signal: {signal.side}") # Expected: SELL
    
    # 5. Price goes up to 64.5k (Level 5)
    price = 64500
    signal = await strategy.analyze({'last_price': price, 'symbol': 'BTC/USDT'})
    print(f"Price: {price} | Signal: {signal.side}") # Expected: SELL

if __name__ == "__main__":
    asyncio.run(test_grid())
