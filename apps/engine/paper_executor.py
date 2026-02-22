from datetime import datetime
from apps.shared.interfaces import BaseExecutionProvider
from apps.shared.models import TradeSignal, ExecutionResult, TradeSide
import uuid

class PaperTradingExecutor(BaseExecutionProvider):
    """
    Simula la ejecución de órdenes en modo paper trading.
    Usa precios reales de mercado pero no ejecuta operaciones reales.
    """
    
    def __init__(self, fee_rate: float = 0.001):
        """
        Args:
            fee_rate: Tasa de comisión simulada (0.001 = 0.1%, similar a Binance)
        """
        self.fee_rate = fee_rate
    
    async def execute(self, signal: TradeSignal) -> ExecutionResult:
        """
        Simula la ejecución de una orden al precio actual de mercado.
        
        Args:
            signal: Señal de trading a ejecutar
            
        Returns:
            ExecutionResult con detalles de la ejecución simulada
        """
        # Simular fill instantáneo al precio de la señal
        fill_price = signal.price
        fill_amount = signal.amount
        
        # Calcular fee basado en el valor de la operación
        trade_value = fill_price * fill_amount
        fee = trade_value * self.fee_rate
        
        # Generar ID único para la orden
        order_id = f"paper_{uuid.uuid4().hex[:8]}"
        
        # Crear resultado de ejecución
        result = ExecutionResult(
            order_id=order_id,
            status="filled",
            filled_amount=fill_amount,
            avg_price=fill_price,
            timestamp=datetime.utcnow()
        )
        
        print(f"[PaperTrading] Executed {signal.side} {fill_amount} {signal.symbol} @ ${fill_price:,.2f} (Fee: ${fee:.2f})")
        
        return result
    async def fetch_active_positions(self) -> list:
        """
        Simula el fetch de posiciones leyendo de la base de datos (PositionDB).
        """
        from apps.shared.database import SessionLocal
        from apps.shared.models import PositionDB
        
        try:
            with SessionLocal() as db:
                open_pos = db.query(PositionDB).filter(PositionDB.is_open == True).all()
                return [
                    {
                        'symbol': p.symbol,
                        'side': p.side,
                        'quantity': p.quantity,
                        'entry_price': p.entry_price,
                        'current_price': p.current_price,
                        'unrealized_pnl': p.unrealized_pnl,
                        'bot_id': p.bot_id
                    }
                    for p in open_pos
                ]
        except Exception as e:
            print(f"Error fetching paper positions: {e}")
            return []
