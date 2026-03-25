from typing import Dict, Optional
from datetime import datetime
from apps.shared.models import ExecutionResult, TradeSide, PositionDB
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
    saved_profits = Column(Float, default=0.0) # Profits stored in the 'vault'
    savings_ratio = Column(Float, default=0.2) # 20% to savings by default
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
            self.positions = self._normalize_positions(portfolio.positions or {})
            self.total_equity = portfolio.total_equity
            self.realized_pnl = portfolio.realized_pnl
            self.saved_profits = portfolio.saved_profits or 0.0
            self.savings_ratio = portfolio.savings_ratio or 0.2

            # Mantener compatibilidad: el resto del sistema (UI/guards/position sync)
            # lee `trading.db.positions`, así que sincronizamos las posiciones abiertas
            # actuales del portfolio paper al inicializar.
            self._sync_positions_to_position_db()

    def _sync_positions_to_position_db(self) -> None:
        with SessionLocal() as db:
            open_symbols = set(self.positions.keys())

            # 1) Upsert de posiciones abiertas según PaperTradingPortfolio
            for symbol, payload in (self.positions or {}).items():
                amount = float(payload.get("amount") or 0.0)
                if amount <= 0:
                    continue

                entry_price = float(payload.get("avg_price") or 0.0)
                side = str(payload.get("side") or "long").lower()
                mark_price = float(payload.get("mark_price") or entry_price or 0.0)

                if entry_price <= 0:
                    continue

                unrealized_pnl = (
                    (mark_price - entry_price) * amount
                    if side != "short"
                    else (entry_price - mark_price) * amount
                )

                existing_pos = db.query(PositionDB).filter(
                    PositionDB.bot_id == self.bot_id,
                    PositionDB.symbol == symbol,
                ).first()

                if existing_pos:
                    existing_pos.side = side
                    existing_pos.entry_price = entry_price
                    existing_pos.quantity = amount
                    existing_pos.current_price = mark_price
                    existing_pos.unrealized_pnl = unrealized_pnl
                    existing_pos.is_open = True
                    existing_pos.updated_at = datetime.utcnow()
                else:
                    new_pos = PositionDB(
                        bot_id=self.bot_id,
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        quantity=amount,
                        leverage=1.0,
                        current_price=mark_price,
                        unrealized_pnl=unrealized_pnl,
                        fee_paid=0.0,
                        is_open=True,
                        meta={"source": "paper_portfolio_init"},
                    )
                    db.add(new_pos)

            # 2) Cerrar posiciones abiertas en PositionDB que ya no existan en el portfolio
            stale_open = db.query(PositionDB).filter(
                PositionDB.bot_id == self.bot_id,
                PositionDB.is_open == True,
            ).all()
            for pos in stale_open:
                if pos.symbol not in open_symbols:
                    pos.is_open = False
                    pos.quantity = 0.0
                    pos.updated_at = datetime.utcnow()

            db.commit()
    
    def _normalize_positions(self, positions: Dict) -> Dict:
        normalized = {}
        for symbol, payload in (positions or {}).items():
            data = dict(payload or {})
            amount = float(data.get("amount") or 0.0)
            if amount <= 0:
                continue

            avg_price = float(data.get("avg_price") or 0.0)
            side = str(data.get("side") or "long").lower()
            if side not in {"long", "short"}:
                side = "long"

            mark_price = float(data.get("mark_price") or avg_price or 0.0)
            normalized[symbol] = {
                "amount": amount,
                "avg_price": avg_price,
                "side": side,
                "mark_price": mark_price,
            }
        return normalized

    async def process_execution(self, execution: ExecutionResult, signal_side: TradeSide, symbol: str, allow_short: bool = False) -> Dict:
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
        
        position = dict(self.positions.get(symbol) or {})
        current_amount = float(position.get("amount") or 0.0)
        current_avg_price = float(position.get("avg_price") or 0.0)
        current_side = str(position.get("side") or "long").lower()

        if signal_side == TradeSide.BUY:
            if current_amount > 0 and current_side == "short":
                if fill_amount > current_amount + 1e-9:
                    return {"success": False, "reason": "cover_amount_exceeds_short_position"}

                total_cost = trade_value + fee
                if self.cash_balance < total_cost:
                    print(f"[Portfolio] WARNING: Insufficient cash (${self.cash_balance:.2f} < ${total_cost:.2f})")
                    return {"success": False, "reason": "insufficient_cash"}

                self.cash_balance -= total_cost
                pnl = (current_avg_price - fill_price) * fill_amount - fee
                self.realized_pnl += pnl

                remaining = current_amount - fill_amount
                if remaining <= 0.0001:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = {
                        "amount": remaining,
                        "avg_price": current_avg_price,
                        "side": "short",
                        "mark_price": fill_price,
                    }

                print(f"[Portfolio] BUY-COVER {fill_amount} {symbol} @ ${fill_price:,.2f} | P&L: ${pnl:,.2f} | Cash: ${self.cash_balance:,.2f}")
            else:
                total_cost = trade_value + fee
                if self.cash_balance < total_cost:
                    print(f"[Portfolio] WARNING: Insufficient cash (${self.cash_balance:.2f} < ${total_cost:.2f})")
                    return {"success": False, "reason": "insufficient_cash"}

                self.cash_balance -= total_cost
                if current_amount > 0 and current_side == "long":
                    new_amount = current_amount + fill_amount
                    new_avg_price = ((current_amount * current_avg_price) + total_cost) / max(new_amount, 1e-12)
                else:
                    new_amount = fill_amount
                    new_avg_price = total_cost / max(new_amount, 1e-12)

                self.positions[symbol] = {
                    "amount": new_amount,
                    "avg_price": new_avg_price,
                    "side": "long",
                    "mark_price": fill_price,
                }

                print(f"[Portfolio] BUY {fill_amount} {symbol} @ ${fill_price:,.2f} | Cash: ${self.cash_balance:,.2f}")

        elif signal_side == TradeSide.SELL:
            if current_amount > 0 and current_side == "long":
                if fill_amount > current_amount + 1e-9:
                    if not allow_short:
                        print(f"[Portfolio] WARNING: Insufficient position to sell")
                        return {"success": False, "reason": "insufficient_position"}
                    return {"success": False, "reason": "sell_amount_exceeds_long_position"}

                pnl = (fill_price - current_avg_price) * fill_amount - fee
                revenue = trade_value - fee

                if pnl > 0:
                    to_save = pnl * self.savings_ratio
                    to_reinvest = pnl - to_save
                    self.saved_profits += to_save
                    self.cash_balance += (revenue - to_save)
                    print(f"[Portfolio] Profit split: Save ${to_save:.2f} | Reinvest ${to_reinvest:.2f}")
                else:
                    self.cash_balance += revenue

                self.realized_pnl += pnl
                remaining = current_amount - fill_amount
                if remaining <= 0.0001:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = {
                        "amount": remaining,
                        "avg_price": current_avg_price,
                        "side": "long",
                        "mark_price": fill_price,
                    }

                print(f"[Portfolio] SELL {fill_amount} {symbol} @ ${fill_price:,.2f} | P&L: ${pnl:,.2f} | Cash: ${self.cash_balance:,.2f}")
            else:
                if not allow_short:
                    print(f"[Portfolio] WARNING: Insufficient position to sell")
                    return {"success": False, "reason": "insufficient_position"}

                proceeds = trade_value - fee
                self.cash_balance += proceeds

                if current_amount > 0 and current_side == "short":
                    new_amount = current_amount + fill_amount
                    new_avg_price = ((current_amount * current_avg_price) + trade_value) / max(new_amount, 1e-12)
                else:
                    new_amount = fill_amount
                    new_avg_price = fill_price

                self.positions[symbol] = {
                    "amount": new_amount,
                    "avg_price": new_avg_price,
                    "side": "short",
                    "mark_price": fill_price,
                }

                print(f"[Portfolio] SELL-SHORT {fill_amount} {symbol} @ ${fill_price:,.2f} | Cash: ${self.cash_balance:,.2f}")
        
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
        position_value = 0.0
        for payload in self.positions.values():
            amount = float(payload.get("amount") or 0.0)
            mark_price = float(payload.get("mark_price") or payload.get("avg_price") or 0.0)
            side = str(payload.get("side") or "long").lower()
            if side == "short":
                position_value -= amount * mark_price
            else:
                position_value += amount * mark_price
        self.total_equity = self.cash_balance + position_value

    def update_market_prices(self, marks: Dict[str, float]):
        updated = False
        for symbol, mark in (marks or {}).items():
            if symbol not in self.positions:
                continue
            mark_price = float(mark or 0.0)
            if mark_price <= 0:
                continue
            payload = dict(self.positions[symbol])
            payload["mark_price"] = mark_price
            self.positions[symbol] = payload
            updated = True

        if updated:
            self._update_total_equity()
            self._save_to_db()
    
    def _save_to_db(self):
        """Guarda el estado actual del portfolio en la base de datos"""
        with SessionLocal() as db:
            portfolio = db.query(PaperPortfolioDB).filter(PaperPortfolioDB.bot_id == self.bot_id).first()
            if portfolio:
                portfolio.cash_balance = self.cash_balance
                portfolio.positions = self.positions
                portfolio.total_equity = self.total_equity
                portfolio.realized_pnl = self.realized_pnl
                portfolio.saved_profits = self.saved_profits
                portfolio.savings_ratio = self.savings_ratio
                portfolio.updated_at = datetime.utcnow()
                db.commit()
    
    def get_summary(self) -> Dict:
        """Retorna un resumen del portfolio"""
        return {
            "bot_id": self.bot_id,
            "cash_balance": self.cash_balance,
            "positions": self.positions,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "saved_profits": self.saved_profits,
            "total_profits": self.realized_pnl + self.saved_profits # Total profit generated
        }
