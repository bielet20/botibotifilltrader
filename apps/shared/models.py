from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
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

class ExecutionResult(BaseModel):
    order_id: str
    status: str
    filled_amount: float
    avg_price: float
    timestamp: datetime

# --- SQLAlchemy Models ---

class AccountDB(Base):
    __tablename__ = "accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    time = Column(DateTime, nullable=False, default=datetime.utcnow)
    bot_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    meta = Column(JSON)
