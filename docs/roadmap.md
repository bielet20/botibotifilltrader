# Development Roadmap: Algorithmic Trading Platform

## Phase 1: Foundation (MVP) - [COMPLETED IN SKELETON]
- [ ] Basic project structure & Docker setup.
- [ ] Core interfaces for Exchanges and Strategies.
- [ ] Risk Engine with Global Kill Switch.
- [ ] CCXT Integration for Binance/Bybit tickers.
- [ ] Bot Manager to spawn/kill independent bot threads/processes.
- [ ] Basic SQLite/PostgreSQL storage for trades.

## Phase 2: Enhanced Reliability & Data
- [ ] TimescaleDB integration for high-perf OHLCV storage.
- [ ] Redis caching for real-time order book and candle data.
- [ ] Unit testing for Risk and Strategy logic.
- [ ] Strategy versioning and declarative config validation.

## Phase 3: AI & Insights
- [ ] Local LLM integration (Ollama/Llama-cpp-python).
- [ ] Post-trade analysis module (explaining PnL).
- [ ] Automated PDF/JSON reporting.
- [ ] Market sentiment analysis (News/Social aggregator).

## Phase 4: Advanced Trading
- [ ] Backtesting Engine with Fees/Slippage simulation.
- [ ] Support for Options and Perpetuals.
- [ ] Interactive Brokers / Alpaca integration for traditional assets.
- [ ] Multi-asset portfolio management bots.

## Phase 5: Production & UI
- [ ] Web Dashboard (React/Next.js).
- [ ] Advanced security: API key encryption (KMS/Vault), JWT.
- [ ] Alerts & Notifications (Telegram/Discord/Email).
- [ ] Deployment to Cloud (AWS/DigitalOcean) with Kubernetes.
