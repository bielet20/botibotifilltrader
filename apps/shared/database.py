from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or "@db/" in DATABASE_URL:
    # Fallback to local SQLite for development if DB host is 'db' (docker-only) or not set
    DATABASE_URL = "sqlite:///./trading.db"
    print(f"--- [Database] Using local SQLite fallback: {DATABASE_URL} ---")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # In a real app we'd use Alembic, but for this skeleton create_all is fine
    Base.metadata.create_all(bind=engine)
