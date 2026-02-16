from typing import Dict, Optional
from datetime import datetime
from apps.shared.models import ExecutionResult, TradeSide
from apps.shared.database import SessionLocal
from sqlalchemy import Column, String, Float, JSON, DateTime
from apps.shared.database import Base
import uuid

class PaperPortfolioDB(Base):
    """Modelo de base de datos para portfolios de paper trading"""
    __tablename__ = "paper_portfolios"
    
    bot_id = Column(String(100), primary_key=True)
    cash_balance = Column(Float, default=10000.0)
    positions = Column(JSON, default={})
    total_equity = Column(Float, default=10000.0)
    realized_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaperTradingPortfolio:
    """
    Gestiona el portfolio de paper trading: balance, posiciones y P&L.
    """
    
    def __init__(self, bot_id: str, initial_balance: float = 10000.0, fee_rate: float = 0.001):
        """
        Args:
            bot_id: ID único del bot
            initial_balance: Balance inicial en USD
            fee_rate: Tasa de comisión (0.001 = 0.1%)
        """
        self.bot_id = bot_id
        self.fee_rate = fee_rate
        
        # Cargar o crear portfolio desde DB
        with SessionLocal() as db:
            portfolio = db.query(PaperPortfolioDB).filter(PaperPortfolioDB.bot_id == bot_id).first()
            
            if not portfolio:
                # Crear nuevo portfolio
                portfolio = PaperPortfolioDB(
                    bot_id=bot_id,
                    cash_balance=initial_balance,
                    positions={},
                    total_equity=initial_balance,
                    realized_pnl=0.0
                )
                db.add(portfolio)
                db.commit()
                print(f"[Portfolio] Created new paper trading portfolio for {bot_id} with ${initial_balance:,.2f}")
            
            self.cash_balance = portfolio.cash_balance
            self.positions = portfolio.positions or {}
            self.total_equity = portfolio.total_equity
            self.realized_pnl = portfolio.realized_pnl
    
    async def process_execution(self, execution: ExecutionResult, signal_side: TradeSide, symbol: str) -> Dict:
        """
        Procesa una ejecución y actualiza el portfolio.
        
        Args:
            execution: Resultado de la ejecución
            signal_side: Lado de la operación (BUY/SELL)
            symbol: Par de trading (ej: BTC/USDT)
            
        Returns:
            Dict con detalles de la actualización del portfolio
        """
        fill_price = execution.avg_price
        fill_amount = execution.filled_amount
        trade_value = fill_price * fill_amount
        fee = trade_value * self.fee_rate
        
        pnl = 0.0
        
        if signal_side == TradeSide.BUY:
            # Compra: reducir cash, aumentar posición
            total_cost = trade_value + fee
            
            if self.cash_balance < total_cost:
                print(f"[Portfolio] WARNING: Insufficient cash (${self.cash_balance:.2f} < ${total_cost:.2f})")
                return {"success": False, "reason": "insufficient_cash"}
            
            self.cash_balance -= total_cost
            
            # Actualizar posición
            if symbol not in self.positions:
                self.positions[symbol] = {"amount": 0.0, "avg_price": 0.0}
            
            current_amount = self.positions[symbol]["amount"]
            current_avg_price = self.positions[symbol]["avg_price"]
            
            # Calcular nuevo precio promedio
            new_amount = current_amount + fill_amount
            new_avg_price = ((current_amount * current_avg_price) + (fill_amount * fill_price)) / new_amount
            
            self.positions[symbol] = {
                "amount": new_amount,
                "avg_price": new_avg_price
            }
            
            print(f"[Portfolio] BUY {fill_amount} {symbol} @ ${fill_price:,.2f} | Cash: ${self.cash_balance:,.2f}")
        
        elif signal_side == TradeSide.SELL:
            # Venta: aumentar cash, reducir posición
            if symbol not in self.positions or self.positions[symbol]["amount"] < fill_amount:
                print(f"[Portfolio] WARNING: Insufficient position to sell")
                return {"success": False, "reason": "insufficient_position"}
            
            revenue = trade_value - fee
            self.cash_balance += revenue
            
            # Calcular P&L realizado
            avg_cost = self.positions[symbol]["avg_price"]
            pnl = (fill_price - avg_cost) * fill_amount - fee
            self.realized_pnl += pnl
            
            # Reducir posición
            self.positions[symbol]["amount"] -= fill_amount
            
            # Eliminar posición si se cerró completamente
            if self.positions[symbol]["amount"] <= 0.0001:  # Threshold para evitar decimales residuales
                del self.positions[symbol]
            
            print(f"[Portfolio] SELL {fill_amount} {symbol} @ ${fill_price:,.2f} | P&L: ${pnl:,.2f} | Cash: ${self.cash_balance:,.2f}")
        
        # Calcular equity total
        self._update_total_equity()
        
        # Persistir en DB
        self._save_to_db()
        
        return {
            "success": True,
            "cash_balance": self.cash_balance,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "pnl": pnl,
            "fee": fee
        }
    
    def _update_total_equity(self):
        """Calcula el equity total (cash + valor de posiciones al precio actual)"""
        # Nota: En esta versión simplificada, asumimos que el valor de las posiciones
        # se actualiza cuando se procesan nuevas ejecuciones.
        # En una versión más avanzada, se consultarían precios actuales de mercado.
        self.total_equity = self.cash_balance
        # TODO: Agregar valor de posiciones abiertas al precio actual
    
    def _save_to_db(self):
        """Guarda el estado actual del portfolio en la base de datos"""
        with SessionLocal() as db:
            portfolio = db.query(PaperPortfolioDB).filter(PaperPortfolioDB.bot_id == self.bot_id).first()
            if portfolio:
                portfolio.cash_balance = self.cash_balance
                portfolio.positions = self.positions
                portfolio.total_equity = self.total_equity
                portfolio.realized_pnl = self.realized_pnl
                portfolio.updated_at = datetime.utcnow()
                db.commit()
    
    def get_summary(self) -> Dict:
        """Retorna un resumen del portfolio"""
        return {
            "bot_id": self.bot_id,
            "cash_balance": self.cash_balance,
            "positions": self.positions,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl
        }
