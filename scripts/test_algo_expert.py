import asyncio
import pandas as pd
import numpy as np
from apps.engine.algo_expert import AlgoExpertStrategy
from apps.shared.models import TradeSide

def generate_mock_history(size=300, trend='up'):
    history = []
    price = 100.0
    for i in range(size):
        if trend == 'up':
            price += np.random.normal(0.5, 1)
        else:
            price += np.random.normal(-0.5, 1)
        
        history.append({
            'time': i,
            'open': price - 0.5,
            'high': price + 1.0,
            'low': price - 1.0,
            'close': price,
            'volume': 1000 + np.random.normal(100, 10)
        })
    return history

async def test_algo_expert_signals():
    print("--- Testing AlgoExpert Strategy Signals ---")
    strategy = AlgoExpertStrategy()

    # 1. Test BUY scenario (Uptrend + Oversold)
    # We force a dip in an uptrend to trigger RSI < 30
    up_history = generate_mock_history(size=250, trend='up')
    # EMA(200) will be around the average of the last 200 items.
    # We dip the price significantly at the end to lower RSI
    last_price = up_history[-1]['close']
    for i in range(1, 15):
        up_history[-i]['close'] -= 20 # Sharp dip
        up_history[-i]['low'] -= 22
    
    context_buy = {
        'symbol': 'TEST/USDT',
        'last_price': up_history[-1]['close'],
        'history': up_history
    }
    
    signal_buy = await strategy.analyze(context_buy)
    print(f"BUY Test: Mode={signal_buy.side}, RSI={signal_buy.meta.get('rsi'):.2f}, EMA={signal_buy.meta.get('ema_200'):.2f}, VWAP={signal_buy.meta.get('vwap'):.2f}")

    # 2. Test SELL scenario (Downtrend + Overbought)
    down_history = generate_mock_history(size=250, trend='down')
    # Force a spike in a downtrend to trigger RSI > 70
    for i in range(1, 15):
        down_history[-i]['close'] += 20 # Sharp spike
        down_history[-i]['high'] += 22

    context_sell = {
        'symbol': 'TEST/USDT',
        'last_price': down_history[-1]['close'],
        'history': down_history
    }
    
    signal_sell = await strategy.analyze(context_sell)
    print(f"SELL Test: Mode={signal_sell.side}, RSI={signal_sell.meta.get('rsi'):.2f}, EMA={signal_sell.meta.get('ema_200'):.2f}, VWAP={signal_sell.meta.get('vwap'):.2f}")

    # 3. Test HOLD scenario
    hold_history = generate_mock_history(size=250, trend='up')
    context_hold = {
        'symbol': 'TEST/USDT',
        'last_price': hold_history[-1]['close'],
        'history': hold_history
    }
    signal_hold = await strategy.analyze(context_hold)
    print(f"HOLD Test: Mode={signal_hold.side}, RSI={signal_hold.meta.get('rsi'):.2f}")

if __name__ == "__main__":
    asyncio.run(test_algo_expert_signals())
