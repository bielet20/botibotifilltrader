#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN=".venv/bin/python"
API_HOST="127.0.0.1"
API_PORT="8000"
API_URL="http://${API_HOST}:${API_PORT}"
API_LOG="/tmp/aaa_bot_uvicorn.log"
DEPLOY_LOCK_DIR="/tmp/aaa_bot_production_deploy.lock"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "❌ No existe $PYTHON_BIN"
  exit 1
fi

LOOKBACK_HOURS="${LOOKBACK_HOURS:-24}"
MIN_SCORED_TRADES="${MIN_SCORED_TRADES:-8}"
MONITOR_HOURS="${MONITOR_HOURS:-2}"
MONITOR_INTERVAL="${MONITOR_INTERVAL:-120}"
MONITOR_PREFIX="${MONITOR_PREFIX:-paper_lab_prod}"

parse_common_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --lookback-hours)
        LOOKBACK_HOURS="$2"; shift 2 ;;
      --min-scored-trades)
        MIN_SCORED_TRADES="$2"; shift 2 ;;
      --hours)
        MONITOR_HOURS="$2"; shift 2 ;;
      --interval)
        MONITOR_INTERVAL="$2"; shift 2 ;;
      --prefix)
        MONITOR_PREFIX="$2"; shift 2 ;;
      *)
        echo "⚠️ Flag no reconocida: $1"; shift ;;
    esac
  done
}

api_health() {
  curl -fsS "${API_URL}/api/health" >/dev/null 2>&1
}

ensure_api_running() {
  if api_health; then
    echo "✅ API activa en ${API_URL}"
    return 0
  fi

  echo "🚀 Iniciando API..."
  pkill -f "uvicorn apps.api.main:app" >/dev/null 2>&1 || true
  PYTHONPATH=. "$PYTHON_BIN" -m uvicorn apps.api.main:app --host "$API_HOST" --port "$API_PORT" > "$API_LOG" 2>&1 &
  sleep 2

  if api_health; then
    echo "✅ API iniciada (${API_URL})"
    return 0
  fi

  echo "❌ No se pudo iniciar la API. Log: $API_LOG"
  tail -n 80 "$API_LOG" || true
  exit 1
}

