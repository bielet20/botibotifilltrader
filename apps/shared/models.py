from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, JSON, Boolean, ForeignKey, Uuid, Text
import uuid

# Base for SQLAlchemy
from apps.shared.database import Base

class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class BotStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"

class TradeSignal(BaseModel):
    symbol: str
    side: TradeSide
    amount: float
    price: Optional[float] = None
    strategy_id: str
    meta: Dict[str, Any] = {}

class RiskResult(BaseModel):
    approved: bool
    reason: Optional[str] = None
    original_signal: TradeSignal
    emergency_exit: bool = False

class ExecutionResult(BaseModel):
    order_id: str
    status: str
    filled_amount: float
    avg_price: float
    fee: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime

# --- SQLAlchemy Models ---

class AccountDB(Base):
    __tablename__ = "accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    exchange = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class BotDB(Base):
    __tablename__ = "bots"
    
    id = Column(String(100), primary_key=True)
    strategy = Column(String(100))
    status = Column(String(20), default="stopped")
    capital_allocation = Column(Float, default=0.0)
    config = Column(JSON)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class TradeDB(Base):
    __tablename__ = "trades"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    time = Column(DateTime, nullable=False, default=datetime.utcnow)
    bot_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    meta = Column(JSON)

class OrderLogDB(Base):
    """Persistent log of every order sent by the system.
    Survives restarts — used for state recovery and auditing."""
    __tablename__ = "order_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    bot_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)    # buy / sell
    status = Column(String(20), default="open")  # open / closed / cancelled / failed
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    filled_amount = Column(Float, default=0.0)
    fee = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    exchange_order_id = Column(String(100), nullable=True)
    strategy = Column(String(100), nullable=True)
    executor = Column(String(50), default="paper")  # paper / hyperliquid
    meta = Column(JSON, default={})

class PositionDB(Base):
    """Open positions per bot+symbol. Updated on every trade.
    Reading this table on startup lets the system know what's open."""
    __tablename__ = "positions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bot_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)         # long / short
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    leverage = Column(Float, default=1.0)
    current_price = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, default=0.0)
    fee_paid = Column(Float, default=0.0)
    opened_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_open = Column(Boolean, default=True)
    meta = Column(JSON, default={})


class BotAlertDB(Base):
    """Alertas operativas y de productividad por bot."""
    __tablename__ = "bot_alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow)
    bot_id = Column(String(100), nullable=False)
    level = Column(String(20), default="info")  # info / warning / critical
    title = Column(String(255), nullable=False)
    message = Column(String(1000), nullable=False)
    reason_code = Column(String(100), nullable=True)
    data = Column(JSON, default={})
    acknowledged = Column(Boolean, default=False)


class BotLearningStateDB(Base):
    """Estado persistente de aprendizaje por bot y símbolo."""
    __tablename__ = "bot_learning_state"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bot_id = Column(String(100), nullable=False)
    symbol = Column(String(30), nullable=False)
    strategy = Column(String(100), nullable=True)
    state = Column(JSON, default={})
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EncryptedCredentialDB(Base):
    """
    Credenciales sensibles cifradas con Fernet (clave maestra solo en entorno APP_CREDENTIALS_FERNET_KEY).
    id fijo 'hyperliquid' para la cuenta Hyperliquid.
    """
    __tablename__ = "encrypted_credentials"

    id = Column(String(64), primary_key=True)
    ciphertext = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
