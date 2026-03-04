import ccxt.async_support as ccxt
import os
import asyncio
from datetime import datetime
from typing import Optional
from apps.shared.interfaces import BaseExecutionProvider
from apps.shared.models import TradeSignal, ExecutionResult

class HyperliquidExecutor(BaseExecutionProvider):
    """
    Ejecutor real para Hyperliquid utilizando la librería CCXT.
    Soporta Mainnet y Testnet según la configuración del entorno.
    """
    
    def __init__(self, use_testnet: Optional[bool] = None):
        wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
        signing_key = os.getenv("HYPERLIQUID_SIGNING_KEY")
        if use_testnet is None:
            use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
        self.is_configured = self._is_valid_wallet(wallet_address) and self._is_valid_private_key(signing_key)
        
        if not self.is_configured:
            print("Warning: Hyperliquid credentials missing or invalid in .env (wallet/private key format)")
            
        self.exchange = ccxt.hyperliquid({
            'privateKey': signing_key,
            'walletAddress': wallet_address,
        })
        
        if use_testnet:
            self.exchange.set_sandbox_mode(True)

    @staticmethod
    def _is_valid_wallet(wallet: Optional[str]) -> bool:
        if not wallet:
            return False
        value = wallet.strip()
        return value.startswith("0x") and len(value) == 42

    @staticmethod
    def _is_valid_private_key(private_key: Optional[str]) -> bool:
        if not private_key:
            return False
        value = private_key.strip()
        if "tu_nueva_clave_de_agente_aqui" in value.lower():
            return False
        if not value.startswith("0x") or len(value) != 66:
            return False
        hex_part = value[2:]
        return all(ch in "0123456789abcdefABCDEF" for ch in hex_part)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        if not symbol:
            return "BTC/USDC:USDC"

        normalized = symbol.strip().upper()
        if normalized.endswith(":USDC") and "/USDC" in normalized:
            return normalized

        if "/USDT" in normalized:
            base = normalized.split('/')[0]
            return f"{base}/USDC:USDC"

        if "/USDC" in normalized and not normalized.endswith(":USDC"):
            base = normalized.split('/')[0]
            return f"{base}/USDC:USDC"

        if "/" not in normalized:
            return f"{normalized}/USDC:USDC"

        base = normalized.split('/')[0]
        return f"{base}/USDC:USDC"

    def _normalize_symbol(self, symbol: str) -> str:
        return self.normalize_symbol(symbol)
            
    async def execute(self, signal: TradeSignal) -> ExecutionResult:
        """
        Ejecuta una orden real en Hyperliquid.
        
        Args:
            signal: Señal de trading a ejecutar (BUY/SELL)
            
        Returns:
            ExecutionResult con los detalles de la ejecución real
        """
        try:
            if not self.is_configured:
                return ExecutionResult(
                    order_id="error",
                    status="failed",
                    filled_amount=0,
                    avg_price=0,
                    timestamp=datetime.utcnow()
                )

            # En Hyperliquid con CCXT, los símbolos suelen ser 'BTC/USDC:USDC' para perps
            # Aseguramos que el símbolo tenga el formato correcto si es necesario
            symbol = self._normalize_symbol(signal.symbol)
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

            fee_cost = 0.0
            if isinstance(order.get('fee'), dict):
                fee_cost = float(order.get('fee', {}).get('cost') or 0.0)
            elif isinstance(order.get('fees'), list):
                fee_cost = float(sum((f or {}).get('cost', 0.0) for f in order.get('fees', [])))
            
            # Extraer info del resultado de CCXT
            # Nota: Hyperliquid a veces devuelve None en algunos campos
            result = ExecutionResult(
                order_id=str(order.get('id') or 'unknown'),
                status=str(order.get('status') or 'closed'),
                filled_amount=float(order.get('filled') or order.get('amount') or amount),
                avg_price=float(order.get('average') or order.get('price') or price),
                fee=fee_cost,
                timestamp=datetime.utcnow()
            )
            
            print(f"[Hyperliquid] Order {result.order_id} {result.status} at ${result.avg_price:,.2f}")
            
            # PROTECCIÓN: Colocar stop loss automático después de abrir posición
            if side == 'buy' and result.status in ['closed', 'filled'] and result.filled_amount > 0:
                await self._place_stop_loss(
                    symbol=symbol,
                    side='sell',
                    amount=result.filled_amount,
                    entry_price=result.avg_price,
                    stop_loss_pct=0.05  # 5% stop loss por defecto
                )
            elif side == 'sell' and result.status in ['closed', 'filled'] and result.filled_amount > 0:
                # Si es un short, el stop loss sería comprar
                await self._place_stop_loss(
                    symbol=symbol,
                    side='buy',
                    amount=result.filled_amount,
                    entry_price=result.avg_price,
                    stop_loss_pct=0.05
                )
            
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

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Configura el apalancamiento para un símbolo específico.
        """
        try:
            if not self.is_configured:
                return False
            
            normalized_symbol = self._normalize_symbol(symbol)
            print(f"[Hyperliquid] Setting leverage for {normalized_symbol} to {leverage}x...")
            
            # CCXT method for setting leverage
            await self.exchange.set_leverage(int(leverage), normalized_symbol)
            return True
        except Exception as e:
            print(f"Error setting leverage on Hyperliquid: {e}")
            return False

    async def _place_stop_loss(self, symbol: str, side: str, amount: float, entry_price: float, stop_loss_pct: float = 0.05) -> None:
        """
        Coloca una orden stop loss nativa en Hyperliquid.
        
        Args:
            symbol: Símbolo normalizado (ej: BTC/USDC:USDC)
            side: 'sell' para longs, 'buy' para shorts
            amount: Cantidad a cerrar
            entry_price: Precio de entrada de la posición
            stop_loss_pct: Porcentaje de pérdida permitido (default 5%)
        """
        try:
            # Calcular el precio de stop loss
            if side.lower() == 'sell':
                # Para posiciones long: stop loss por debajo del precio de entrada
                stop_price = entry_price * (1 - stop_loss_pct)
            else:
                # Para posiciones short: stop loss por encima del precio de entrada
                stop_price = entry_price * (1 + stop_loss_pct)
            
            print(f"[Hyperliquid] Placing stop loss: {side} {amount} at ${stop_price:,.2f} (entry ${entry_price:,.2f}, -{stop_loss_pct*100}%)")
            
            # Crear orden stop market
            stop_order = await self.exchange.create_order(
                symbol=symbol,
                type='stop_market',
                side=side,
                amount=amount,
                params={
                    'stopPrice': stop_price,
                    'triggerPrice': stop_price
                }
            )
            
            print(f"[Hyperliquid] Stop loss order placed: {stop_order.get('id', 'unknown')}")
            
        except Exception as e:
            print(f"[Hyperliquid] Error placing stop loss: {e}")

    async def fetch_active_positions(self) -> list:
        """
        Obtiene las posiciones abiertas actuales en Hyperliquid.
        """
        try:
            # Hyperliquid en CCXT usa fetch_positions pero a veces hay que asegurarse de los mercados cargados
            if not self.exchange.markets:
                await self.exchange.load_markets()
            
            wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS") or self.exchange.walletAddress
            params = {}
            if wallet_address:
                params["user"] = wallet_address

            positions = await self.exchange.fetch_positions(params=params)
            print(f"[Hyperliquid] Found {len(positions)} raw position records.")
            
            # Filtrar solo las que tienen cantidad > 0
            active = []
            for p in positions:
                # CCXT suele normalizar la info de posiciones
                # En Hyperliquid CCXT 'contracts' o 'info.size'
                size = float(p.get('contracts', 0) or p.get('info', {}).get('size', 0) or 0)
                if size != 0:
                    active.append({
                        'symbol': p.get('symbol'),
                        'side': 'long' if size > 0 else 'short',
                        'quantity': abs(size),
                        'leverage': float(p.get('leverage', 1.0) or 1.0),
                        'entry_price': float(p.get('entryPrice', 0) or 0),
                        'current_price': float(p.get('markPrice', 0) or 0),
                        'unrealized_pnl': float(p.get('unrealizedPnl', 0) or 0)
                    })
            
            print(f"[Hyperliquid] {len(active)} active positions after filtering.")
            return active
        except Exception as e:
            print(f"Error fetching Hyperliquid positions: {e}")
            return []
        finally:
            await self.exchange.close()

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            pass
