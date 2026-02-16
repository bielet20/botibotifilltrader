# Functional Specification: Algorithmic Trading Platform

## User Roles
- **Trader**: Manages bots, reviews reports, manual/assisted trading.
- **System Admin**: Configuration of exchanges, AI settings, and system monitoring.

## Key Features

### Trading Modes
- **Assisted**: AI/Strategy provides signals; User must confirm execution.
- **Semi-Automatic**: Strategy executes within specific boundaries (e.g., specific hours or volume).
- **Automatic**: Bots run 24/7 based on configured strategies and risk limits.

### Strategy Management
- Strategies are defined in JSON/YAML (Declarative).
- Users can backtest strategies against historical data before deployment.
- "Cloning" feature: Duplicate a strategy with modified parameters.

### AI Integration (Insights over Execution)
- **Post-Market Reports**: "Why did I lose money today?" analysis.
- **Parameter Suggestion**: AI suggests better EMA periods or RSI levels based on recent history.
- **Natural Language Interface**: "Show me my most profitable crypto bot in the last 7 days."

### Risk Control (The "Independent Guard")
- **Kill Switch**: Stop all trading across all accounts in 1 click.
- **Daily Drawdown**: Hard limit on losses per 24h.
- **Asset Diversification**: Max % of capital allowed per single asset.

### Reporting
- Interactive Dashboard (ROI, Sharpe, Sortino).
- Automated PDF reports sent via email/telegram.
- Export results to JSON for external analysis.
