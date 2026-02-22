import pandas as pd
import numpy as np
from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
from datetime import datetime

class TechnicalProStrategy(BaseStrategy):
    """
    Advanced strategy combining RSI, MACD, and Fibonacci Retracements.
    """
    def __init__(self, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9):
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

    async def analyze(self, context: dict) -> TradeSignal:
        history = context.get('history', [])
        if len(history) < self.macd_slow + self.macd_signal:
            return TradeSignal(symbol=context['symbol'], side=TradeSide.HOLD, amount=0, strategy_id="Technical_Pro_v1")

        df = pd.DataFrame(history)
        
        # 1. RSI Calculation
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        # Evitar división por cero
        loss = loss.replace(0, 1e-9)
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        current_rsi = df['rsi'].iloc[-1]

        # 2. MACD Calculation
        exp1 = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        exp2 = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['signal_line'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()
        
        macd_val = df['macd'].iloc[-1]
        signal_val = df['signal_line'].iloc[-1]
        prev_macd = df['macd'].iloc[-2]
        prev_signal = df['signal_line'].iloc[-2]

        # 3. Fibonacci Retracements (on 100 candle window)
        window = history[-100:]
        high = max(c['high'] for c in window)
        low = min(c['low'] for c in window)
        diff = high - low
        
        fib_levels = {
            '0.382': high - 0.382 * diff,
            '0.5': high - 0.5 * diff,
            '0.618': high - 0.618 * diff
        }
        
        current_price = context['last_price']
        
        # Signal Logic
        side = TradeSide.HOLD
        weight = 0
        
        # Trend Confirmation (MACD Cross)
        if prev_macd < prev_signal and macd_val > signal_val:
            weight += 1 # Bullish Cross
        elif prev_macd > prev_signal and macd_val < signal_val:
            weight -= 1 # Bearish Cross
            
        # Overbought/Oversold (RSI)
        if current_rsi < 30:
            weight += 1
        elif current_rsi > 70:
            weight -= 1
            
        # Fibonacci Level Check (Proximity to support/resistance)
        # If price is near 0.618 (Golden Pocket) and weight is bullish
        if abs(current_price - fib_levels['0.618']) / current_price < 0.005: # Within 0.5%
            weight += 0.5

        if weight >= 1.5:
            side = TradeSide.BUY
        elif weight <= -1.5:
            side = TradeSide.SELL

        return TradeSignal(
            symbol=context['symbol'],
            side=side,
            amount=10.0,
            strategy_id="Technical_Pro_v1",
            meta={
                "rsi": float(current_rsi),
                "macd": float(macd_val),
                "fib_0.618": float(fib_levels['0.618']),
                "weight": weight
            }
        )
