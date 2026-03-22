from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide
import asyncio

class EMACrossStrategy(BaseStrategy):
    def __init__(
        self,
        fast_ema: int = 9,
        slow_ema: int = 21,
        trade_amount: float = 0.002,
        min_spread_pct: float = 0.0004,
        min_slope_pct: float = 0.00015,
    ):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trade_amount = max(0.0001, float(trade_amount or 0.002))
        self.min_spread_pct = max(0.0, float(min_spread_pct or 0.0))
        self.min_slope_pct = max(0.0, float(min_slope_pct or 0.0))

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2.0 / (max(1, int(period)) + 1.0)
        out = []
        ema_val = float(values[0])
        for v in values:
            ema_val = alpha * float(v) + (1.0 - alpha) * ema_val
            out.append(ema_val)
        return out

    async def analyze(self, market_data: dict) -> TradeSignal:
        # Keep loop cooperative while doing CPU-light analysis.
        await asyncio.sleep(0)

        symbol = market_data.get('symbol', 'BTC/USDT')
        price = market_data.get('last_price', 40000)
        history = market_data.get('history') or []

        min_bars = max(self.fast_ema, self.slow_ema) + 3
        if len(history) < min_bars:
            side = TradeSide.HOLD
        else:
            closes = []
            for row in history:
                try:
                    closes.append(float(row.get('close')))
                except Exception:
                    pass

            if len(closes) < min_bars:
                side = TradeSide.HOLD
            else:
                fast = self._ema(closes, self.fast_ema)
                slow = self._ema(closes, self.slow_ema)
                fast_prev, fast_now = fast[-2], fast[-1]
                slow_prev, slow_now = slow[-2], slow[-1]

                spread_pct = abs(fast_now - slow_now) / max(abs(slow_now), 1e-12)
                fast_slope_pct = abs(fast_now - fast_prev) / max(abs(fast_prev), 1e-12)

                crossed_up = fast_prev <= slow_prev and fast_now > slow_now
                crossed_down = fast_prev >= slow_prev and fast_now < slow_now
                quality_ok = spread_pct >= self.min_spread_pct and fast_slope_pct >= self.min_slope_pct

                if crossed_up and quality_ok:
                    side = TradeSide.BUY
                elif crossed_down and quality_ok:
                    side = TradeSide.SELL
                else:
                    side = TradeSide.HOLD

        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=self.trade_amount,
            price=price,
            strategy_id="EMA_Cross_v1",
            meta={
                "fast": self.fast_ema,
                "slow": self.slow_ema,
                "ema_min_spread_pct": self.min_spread_pct,
                "ema_min_slope_pct": self.min_slope_pct,
            },
        )
