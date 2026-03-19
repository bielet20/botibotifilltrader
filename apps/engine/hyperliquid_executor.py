import ccxt.async_support as ccxt
import os
import asyncio
from datetime import datetime, timezone
from typing import Optional
from apps.shared.interfaces import BaseExecutionProvider
from apps.shared.models import TradeSignal, ExecutionResult
from apps.shared.hyperliquid_credentials import get_hyperliquid_wallet_and_key

class HyperliquidExecutor(BaseExecutionProvider):
    """
    Ejecutor real para Hyperliquid utilizando la librería CCXT.
    Soporta Mainnet y Testnet según la configuración del entorno.
    """
    
    def __init__(self, use_testnet: Optional[bool] = None):
        wallet_address, signing_key = get_hyperliquid_wallet_and_key()
        if use_testnet is None:
            use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
        self._wallet_address = wallet_address
        self.is_configured = self._is_valid_wallet(wallet_address) and self._is_valid_private_key(signing_key)
        
        if not self.is_configured:
            print("Warning: Hyperliquid credentials missing or invalid (.env o almacén cifrado)")
            
        self.exchange = ccxt.hyperliquid({
            'privateKey': signing_key or "",
            'walletAddress': wallet_address or "",
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

    @staticmethod
    def _extract_side_qty(position: dict) -> tuple[str, float]:
        """Infer canonical side/qty from heterogeneous CCXT Hyperliquid payloads."""
        info = position.get("info") or {}
        nested_pos = info.get("position") if isinstance(info.get("position"), dict) else {}

        raw_side = str(position.get("side") or nested_pos.get("side") or info.get("side") or "").strip().lower()

        # Signed fields first (most reliable when present).
        signed_size = None
        for candidate in (
            nested_pos.get("szi"),
            info.get("szi"),
            info.get("size"),
            position.get("contracts"),
        ):
            try:
                if candidate is not None and str(candidate).strip() != "":
                    signed_size = float(candidate)
                    break
            except Exception:
                continue

        if signed_size is None:
            return "", 0.0

        qty = abs(float(signed_size))
        if qty <= 0:
            return "", 0.0

        # Explicit side (if coherent) wins; sign is fallback.
        if raw_side in {"long", "buy"}:
            return "long", qty
        if raw_side in {"short", "sell"}:
            return "short", qty

        return ("long", qty) if signed_size > 0 else ("short", qty)

    async def _fetch_symbol_position(self, symbol: str) -> tuple[str, float]:
        """Return current live position side and size for symbol as (side, qty)."""
        try:
            if not self.exchange.markets:
                await self.exchange.load_markets()
            wallet_address = self._wallet_address or os.getenv("HYPERLIQUID_WALLET_ADDRESS") or self.exchange.walletAddress
            params = {"user": wallet_address} if wallet_address else {}
            positions = await self.exchange.fetch_positions(params=params)
            target = self._normalize_symbol(symbol)
            for p in positions or []:
                sym = self._normalize_symbol(str(p.get("symbol") or ""))
                if sym != target:
                    continue
                side, qty = self._extract_side_qty(p)
                if qty > 0:
                    return side, qty
            return "", 0.0
        except Exception:
            return "", 0.0
            
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
                    timestamp=datetime.now(timezone.utc)
                )

            # En Hyperliquid con CCXT, los símbolos suelen ser 'BTC/USDC:USDC' para perps
            # Aseguramos que el símbolo tenga el formato correcto si es necesario
            symbol = self._normalize_symbol(signal.symbol)
            side = signal.side.value # 'buy' o 'sell'
            amount = signal.amount
            signal_meta = dict(signal.meta or {})
            reduce_only_intent = bool(
                signal_meta.get("reduce_only")
                or signal_meta.get("pair_action") == "close"
                or signal_meta.get("close_reason")
            )
            
            print(f"[Hyperliquid] Executing {side} {amount} {symbol}...")
            
            # Hyperliquid en CCXT requiere un precio de referencia para órdenes de mercado
            # para calcular el slippage máximo permitido (por defecto 5%).
            order_params = {}
            price = signal.price

            if reduce_only_intent:
                live_side, live_qty = await self._fetch_symbol_position(symbol)
                expected_live_side = "long" if side == "sell" else "short"
                if live_qty <= 0 or live_side != expected_live_side:
                    print(
                        f"[Hyperliquid] Skip close: no matching live position for {symbol} "
                        f"(expected={expected_live_side}, got={live_side}:{live_qty})"
                    )
                    return ExecutionResult(
                        order_id="no_position",
                        status="failed",
                        filled_amount=0,
                        avg_price=0,
                        timestamp=datetime.now(timezone.utc),
                    )
                amount = min(float(amount), float(live_qty))
                order_params.update({"reduceOnly": True, "timeInForce": "Ioc"})

            if not price or float(price) <= 0:
                # Hyperliquid market orders in CCXT still need a reference price.
                ticker = await self.exchange.fetch_ticker(symbol)
                price = float(ticker.get('last') or ticker.get('close') or ticker.get('bid') or 0)

            if price <= 0:
                return ExecutionResult(
                    order_id="no_price",
                    status="failed",
                    filled_amount=0,
                    avg_price=0,
                    timestamp=datetime.now(timezone.utc),
                )
            
            # Crear la orden de mercado
            # Nota: En CCXT.hyperliquid, para órdenes market, el argumento 'price' 
            # se usa para calcular el slippage.
            order = await self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount,
                price=price,
                params=order_params,
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
                timestamp=datetime.now(timezone.utc)
            )
            
            print(f"[Hyperliquid] Order {result.order_id} {result.status} at ${result.avg_price:,.2f}")
            
            # PROTECCIÓN: Colocar stop loss automático después de abrir posición
            if (not reduce_only_intent) and side == 'buy' and result.status in ['closed', 'filled'] and result.filled_amount > 0:
                await self._place_stop_loss(
                    symbol=symbol,
                    side='sell',
                    amount=result.filled_amount,
                    entry_price=result.avg_price,
                    stop_loss_pct=0.05  # 5% stop loss por defecto
                )
            elif (not reduce_only_intent) and side == 'sell' and result.status in ['closed', 'filled'] and result.filled_amount > 0:
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
                timestamp=datetime.now(timezone.utc)
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

    async def fetch_active_positions(self) -> list | None:
        """
        Obtiene las posiciones abiertas actuales en Hyperliquid.
        """
        try:
            positions = []
            for attempt in range(1, 4):
                # Hyperliquid en CCXT usa fetch_positions pero a veces hay que asegurarse de los mercados cargados
                if not self.exchange.markets:
                    await self.exchange.load_markets()

                wallet_address = self._wallet_address or os.getenv("HYPERLIQUID_WALLET_ADDRESS") or self.exchange.walletAddress
                params = {}
                if wallet_address:
                    params["user"] = wallet_address

                try:
                    positions = await self.exchange.fetch_positions(params=params)
                    print(f"[Hyperliquid] Found {len(positions)} raw position records.")
                    break
                except Exception as e:
                    msg = str(e)
                    retriable = ("429" in msg) or ("RateLimitExceeded" in msg)
                    if retriable and attempt < 3:
                        await asyncio.sleep(1.0 * (2 ** (attempt - 1)))
                        continue
                    raise
            
            # Filtrar solo las que tienen cantidad > 0
            active = []
            for p in positions:
                side, qty = self._extract_side_qty(p)
                if qty > 0 and side:
                    active.append({
                        'symbol': p.get('symbol'),
                        'side': side,
                        'quantity': qty,
                        'leverage': float(p.get('leverage', 1.0) or 1.0),
                        'entry_price': float(p.get('entryPrice', 0) or 0),
                        'current_price': float(p.get('markPrice', 0) or 0),
                        'unrealized_pnl': float(p.get('unrealizedPnl', 0) or 0)
                    })
            
            print(f"[Hyperliquid] {len(active)} active positions after filtering.")
            return active
        except Exception as e:
            print(f"Error fetching Hyperliquid positions: {e}")
            return None
        finally:
            await self.exchange.close()

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            pass
