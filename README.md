# Professional Algorithmic Trading Platform

A modular, scalable, and secure platform for assisted and automatic trading across Crypto and Traditional assets.

## 📁 Project Structure

```text
.
├── apps/
│   ├── api/                # FastAPI Gateway (Dashboard & Controller)
│   ├── engine/             # Core Trading Engine & Strategy execution
│   ├── bot_manager/        # Logic to manage bot lifecycles
│   ├── ai_engine/          # Local AI/LLM analysis & reporting
│   └── shared/             # Shared Pydantic models, Utils, DB models
├── docs/                   # Full Technical & Functional Documentation
├── scripts/                # Setup & Migration scripts
├── docker-compose.yml      # Orchestration of DB, Cache, and Apps
├── requirements.txt        # Python dependencies
└── README.md               # You are here
```

## 🚀 Getting Started

1. **Prerequisites**:
   - Docker & Docker Compose
   - Python 3.11+
   - [Optional] Ollama for local AI

2. **Setup**:
   ```bash
   pip install -r requirements.txt
   docker-compose up -d
   ```

3. **Documentation**:
   Refer to the `docs/` folder for:
   - [Architecture](docs/architecture.md)
   - [Functional Specs](docs/functional.md)
   - [Database Schema](docs/database_schema.md)
   - [API Specs](docs/api_spec.md)
   - [Catálogo de Bots Seguros](docs/catalogo_bots_seguro.md)
   - [Roadmap](docs/roadmap.md)

## 🛡️ Monitoreo estable (producción)

Para generar datos de validación paper sin corrupción de archivos, ejecuta siempre con el Python del entorno virtual y `PYTHONPATH`:

```bash
cd "/Users/bielrivero/Library/Mobile Documents/com~apple~CloudDocs/APPS ANTIGRAVITY BIEL/AAA BOT TRADING"
PYTHONPATH=. .venv/bin/python scripts/monitor_paper_fleet.py --hours 2 --interval 120 --prefix paper_lab_prod
```

Este monitor ahora incluye:
- Escritura robusta en CSV/JSONL (`flush` + `fsync`) por snapshot.
- Escritura atómica del resumen final JSON (sin archivos truncados).
- Lock por prefijo en `reports/<prefix>.lock` para evitar dos ejecuciones simultáneas sobre la misma corrida.
- Sanitización de valores numéricos no válidos (`NaN`/`inf`) a `0.0`.

## ⚙️ Comando único de operación (paper + estado producción)

Nuevo script operativo: `scripts/production_control.sh`

Ejemplos:

```bash
# 1) Estado de bots para producción (colores PREPARADO / CASI LISTO / BLOQUEADO)
bash scripts/production_control.sh status --lookback-hours 24 --min-scored-trades 8

# 2) Deploy operativo único (asegura API + lanza monitor paper en background con lock)
bash scripts/production_control.sh deploy --hours 2 --interval 120 --prefix paper_lab_prod

# 3) Activar un bot en producción (si cumple guardrails)
bash scripts/production_control.sh activate Bot-LAB-EMA-BTC --lookback-hours 24 --min-scored-trades 8
```

Notas:
- El comando `deploy` usa lock global en `/tmp/aaa_bot_production_deploy.lock`.
- El monitor paper mantiene lock por prefijo (`reports/<prefix>.lock`).

## 🖥️ Gestión desde la app (sin consola)

En la pestaña **Ajustes** existe ahora el bloque **Operación Automática** para:
- Ver estado en vivo de monitor paper + orquestador.
- Iniciar operación completa con un click.
- Parar operación completa con un click.

Backend usado por la UI:
- `GET /api/paper-monitor/status`
- `POST /api/paper-monitor/start`
- `POST /api/paper-monitor/stop`
- `POST /api/autotrader/orchestrator/start`
- `POST /api/autotrader/orchestrator/stop`

## 🤖 Advisor: creación de bots sin sobrescribir

En **Analizar y Recomendar**:
- **Crear bot ahora** siempre crea un bot **nuevo**.
- **Auto-ejecutar** siempre crea un bot **nuevo** (`force_new=true`).
- Ninguna de esas dos acciones sobrescribe bots existentes (por ejemplo, `Bot-472`).

Si quieres editar un bot existente, usa explícitamente **Usar en formulario** y luego aplica cambios al bot objetivo.

## 🔧 Runtime rápido API

Script recomendado para levantar/parar la API local con la DB runtime estable:

```bash
bash scripts/api_runtime.sh start
bash scripts/api_runtime.sh stop
bash scripts/api_runtime.sh restart
bash scripts/api_runtime.sh status
bash scripts/api_runtime.sh logs
```
