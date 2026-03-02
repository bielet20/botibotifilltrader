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
        # Initial portfolio setup
        cash = 10000.0
        initial_value = cash
        position = 0.0  # Current position size (in asset units)
        entry_price = 0.0
        trades = []
        equity_curve = []
        
        try:
            for i in range(len(historical_data)):
                candle = historical_data[i]
                current_price = candle['close']
                
                # Calculate current portfolio value
                portfolio_value = cash + (position * current_price)
                equity_curve.append({
                    'time': candle['time'],
                    'value': portfolio_value
                })
                
                context = {
                    'symbol': self.strategy.__class__.__name__, 
                    'last_price': current_price,
                    'candle': candle,
                    'history': historical_data[:i+1]
                }
                
                signal = await self.strategy.analyze(context)
                
                # Process trading signals
                if signal.side == TradeSide.BUY and position == 0:
                    # Open long position - use 95% of available cash
                    trade_size = cash * 0.95
                    amount = trade_size / current_price
                    
                    position = amount
                    entry_price = current_price
                    cash -= trade_size
                    
                    trade_record = {
                        "time": candle['time'].isoformat(),
                        "side": "buy",
                        "price": current_price,
                        "amount": amount,
                        "value": trade_size
                    }
                    trades.append(trade_record)
                
                elif signal.side == TradeSide.SELL and position > 0:
                    # Close long position
                    trade_value = position * current_price
                    pnl = (current_price - entry_price) * position
                    
                    cash += trade_value
                    
                    trade_record = {
                        "time": candle['time'].isoformat(),
                        "side": "sell",
                        "price": current_price,
                        "amount": position,
                        "value": trade_value,
                        "pnl": pnl
                    }
                    trades.append(trade_record)
                    
                    position = 0.0
                    entry_price = 0.0
            
            # Close any open position at the end
            if position > 0:
                final_price = historical_data[-1]['close']
                trade_value = position * final_price
                pnl = (final_price - entry_price) * position
                cash += trade_value
                
                trades.append({
                    "time": historical_data[-1]['time'].isoformat(),
                    "side": "sell",
                    "price": final_price,
                    "amount": position,
                    "value": trade_value,
                    "pnl": pnl
                })
                position = 0.0
            
            # Calculate final metrics
            final_value = cash
            total_return = (final_value - initial_value) / initial_value
            
            # Calculate realized PnL
            realized_pnl = sum([t.get('pnl', 0) for t in trades if 'pnl' in t])
            
            # Calculate Sharpe Ratio
            equity_values = [e['value'] for e in equity_curve]
            returns = np.diff(equity_values) / equity_values[:-1] if len(equity_values) > 1 else [0]
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
            
            # Calculate Max Drawdown
            peak = equity_values[0]
            max_dd = 0.0
            for value in equity_values:
                if value > peak:
                    peak = value
                dd = (peak - value) / peak
                if dd > max_dd:
                    max_dd = dd
            
            # Win rate
            winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
            total_closed_trades = len([t for t in trades if t['side'] == 'sell'])
            win_rate = (len(winning_trades) / total_closed_trades * 100) if total_closed_trades > 0 else 0.0
            
            metrics = {
                "total_trades": len(trades),
                "closed_trades": total_closed_trades,
                "total_return": f"{total_return:.2%}",
                "realized_pnl": f"${realized_pnl:,.2f}",
                "final_value": f"${final_value:,.2f}",
                "sharpe_ratio": f"{sharpe:.2f}",
                "max_drawdown": f"{max_dd:.2%}",
                "win_rate": f"{win_rate:.1f}%"
            }
            
        finally:
            await self.exchange.close()
            
        return {
            "metrics": metrics, 
            "trades": trades,
            "equity_curve": [{'time': e['time'].isoformat(), 'value': e['value']} for e in equity_curve]
        }
