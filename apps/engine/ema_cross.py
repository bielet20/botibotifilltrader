from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
import asyncio

class EMACrossStrategy(BaseStrategy):
    def __init__(self, fast_ema: int = 9, slow_ema: int = 21, trade_amount: float = 0.002):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trade_amount = max(0.0001, float(trade_amount or 0.002))

    async def analyze(self, market_data: dict) -> TradeSignal:
        # Placeholder for real EMA calculation logic using market_data (OHLCV)
        # For now, it just simulates a signal for demonstration
        
        symbol = market_data.get('symbol', 'BTC/USDT')
        price = market_data.get('last_price', 40000)
        
        # Dummy Crossover logic for safety
        if 'history' in market_data and len(market_data['history']) > 2:
            last_close = market_data['history'][-1]['close']
            prev_close = market_data['history'][-2]['close']
            if last_close > prev_close:
                side = TradeSide.BUY
            else:
                side = TradeSide.SELL
        else:
            side = TradeSide.HOLD

        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=self.trade_amount,
            price=price,
            strategy_id="EMA_Cross_v1",
            meta={"fast": self.fast_ema, "slow": self.slow_ema}
        )
