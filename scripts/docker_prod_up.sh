#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  if [[ -f ".env.prod.example" ]]; then
    echo "⚠️ No existe .env. Copiando desde .env.prod.example..."
    cp .env.prod.example .env
    echo "📝 Edita .env (passwords/secrets) y vuelve a ejecutar."
    exit 1
  fi
  echo "❌ Falta .env y .env.prod.example"
  exit 1
fi

echo "🚀 Levantando stack de producción (db + redis + api)..."
docker compose -f docker-compose.prod.yml up -d --build db redis api

echo "⏳ Esperando health de API..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "✅ API saludable en http://127.0.0.1:8000"
    exit 0
  fi
  sleep 2
done

echo "❌ API no respondió saludable a tiempo"
docker compose -f docker-compose.prod.yml logs --tail=120 api || true
exit 1
