# Database Schema Design

The system uses **PostgreSQL** with the **TimescaleDB** extension for high-performance time-series data.

## Entity-Relationship Overview

### 1. Configuration & Management
- `accounts`: Store API keys (encrypted), exchange names, and sub-account info.
- `strategies`: Declarative definitions of trading logic.
- `bots`: Instance of a strategy linked to an account.

### 2. Trading Data (TimescaleDB Hyper-tables)
- `ohlcv_data`: Historical and real-time candle data.
- `trades`: Record of every execution (Entry/Exit).
- `metrics`: Snapshots of bot performance (Equity curve).

## SQL Schema (Simplified)

```sql
-- Accounts Table
CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    api_key_enc TEXT,
    api_secret_enc TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategies Table
CREATE TABLE strategies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    logic_config JSONB NOT NULL, -- Declarative config
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bots Table
CREATE TABLE bots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(id),
    strategy_id UUID REFERENCES strategies(id),
    status VARCHAR(20) DEFAULT 'stopped', -- starting, running, paused, stopped
    capital_allocation NUMERIC(18, 8),
    risk_config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades Hypertable (TimescaleDB)
CREATE TABLE trades (
    time TIMESTAMPTZ NOT NULL,
    bot_id UUID NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL, -- buy/sell
    price NUMERIC(18, 8) NOT NULL,
    amount NUMERIC(18, 8) NOT NULL,
    fee NUMERIC(18, 8),
    pnl NUMERIC(18, 8),
    meta JSONB -- Logs from AI or Risk Engine
);
SELECT create_hypertable('trades', 'time');

-- OHLCV Hypertable (TimescaleDB)
CREATE TABLE ohlcv (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open NUMERIC(18, 8),
    high NUMERIC(18, 8),
    low NUMERIC(18, 8),
    close NUMERIC(18, 8),
    volume NUMERIC(18, 8)
);
SELECT create_hypertable('ohlcv', 'time');
```
