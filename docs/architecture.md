# Technical Architecture: Algorithmic Trading Platform

## System Overview
The platform is designed as a modular system where each component has a specific responsibility. Communication between modules is handled via an API Gateway or a Pub/Sub mechanism (Redis).

## Core Modules

### 1. API Gateway (FastAPI)
- **Responsibility**: Entry point for all external requests.
- **Functions**: Authentication, Rate Limiting, Request Routing, and providing an interface for the Dashboard.

### 2. Bot Manager
- **Responsibility**: Lifecycle management of trading bots.
- **Functions**: Start, Stop, Pause, Resume, and Monitoring of independent bot processes.

### 3. Core Trading Engine
- **Market Data Engine**: Aggregates OHLCV and real-time data from multiple sources. Implements caching and failover.
- **Strategy Engine**: Executes declaratively defined strategies.
- **Risk Engine**: The "Safety Net". Validates every trade against global and specific risk rules (Max drawdown, exposure per asset, kill switches).
- **Execution Engine**: Translates strategy signals into exchange-specific API calls using CCXT or direct broker libraries.

### 4. AI Analysis Engine
- **Responsibility**: Post-trade analysis and market insight generation.
- **Functions**: Parameter optimization (Backtesting feedback), anomaly detection, and natural language reporting.

### 5. Data Storage Layer
- **PostgreSQL**: Stores relational data (Users, Bots, Strategies, Config).
- **TimescaleDB**: Extension for PostgreSQL to handle high-velocity OHLCV and Trade data efficiently.
- **Redis**: Real-time caching for "Hot Data" (Current prices, active signals).

## Data Flow (Trading Loop)
1. **Ticker Update**: `Market Data Engine` receives price update -> Updates Redis.
2. **Strategy Trigger**: `Strategy Engine` checks conditions against price update.
3. **Signal Generation**: If conditions met, signal is sent to `Risk Engine`.
4. **Risk Validation**: `Risk Engine` accepts or rejects signal based on exposure/limits.
5. **Order Execution**: If accepted, `Execution Engine` places order via CCXT.
6. **Persistence**: `Reporting Engine` logs the trade to PostgreSQL.

## Deployment Strategy
- **Containerization**: Everything runs in Docker.
- **Local AI**: LLaMA/Mistral models running in a dedicated container or via Ollama API.
