import pandas as pd
import numpy as np
from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
from datetime import datetime

class DynamicReinvestStrategy(BaseStrategy):
    """
    Strategy focused on dynamic profit taking and consistent reinvestment.
    - Monitors current open positions for profit targets.
    - Uses EMA/RSI for entry signals.
    - Triggers 'SELL' when profit target is reached (dynamic take profit).
    """
    def __init__(self, take_profit_pct=0.02, ema_period=20, rsi_period=14):
        self.take_profit_pct = take_profit_pct
        self.ema_period = ema_period
        self.rsi_period = rsi_period

    async def analyze(self, context: dict) -> TradeSignal:
        symbol = context.get('symbol', 'BTC/USDT')
        current_price = context.get('last_price', 0.0)
        history = context.get('history', [])
        portfolio = context.get('portfolio', {}) # We'll need the manager to pass this
        
        # 1. Check if we have an open position to TAKE PROFIT
        positions = portfolio.get('positions', {})
        if symbol in positions:
            pos = positions[symbol]
            entry_price = pos['avg_price']
            profit_pct = (current_price - entry_price) / entry_price
            
            if profit_pct >= self.take_profit_pct:
                print(f"[Strategy] Target profit reached: {profit_pct*100:.2f}% >= {self.take_profit_pct*100:.2f}%")
                return TradeSignal(
                    symbol=symbol,
                    side=TradeSide.SELL,
                    amount=pos['amount'],
                    price=current_price,
                    strategy_id="DynamicReinvest_v1",
                    meta={"reason": "target_profit_reached", "profit_pct": profit_pct}
                )

        # 2. Entry Logic (EMA Cross + RSI Oversold)
        if not history or len(history) < self.ema_period:
            return TradeSignal(symbol=symbol, side=TradeSide.HOLD, amount=0, strategy_id="DynamicReinvest_v1")

        df = pd.DataFrame(history)
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean().replace(0, 1e-9)
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        current_ema = df['ema'].iloc[-1]
        current_rsi = df['rsi'].iloc[-1]
        
        side = TradeSide.HOLD
        amount = 0
        
        # Simple Entry: Price > EMA AND RSI < 40
        if current_price > current_ema and current_rsi < 40:
            if symbol not in positions:
                side = TradeSide.BUY
                # Dynamic amount based on reinvestable cash
                cash = portfolio.get('cash_balance', 0)
                amount = (cash * 0.1) / current_price # Use 10% of cash
        
        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=amount,
            price=current_price,
            strategy_id="DynamicReinvest_v1",
            meta={
                "ema": float(current_ema),
                "rsi": float(current_rsi),
                "has_position": symbol in positions
            }
        )
