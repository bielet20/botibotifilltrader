import ccxt.async_support as ccxt
import asyncio
import os
from typing import Dict, Any

class MarketDataEngine:
    def __init__(self, exchange_id: str = 'binance'):
        self.exchange_class = getattr(ccxt, exchange_id)
        self.exchange = self.exchange_class()
        
        # Soporte para modo sandbox/testnet si está configurado en el entorno
        if exchange_id == 'hyperliquid':
            use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
            if use_testnet:
                self.exchange.set_sandbox_mode(True)
        
        self.tickers = {}

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            self.tickers[symbol] = ticker
            return ticker
        except Exception as e:
            print(f"Error fetching ticker for {symbol}: {e}")
            return {}
        finally:
            await self.exchange.close()

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> list:
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return [
                {
                    'time': c[0],
                    'open': c[1],
                    'high': c[2],
                    'low': c[3],
                    'close': c[4],
                    'volume': c[5]
                }
                for c in ohlcv
            ]
        except Exception as e:
            print(f"Error fetching OHLCV for {symbol}: {e}")
            return []
        finally:
            await self.exchange.close()

    async def get_latest_price(self, symbol: str) -> float:
        ticker = self.tickers.get(symbol)
        if not ticker:
            ticker = await self.fetch_ticker(symbol)
        return ticker.get('last', 0.0)
