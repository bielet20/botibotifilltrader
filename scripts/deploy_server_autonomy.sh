#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ENV_SOURCE="${1:-.env.server.autonomy}"
ENV_TARGET=".env"
COMPOSE_FILE="docker-compose.prod.yml"

if [[ ! -f "$ENV_SOURCE" ]]; then
  echo "❌ No existe $ENV_SOURCE"
  echo "   Ejemplo: bash scripts/deploy_server_autonomy.sh .env.server.autonomy"
  exit 1
fi

if [[ "$ENV_SOURCE" != "$ENV_TARGET" ]]; then
  cp "$ENV_SOURCE" "$ENV_TARGET"
  echo "✅ Copiado $ENV_SOURCE -> $ENV_TARGET"
fi

echo "⚠️  Verifica secretos en $ENV_TARGET (CHANGE_ME_*) antes de continuar."

echo "🚀 Levantando stack autónomo (db + redis + api)..."
docker compose --env-file "$ENV_TARGET" -f "$COMPOSE_FILE" up -d --build db redis api

echo "⏳ Esperando /api/health..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    echo "✅ API saludable"
    break
  fi
  sleep 2
done

if ! curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  echo "❌ API no respondió a tiempo"
  docker compose --env-file "$ENV_TARGET" -f "$COMPOSE_FILE" logs --tail=200 api || true
  exit 1
fi

echo "🔎 Validando autonomía (watchdog + capital autonomy)..."
STATUS_JSON="$(curl -fsS "http://127.0.0.1:8000/api/autonomy/watchdog/status")"
python3 - <<'PY' "$STATUS_JSON"
import json, sys
d = json.loads(sys.argv[1])
c = dict(d.get("capital_autonomy") or {})
print(f"watchdog_enabled={d.get('enabled')} running={d.get('running')} interval_sec={d.get('interval_sec')}")
print(
    "capital_autonomy="
    f"enabled={c.get('enabled')} max_active={c.get('max_active')} "
    f"base_allocation={c.get('base_allocation')} only_paper={c.get('only_paper')}"
)
PY

echo "▶️ Ejecutando un ciclo manual del watchdog..."
RUN_ONCE_JSON="$(curl -fsS -X POST "http://127.0.0.1:8000/api/autonomy/watchdog/run-once")"
python3 - <<'PY' "$RUN_ONCE_JSON"
import json, sys
d = json.loads(sys.argv[1])
c = dict(d.get("capital_autonomy") or {})
print(
    "run_once:"
    f" evaluated={c.get('evaluated')} running_before={c.get('running_before')} "
    f"running_after={c.get('running_after')} started={c.get('started')} stopped={c.get('stopped')}"
)
PY

echo "✅ Despliegue autónomo listo."
echo "   Logs: docker compose --env-file .env -f $COMPOSE_FILE logs -f api"
