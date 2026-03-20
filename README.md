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

2. **Setup** (elige uno):
   - **Solo Python local:** `pip install -r requirements.txt` y `bash start.sh`
   - **Todo en Docker (DB + Redis + API + worker):** ver sección *Docker desarrollo* más abajo

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

## 🔐 Acceso con contraseña + backups automáticos cifrados

1. Genera hash de contraseña:
   ```bash
   python scripts/generate_app_auth_hash.py
   ```
2. En `.env` activa seguridad de acceso:
   - `APP_AUTH_ENABLED=true`
   - `APP_AUTH_USERNAME=admin` (o el usuario que quieras)
   - `APP_AUTH_PASSWORD_HASH=<hash generado>`
   - `APP_AUTH_SECRET_KEY=<clave larga aleatoria>`
   - `APP_AUTH_COOKIE_SECURE=true` (si usas HTTPS)
   - `APP_AUTH_IDLE_TIMEOUT_MINUTES=30` (cierre por inactividad)
   - `APP_AUTH_MAX_FAILED_ATTEMPTS=5`
   - `APP_AUTH_LOCKOUT_MINUTES=15`
   - (opcional 2FA) `APP_AUTH_TOTP_ENABLED=true` + `APP_AUTH_TOTP_SECRET=<base32>`
3. Activa backups automáticos cifrados:
   - `DB_BACKUP_ENABLED=true`
   - `DB_BACKUP_ENCRYPTION_KEY=<clave Fernet>`
   - `DB_BACKUP_INTERVAL_SEC=3600`
   - `DB_BACKUP_RETENTION_DAYS=14`
4. Reinicia API:
   ```bash
   bash scripts/api_runtime.sh restart
   ```

Endpoints útiles:
- `GET /api/auth/status`
- `POST /api/db-backups/run`
- `GET /api/db-backups/list`
- `GET /api/db-backups/status`

Restaurar backup:
```bash
python scripts/restore_db_backup.py --file backups/db/<archivo>.bin.enc
```

## 🐳 Docker desarrollo (stack completo)

Levanta **Postgres (Timescale)**, **Redis**, **API** y **worker** con un solo comando.

1. Crea `.env` desde la plantilla (imprescindible: `DATABASE_URL` con host `db` y `REDIS_URL` con host `redis`):
   ```bash
   cp .env.example .env
   ```
   En Docker debe quedar, como mínimo:
   - `DATABASE_URL=postgresql://trading_user:trading_pass@db/trading_db`
   - `REDIS_URL=redis://redis:6379/0`

2. Arranca:
   ```bash
   docker compose up -d --build
   ```
   O con helper:
   ```bash
   bash scripts/docker_dev_stack.sh up
   ```

3. Prueba:
   - Web: http://127.0.0.1:8000/
   - Salud: http://127.0.0.1:8000/api/health
   - Logs: `docker compose logs -f api`

4. Parar:
   ```bash
   docker compose down
   ```

Notas:
- Postgres y Redis quedan escuchando solo en **localhost** (`127.0.0.1:5432` y `:6379`).
- La API publica **8000** en todas las interfaces del host (`8000:8000`).
- El `docker-compose.yml` espera a que **db** y **redis** pasen healthcheck antes de subir **api** y **worker**.

## 🐳 Docker producción

Se agregó un stack de producción separado para no mezclar con el `docker-compose.yml` de desarrollo.

Archivos:
- `Dockerfile.prod`
- `docker-compose.prod.yml`
- `.dockerignore`

Comandos recomendados:

```bash
# Build + run API en producción
docker compose -f docker-compose.prod.yml up -d --build

# Ver estado
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api

# Healthcheck
curl http://127.0.0.1:8000/api/health

# Apagar
docker compose -f docker-compose.prod.yml down
```

Reinicio limpio (si hay estado raro):

```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

Rollback rápido a imagen ya construida (sin rebuild):

```bash
docker compose -f docker-compose.prod.yml up -d --no-build
```

Opcional: iniciar también `worker` (perfil separado):

```bash
docker compose -f docker-compose.prod.yml --profile worker up -d --build
```

Notas de hardening incluidas:
- `init: true` (manejo de señales correcto)
- `no-new-privileges`
- `tmpfs /tmp`
- rotación de logs (`max-size`, `max-file`)
- `healthcheck` reforzado
