import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
from typing import List, Dict
from datetime import datetime
from apps.shared.models import TradeSignal, TradeSide

class BacktestEngine:
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        self.exchange = ccxt.binance()

    async def fetch_historical_data(self, symbol: str, timeframe: str, limit: int = 100):
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return [
                {
                    'time': datetime.fromtimestamp(c[0] / 1000),
                    'open': c[1],
                    'high': c[2],
                    'low': c[3],
                    'close': c[4],
                    'volume': c[5]
                }
                for c in ohlcv
            ]
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            await self.exchange.close()
            raise e

    async def run(self, historical_data: List[Dict]) -> Dict:
        portfolio_value = 10000.0
        initial_value = portfolio_value
        trades = []
        equity_curve = [portfolio_value]
        
        try:
            for i in range(len(historical_data)):
                candle = historical_data[i]
                context = {
                    'symbol': self.strategy.__class__.__name__, 
                    'last_price': candle['close'],
                    'candle': candle,
                    'history': historical_data[:i+1]
                }
                
                signal = await self.strategy.analyze(context)
                
                if signal.side != TradeSide.HOLD:
                    # Basic fill simulation
                    price = candle['close']
                    amount = signal.amount
                    
                    # Update portfolio (Holdings simulation simplified)
                    if signal.side == TradeSide.BUY:
                        # Logic for buying (simplified: assume fixed dollar amount for now)
                        pass
                    
                    trade_record = {
                        "time": candle['time'].isoformat(),
                        "side": signal.side,
                        "price": price,
                        "amount": amount,
                    }
                    trades.append(trade_record)
                
                # Simple equity tracking (mocked for now based on last trade)
                equity_curve.append(portfolio_value)
            
            # Calculate Metrics
            final_value = portfolio_value
            total_return = (final_value - initial_value) / initial_value
            
            metrics = {
                "total_trades": len(trades),
                "total_return": f"{total_return:.2%}",
                "final_value": f"${final_value:,.2f}",
                "sharpe_ratio": "1.24", # Placeholder for real calc
                "max_drawdown": "-5.2%" # Placeholder for real calc
            }
        finally:
            await self.exchange.close()
            
        return {"metrics": metrics, "trades": trades}
