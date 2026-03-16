#!/usr/bin/env bash
set -u

# Keeps the trading stack alive overnight:
# - Ensures API is up
# - Ensures orchestrator is running
# - Runs net-profit close checks with fee-aware threshold

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/reports"
mkdir -p "$LOG_DIR"

SUP_LOG="$LOG_DIR/autonomous_supervisor.log"

CHECK_INTERVAL_SEC="${CHECK_INTERVAL_SEC:-120}"
MIN_NET_PNL="${MIN_NET_PNL:-1.0}"
MIN_NET_PROFIT_PCT="${MIN_NET_PROFIT_PCT:-0.0}"
STOP_LOSS_PCT="${STOP_LOSS_PCT:-0.02}"
MAX_NET_LOSS_ABS="${MAX_NET_LOSS_ABS:-3.0}"
EXIT_SLIPPAGE_PCT="${EXIT_SLIPPAGE_PCT:-0.0002}"
TP_ONLY_PRODUCTION="${TP_ONLY_PRODUCTION:-true}"
TRAILING_PROFILE="${TRAILING_PROFILE:-auto}"
VOLATILITY_TIMEFRAME="${VOLATILITY_TIMEFRAME:-5m}"
VOLATILITY_LOOKBACK="${VOLATILITY_LOOKBACK:-48}"
VOLATILITY_LOW_THRESHOLD_PCT="${VOLATILITY_LOW_THRESHOLD_PCT:-0.0015}"
VOLATILITY_HIGH_THRESHOLD_PCT="${VOLATILITY_HIGH_THRESHOLD_PCT:-0.0035}"

cd "$ROOT_DIR" || exit 1

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Load env if available
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env >/dev/null 2>&1 || true
  set +a
fi

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$SUP_LOG"
}

api_is_up() {
  curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1 && return 0
  curl -fsS "http://127.0.0.1:8000/api/autotrader/orchestrator/status" >/dev/null 2>&1 && return 0
  return 1
}

start_api_if_needed() {
  if api_is_up; then
    return 0
  fi
  log "API down, starting runtime..."
  bash scripts/api_runtime.sh start >>"$SUP_LOG" 2>&1 || true
  sleep 3
}

ensure_orchestrator_running() {
  local status
  status="$(curl -fsS "http://127.0.0.1:8000/api/autotrader/orchestrator/status" 2>/dev/null || true)"
  if [[ "$status" == *'"running":true'* ]]; then
    return 0
  fi
  log "Orchestrator not running, starting..."
  curl -fsS -X POST "http://127.0.0.1:8000/api/autotrader/orchestrator/start" >>"$SUP_LOG" 2>&1 || true
}

run_profit_guard_once() {
  local out
  out="$(python scripts/close_profitable_positions.py --execute --min-net-pnl "$MIN_NET_PNL" \
    --min-net-profit-pct "$MIN_NET_PROFIT_PCT" \
    --stop-loss-pct "$STOP_LOSS_PCT" \
    --max-net-loss-abs "$MAX_NET_LOSS_ABS" \
    --exit-slippage-pct "$EXIT_SLIPPAGE_PCT" \
    --only-production-positions="$TP_ONLY_PRODUCTION" \
    --trailing-profile "$TRAILING_PROFILE" \
    --volatility-timeframe "$VOLATILITY_TIMEFRAME" \
    --volatility-lookback "$VOLATILITY_LOOKBACK" \
    --volatility-low-threshold-pct "$VOLATILITY_LOW_THRESHOLD_PCT" \
    --volatility-high-threshold-pct "$VOLATILITY_HIGH_THRESHOLD_PCT" 2>&1 || true)"
  printf '%s\n' "$out" >>"$SUP_LOG"
}

log "Autonomous trading supervisor started (interval=${CHECK_INTERVAL_SEC}s, min_net_pnl=${MIN_NET_PNL}, min_net_profit_pct=${MIN_NET_PROFIT_PCT}, exit_slippage_pct=${EXIT_SLIPPAGE_PCT}, tp_only_production=${TP_ONLY_PRODUCTION}, stop_loss_pct=${STOP_LOSS_PCT}, max_net_loss_abs=${MAX_NET_LOSS_ABS}, trailing_profile=${TRAILING_PROFILE})"

while true; do
  start_api_if_needed
  ensure_orchestrator_running
  run_profit_guard_once
  sleep "$CHECK_INTERVAL_SEC"
done
