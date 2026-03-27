#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${1:-docker-compose.prod.yml}"
ENV_FILE="${2:-.env}"

echo "🚀 Levantando stack inicial con $COMPOSE_FILE ..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build db redis api

echo "⏳ Esperando API..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  echo "❌ API no respondió a tiempo."
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200 api || true
  exit 1
fi

STATUS_JSON="$(curl -fsS "http://127.0.0.1:8000/api/setup/status")"
echo "✅ API online."
echo "Setup status: $STATUS_JSON"

echo
echo "➡️  Abre en navegador:"
echo "    http://127.0.0.1:8000/setup"
echo
echo "El setup inicial bloquea el guardado hasta validar SMTP."
