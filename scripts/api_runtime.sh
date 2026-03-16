#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN=".venv/bin/python"
API_HOST="127.0.0.1"
API_PORT="8000"
API_URL="http://${API_HOST}:${API_PORT}"
API_LOG="/tmp/aaa_bot_uvicorn_bg.log"
PID_FILE="/tmp/aaa_bot_uvicorn_bg.pid"
DATABASE_URL_VALUE="sqlite:///./trading_runtime.db"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "❌ No existe $PYTHON_BIN"
  exit 1
fi

api_health() {
  curl -fsS "${API_URL}/api/health" >/dev/null 2>&1
}

get_pid() {
  if [[ -f "$PID_FILE" ]]; then
    cat "$PID_FILE"
    return 0
  fi
  pgrep -f "uvicorn apps.api.main:app --host ${API_HOST} --port ${API_PORT}" | head -n 1 || true
}

start_api() {
  if api_health; then
    echo "✅ API ya activa en ${API_URL}"
    return 0
  fi

  pkill -f "uvicorn apps.api.main:app --host ${API_HOST} --port ${API_PORT}" >/dev/null 2>&1 || true

  echo "🚀 Iniciando API en background..."
  DATABASE_URL="$DATABASE_URL_VALUE" PYTHONPATH=. PYDANTIC_DISABLE_PLUGINS="__all__" "$PYTHON_BIN" -m uvicorn apps.api.main:app --host "$API_HOST" --port "$API_PORT" > "$API_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"

  # Startup may take longer when resuming bots/guards on cold boot.
  local retries=180
  local i=1
  while [[ $i -le $retries ]]; do
    if api_health; then
      echo "✅ API arriba (${API_URL}) · pid=${pid}"
      echo "📝 Log: ${API_LOG}"
      return 0
    fi

    # Fail fast if the process crashed before becoming healthy.
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "❌ Proceso API finalizó antes de estar saludable (pid=${pid})."
      echo "📝 Últimas líneas de log:"
      tail -n 120 "$API_LOG" || true
      exit 1
    fi

    sleep 1
    i=$((i + 1))
  done

  echo "❌ La API no respondió después de iniciar (timeout ${retries}s)."
  echo "📝 Últimas líneas de log:"
  tail -n 120 "$API_LOG" || true
  exit 1
}

stop_api() {
  local pid
  pid="$(get_pid)"

  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "🛑 Deteniendo API pid=${pid}..."
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
  fi

  pkill -f "uvicorn apps.api.main:app --host ${API_HOST} --port ${API_PORT}" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"

  if api_health; then
    echo "⚠️ La API sigue respondiendo en ${API_URL}"
    exit 1
  fi

  echo "✅ API detenida"
}

status_api() {
  if api_health; then
    local pid
    pid="$(get_pid)"
    echo "✅ API activa en ${API_URL}${pid:+ · pid=${pid}}"
    curl -sS "${API_URL}/api/health" | tr -d '\n'
    echo
  else
    echo "❌ API inactiva en ${API_URL}"
    exit 1
  fi
}

logs_api() {
  if [[ -f "$API_LOG" ]]; then
    tail -n 80 "$API_LOG"
  else
    echo "⚠️ No existe log en ${API_LOG}"
  fi
}

usage() {
  cat <<'EOF'
Uso:
  bash scripts/api_runtime.sh start
  bash scripts/api_runtime.sh stop
  bash scripts/api_runtime.sh restart
  bash scripts/api_runtime.sh status
  bash scripts/api_runtime.sh logs
EOF
}

cmd="${1:-status}"

case "$cmd" in
  start)
    start_api
    ;;
  stop)
    stop_api
    ;;
  restart)
    stop_api || true
    start_api
    ;;
  status)
    status_api
    ;;
  logs)
    logs_api
    ;;
  *)
    usage
    exit 1
    ;;
esac
