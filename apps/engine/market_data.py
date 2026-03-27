import ccxt.async_support as ccxt
import asyncio
import os
from typing import Dict, Any, Optional

class MarketDataEngine:
    def __init__(self, exchange_id: str = 'binance', use_testnet: Optional[bool] = None):
        self.exchange_id = str(exchange_id or "binance").strip().lower()
        self.exchange_class = getattr(ccxt, self.exchange_id)
        self.exchange = self.exchange_class()
        self._is_closed = False

        # Fallback: si el proveedor principal falla (p. ej. Hyperliquid 502),
        # usar un exchange "estable" sólo para market data.
        self._fallback_exchange_id = os.getenv("MARKET_DATA_FALLBACK_EXCHANGE", "binance").strip().lower()
        self._fallback_exchange = None
        if self.exchange_id == "hyperliquid" and self._fallback_exchange_id and self._fallback_exchange_id != "hyperliquid":
            try:
                self._fallback_exchange = getattr(ccxt, self._fallback_exchange_id)()
            except Exception:
                self._fallback_exchange = None
        
        # Soporte para modo sandbox/testnet si está configurado en el entorno
        if self.exchange_id == 'hyperliquid':
            if use_testnet is None:
                use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
            if use_testnet:
                self.exchange.set_sandbox_mode(True)
        
        self.tickers = {}

    def _fallback_symbol(self, symbol: str) -> str:
        """
        Convierte símbolos Hyperliquid-perp a un spot/perp típico de Binance.
        Ej: BTC/USDC:USDC -> BTC/USDT
        """
        raw = str(symbol or "").strip().upper()
        if not raw:
            return raw
        if raw.endswith(":USDC") and "/USDC" in raw:
            base = raw.split("/")[0]
            return f"{base}/USDT"
        return raw

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            if self._is_closed:
                self.exchange = self.exchange_class()
                self._is_closed = False
            ticker = await self.exchange.fetch_ticker(symbol)
            self.tickers[symbol] = ticker
            return ticker
        except Exception as e:
            print(f"Error fetching ticker for {symbol}: {e}")
            if self._fallback_exchange is not None:
                try:
                    fb_symbol = self._fallback_symbol(symbol)
                    ticker = await self._fallback_exchange.fetch_ticker(fb_symbol)
                    self.tickers[symbol] = ticker
                    return ticker
                except Exception as fb_exc:
                    print(f"Error fetching ticker fallback for {symbol}: {fb_exc}")
            return {}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> list:
        try:
            if self._is_closed:
                self.exchange = self.exchange_class()
                self._is_closed = False
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
            if self._fallback_exchange is not None:
                try:
                    fb_symbol = self._fallback_symbol(symbol)
                    ohlcv = await self._fallback_exchange.fetch_ohlcv(fb_symbol, timeframe, limit=limit)
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
                except Exception as fb_exc:
                    print(f"Error fetching OHLCV fallback for {symbol}: {fb_exc}")
            return []

    async def get_latest_price(self, symbol: str) -> float:
        ticker = self.tickers.get(symbol)
        if not ticker:
            ticker = await self.fetch_ticker(symbol)
        return ticker.get('last', 0.0)

    async def close(self):
        if not self._is_closed:
            await self.exchange.close()
            if self._fallback_exchange is not None:
                try:
                    await self._fallback_exchange.close()
                except Exception:
                    pass
            self._is_closed = True
