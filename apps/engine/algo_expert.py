import pandas as pd
import numpy as np
from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
import asyncio

class AlgoExpertStrategy(BaseStrategy):
    """
    Efficiency-focused strategy combining EMA, RSI, ATR, and VWAP.
    - EMA(200): Trend filter.
    - RSI(14): Reversal/Correction signal.
    - ATR(14): Dynamic Stop Loss.
    - VWAP: Institutional 'fair price' filter.
    """
    def __init__(self, ema_period=200, rsi_period=14, atr_period=14):
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period

    async def analyze(self, context: dict) -> TradeSignal:
        history = context.get('history', [])
        symbol = context.get('symbol', 'BTC/USDT')
        current_price = context.get('last_price', 0.0)
        
        # Need enough data for EMA calculation and others
        if not history or len(history) < self.ema_period:
            return TradeSignal(
                symbol=symbol, 
                side=TradeSide.HOLD, 
                amount=0, 
                strategy_id="AlgoExpert_v1",
                meta={"reason": f"Insufficient data (need {self.ema_period})"}
            )

        df = pd.DataFrame(history)
        
        # Ensure price and volume are floats
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        # 1. EMA Calculation
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        current_ema = df['ema'].iloc[-1]

        # 2. RSI Calculation
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        # Avoid division by zero
        loss = loss.replace(0, 1e-9)
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        current_rsi = df['rsi'].iloc[-1]

        # 3. ATR Calculation
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=self.atr_period).mean()
        current_atr = df['atr'].iloc[-1]

        # 4. VWAP Calculation (Simplistic rolling VWAP for the current window)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tp_vol'] = df['tp'] * df['volume']
        df['cum_tp_vol'] = df['tp_vol'].cumsum()
        df['cum_vol'] = df['volume'].cumsum()
        # Avoid division by zero
        df['cum_vol'] = df['cum_vol'].replace(0, 1e-9)
        df['vwap'] = df['cum_tp_vol'] / df['cum_vol']
        current_vwap = df['vwap'].iloc[-1]

        # Signal Logic
        side = TradeSide.HOLD
        stop_loss = 0.0
        
        # BUY: Price > EMA(200) AND RSI < 30 (oversold in uptrend) AND Price > VWAP
        if current_price > current_ema and current_rsi < 30 and current_price > current_vwap:
            side = TradeSide.BUY
            stop_loss = current_price - (2 * current_atr)
        
        # SELL: Price < EMA(200) AND RSI > 70 (overbought in downtrend) AND Price < VWAP
        elif current_price < current_ema and current_rsi > 70 and current_price < current_vwap:
            side = TradeSide.SELL
            stop_loss = current_price + (2 * current_atr)

        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=0.1, 
            price=current_price,
            strategy_id="AlgoExpert_v1",
            meta={
                "ema_200": float(current_ema),
                "rsi": float(current_rsi),
                "atr": float(current_atr),
                "vwap": float(current_vwap),
                "stop_loss": float(stop_loss)
            }
        )