show_status() {
  ensure_api_running
  LOOKBACK_HOURS="$LOOKBACK_HOURS" MIN_SCORED_TRADES="$MIN_SCORED_TRADES" PYTHONPATH=. "$PYTHON_BIN" - <<'PY'
import json
import os
import urllib.request

base = "http://127.0.0.1:8000"
lookback = int(float(os.environ.get("LOOKBACK_HOURS", "24")))
min_trades = int(float(os.environ.get("MIN_SCORED_TRADES", "8")))

payload = {
    "lookback_hours": lookback,
    "min_scored_trades": min_trades,
}

req = urllib.request.Request(
    f"{base}/api/monitoring/test-results",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
data = json.load(urllib.request.urlopen(req))
rows = data.get("results", [])

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"

def readiness(item):
    metrics = item.get("metrics", {}) or {}
    scored = float(metrics.get("scored_trades") or 0)
    wr = float(metrics.get("win_rate") or 0)
    net = float(metrics.get("net_pnl") or 0)
    loss_streak = float(metrics.get("consecutive_losses") or 0)
    crit = float(item.get("open_critical_alerts") or 0)

    reasons = []
    if scored < min_trades: reasons.append(f"trades<{min_trades}")
    if wr < 55: reasons.append("win_rate<55%")
    if net <= 0: reasons.append("net<=0")
    if loss_streak > 2: reasons.append("loss_streak>2")
    if crit > 0: reasons.append(f"critical={int(crit)}")

    if not reasons:
        return ("PREPARADO", GREEN, "ok")
    if len(reasons) <= 1 and crit == 0:
        return ("CASI LISTO", YELLOW, reasons[0])
    return ("BLOQUEADO", RED, " · ".join(reasons))

print(f"{BLUE}=== ESTADO PRODUCCIÓN ({lookback}h / min {min_trades} trades) ==={RESET}")
if not rows:
    print("Sin datos de validación.")
    raise SystemExit(0)

for item in rows[:12]:
    metrics = item.get("metrics", {}) or {}
    label, color, reason = readiness(item)
    bot = item.get("bot_id")
    wr = float(metrics.get("win_rate") or 0)
    net = float(metrics.get("net_pnl") or 0)
    scored = int(metrics.get("scored_trades") or 0)
    crit = int(item.get("open_critical_alerts") or 0)
    print(f"{bot:24s}  {color}{label:10s}{RESET}  wr={wr:6.2f}%  net={net:10.4f}  trades={scored:3d}  alerts={crit:2d}  {reason}")
PY
}

run_paper_once() {
  PYTHONPATH=. "$PYTHON_BIN" scripts/monitor_paper_fleet.py \
    --hours "$MONITOR_HOURS" \
    --interval "$MONITOR_INTERVAL" \
    --prefix "$MONITOR_PREFIX"
}

run_deploy() {
  if ! mkdir "$DEPLOY_LOCK_DIR" 2>/dev/null; then
    echo "❌ Ya hay un deploy en curso (lock: $DEPLOY_LOCK_DIR)"
    exit 1
  fi
  trap 'rmdir "$DEPLOY_LOCK_DIR" >/dev/null 2>&1 || true' EXIT

  ensure_api_running

  local monitor_log="reports/${MONITOR_PREFIX}_daemon.log"
  echo "📡 Lanzando monitor paper en segundo plano..."
  nohup env PYTHONPATH=. "$PYTHON_BIN" scripts/monitor_paper_fleet.py \
    --hours "$MONITOR_HOURS" \
    --interval "$MONITOR_INTERVAL" \
    --prefix "$MONITOR_PREFIX" \
    > "$monitor_log" 2>&1 &

  echo "✅ Monitor lanzado. Log: $monitor_log"
  show_status
}

activate_bot() {
  local bot_id="${1:-}"
  if [[ -z "$bot_id" ]]; then
    echo "❌ Debes indicar bot_id"
    echo "Uso: bash scripts/production_control.sh activate BOT_ID"
    exit 1
  fi

  ensure_api_running

  curl -fsS -X POST "${API_URL}/api/monitoring/activate-production" \
    -H 'Content-Type: application/json' \
    -d "{\"bot_id\":\"${bot_id}\",\"lookback_hours\":${LOOKBACK_HOURS},\"min_scored_trades\":${MIN_SCORED_TRADES}}" | \
    PYTHONPATH=. "$PYTHON_BIN" - <<'PY'
import json, sys
r = json.load(sys.stdin)
print(json.dumps(r, ensure_ascii=False, indent=2))
if not r.get("activated"):
    raise SystemExit(1)
PY
}

usage() {
  cat <<'EOF'
Uso:
  bash scripts/production_control.sh status [flags]
  bash scripts/production_control.sh paper [flags]
  bash scripts/production_control.sh deploy [flags]
  bash scripts/production_control.sh activate BOT_ID [flags]

Flags:
  --lookback-hours <n>      (default: 24)
  --min-scored-trades <n>   (default: 8)
  --hours <n>               (monitor paper, default: 2)
  --interval <sec>          (monitor paper, default: 120)
  --prefix <name>           (monitor paper, default: paper_lab_prod)
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status)
    parse_common_flags "$@"
    show_status
    ;;
  paper)
    parse_common_flags "$@"
    run_paper_once
    ;;
  deploy)
    parse_common_flags "$@"
    run_deploy
    ;;
  activate)
    bot_id="${1:-}"
    shift || true
    parse_common_flags "$@"
    activate_bot "$bot_id"
    ;;
  *)
    usage
    exit 1
    ;;
esac
