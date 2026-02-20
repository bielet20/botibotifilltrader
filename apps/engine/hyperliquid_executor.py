import ccxt.async_support as ccxt
import os
import asyncio
from datetime import datetime
from apps.shared.interfaces import BaseExecutionProvider
from apps.shared.models import TradeSignal, ExecutionResult

class HyperliquidExecutor(BaseExecutionProvider):
    """
    Ejecutor real para Hyperliquid utilizando la librería CCXT.
    Soporta Mainnet y Testnet según la configuración del entorno.
    """
    
    def __init__(self):
        wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
        signing_key = os.getenv("HYPERLIQUID_SIGNING_KEY")
        use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
        
        if not wallet_address or not signing_key:
            print("Warning: Hyperliquid credentials not fully configured in .env")
            
        self.exchange = ccxt.hyperliquid({
            'privateKey': signing_key,
            'walletAddress': wallet_address,
        })
        
        if use_testnet:
            self.exchange.set_sandbox_mode(True)
            
    async def execute(self, signal: TradeSignal) -> ExecutionResult:
        """
        Ejecuta una orden real en Hyperliquid.
        
        Args:
            signal: Señal de trading a ejecutar (BUY/SELL)
            
        Returns:
            ExecutionResult con los detalles de la ejecución real
        """
        try:
            # En Hyperliquid con CCXT, los símbolos suelen ser 'BTC/USDC:USDC' para perps
            # Aseguramos que el símbolo tenga el formato correcto si es necesario
            symbol = signal.symbol
            side = signal.side.value # 'buy' o 'sell'
            amount = signal.amount
            
            print(f"[Hyperliquid] Executing {side} {amount} {symbol}...")
            
            # Hyperliquid en CCXT requiere un precio de referencia para órdenes de mercado
            # para calcular el slippage máximo permitido (por defecto 5%).
            order_params = {}
            if signal.price:
                # Si la señal ya trae precio, lo usamos de referencia
                price = signal.price
            else:
                # Si no, tenemos que obtener el precio actual del mercado
                ticker = await self.exchange.fetch_ticker(symbol)
                price = ticker['last']
            
            # Crear la orden de mercado
            # Nota: En CCXT.hyperliquid, para órdenes market, el argumento 'price' 
            # se usa para calcular el slippage.
            order = await self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount,
                price=price
            )
            
            # Extraer info del resultado de CCXT
            # Nota: Hyperliquid a veces devuelve None en algunos campos
            result = ExecutionResult(
                order_id=str(order.get('id') or 'unknown'),
                status=str(order.get('status') or 'closed'),
                filled_amount=float(order.get('filled') or order.get('amount') or amount),
                avg_price=float(order.get('average') or order.get('price') or price),
                timestamp=datetime.utcnow()
            )
            
            print(f"[Hyperliquid] Order {result.order_id} {result.status} at ${result.avg_price:,.2f}")
            return result
            
        except Exception as e:
            print(f"Error executing Hyperliquid order: {e}")
            # Devolver un resultado fallido
            return ExecutionResult(
                order_id="error",
                status="failed",
                filled_amount=0,
                avg_price=0,
                timestamp=datetime.utcnow()
            )
        finally:
            # Cerramos la sesión del exchange para liberar recursos
            await self.exchange.close()
