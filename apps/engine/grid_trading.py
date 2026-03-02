from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
import asyncio

class GridTradingStrategy(BaseStrategy):
    def __init__(self, upper_limit: float, lower_limit: float, num_grids: int):
        self.upper_limit = upper_limit
        self.lower_limit = lower_limit
        self.num_grids = num_grids
        self.grid_size = (upper_limit - lower_limit) / num_grids
        
        # Calculate grid levels
        self.levels = [lower_limit + i * self.grid_size for i in range(num_grids + 1)]
        self.last_grid_level = None
        print(f"[GridStrategy] Initialized with {num_grids} grids between {lower_limit} and {upper_limit}")
        print(f"[GridStrategy] Levels: {[round(l, 2) for l in self.levels]}")

    async def analyze(self, market_data: dict) -> TradeSignal:
        await asyncio.sleep(0.05)
        
        symbol = market_data.get('symbol', 'BTC/USDT')
        price = market_data.get('last_price')
        if not price:
            return TradeSignal(symbol=symbol, side=TradeSide.HOLD, amount=0, price=0, strategy_id="Grid_v1")

        # Determine current grid level
        current_level_idx = None
        for i, level in enumerate(self.levels):
            if price <= level:
                current_level_idx = i
                break
        
        if current_level_idx is None:
            current_level_idx = len(self.levels) - 1

        side = TradeSide.HOLD
        
        # Grid Crossing Logic
        if self.last_grid_level is not None:
            if current_level_idx < self.last_grid_level:
                # Price dropped to a lower grid level -> BUY
                side = TradeSide.BUY
                print(f"[GridStrategy] Price dropped to level {current_level_idx} ({self.levels[current_level_idx]:.2f}) -> BUY")
            elif current_level_idx > self.last_grid_level:
                # Price rose to a higher grid level -> SELL
                side = TradeSide.SELL
                print(f"[GridStrategy] Price rose to level {current_level_idx} ({self.levels[current_level_idx]:.2f}) -> SELL")

        self.last_grid_level = current_level_idx

        # Calcular cantidad basada en la asignación por rejilla y apalancamiento
        allocation = market_data.get('allocation', 100.0)
        leverage = float(market_data.get('leverage', 1.0))
        
        # PROTECCIÓN: Máximo 30% del buying power por operación
        buying_power = allocation * leverage
        max_position_value = buying_power * 0.30  # Solo 30% del capital por trade
        amount = (max_position_value / price) if side != TradeSide.HOLD else 0
        
        # Verificar si ya tenemos una posición abierta (evitar acumulación)
        current_position = market_data.get('current_position_qty', 0.0)
        if side == TradeSide.BUY and current_position > 0:
            print(f"[GridStrategy] Already have open position ({current_position} BTC), skipping BUY")
            side = TradeSide.HOLD
            amount = 0

        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=amount, 
            price=price,
            strategy_id="Grid_v1",
            meta={
                "upper": self.upper_limit,
                "lower": self.lower_limit,
                "grids": self.num_grids,
                "current_grid": current_level_idx
            }
        )
