#!/usr/bin/env bash
# Arranca o detiene el stack completo en Docker (Postgres + Redis + API + worker).
# Uso desde la raíz del repo:
#   bash scripts/docker_dev_stack.sh up      # build + up -d
#   bash scripts/docker_dev_stack.sh down
#   bash scripts/docker_dev_stack.sh logs
#   bash scripts/docker_dev_stack.sh ps

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-up}"

ensure_env() {
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      echo "✅ Creado .env desde .env.example (revísalo antes de producción)."
    else
      echo "❌ Falta .env y no hay .env.example"
      exit 1
    fi
  fi
}

case "$cmd" in
  up)
    ensure_env
    docker compose up -d --build
    echo ""
    echo "✅ Stack arriba."
    echo "   Web:    http://127.0.0.1:8000/"
    echo "   Health: http://127.0.0.1:8000/api/health"
    echo "   Docs:   http://127.0.0.1:8000/docs"
    echo ""
    echo "Logs API: docker compose logs -f api"
    ;;
  down)
    docker compose down
    ;;
  logs)
    docker compose logs -f api worker
    ;;
  ps)
    docker compose ps
    ;;
  *)
    echo "Uso: bash scripts/docker_dev_stack.sh {up|down|logs|ps}"
    exit 1
    ;;
esac
