from datetime import datetime, timedelta
from statistics import mean, pstdev
from fastapi import FastAPI, HTTPException, Depends, Header, Request, status
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import asyncio
import os
import uuid
import json
import csv
import io
import urllib.request
import urllib.parse
import subprocess
import gzip
import hashlib
import hmac
import base64
import struct
import time
from sqlalchemy import text
from sqlalchemy.orm import Session
import ccxt.async_support as ccxt
from cryptography.fernet import Fernet
from passlib.context import CryptContext

from apps.engine.backtester import BacktestEngine
from apps.engine.risk import RiskEngine
from apps.engine.bot_advisor import build_bot_advice
from apps.bot_manager.manager import BotManager
from apps.ai_engine.engine import AIEngine
from apps.ai_engine.adaptive_orchestrator import AdaptiveOrchestratorService
from apps.reporting_engine.production_guard import ProductionGuardService
from apps.reporting_engine.paper_monitor_runtime import PaperMonitorRuntimeService
from apps.shared.database import init_db, get_db, SessionLocal
from apps.shared.models import BotDB, TradeDB, BotStatus, OrderLogDB, PositionDB, BotAlertDB, BotLearningStateDB
from apps.shared.hyperliquid_credentials import (
    get_hyperliquid_wallet_and_key,
    fernet_configured,
    encrypted_blob_exists,
    save_hyperliquid_credentials_encrypted,
    delete_hyperliquid_encrypted_credentials,
    invalidate_hyperliquid_credentials_cache,
)
from apps.shared.bot_presets import list_bot_presets, get_bot_preset
from apps.engine.paper_portfolio import PaperPortfolioDB
from apps.engine.position_sync import PositionSyncService
from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.engine.market_data import MarketDataEngine

app = FastAPI(title="Trading Platform API Gateway")

try:
    from apps.reporting_engine.reporting import ReportingEngine, calculate_metrics
except Exception as _reporting_import_error:
    ReportingEngine = None

    def calculate_metrics(_trades):
        return {}

    print(f"[Startup] reporting module unavailable: {_reporting_import_error}")

# Initialize singletons BEFORE startup event so they are available
from datetime import datetime, timezone
import time as _time

_startup_time = _time.time()

# Singleton-like instances
risk_engine = RiskEngine()
bot_manager = BotManager()
ai_engine = AIEngine()
if ReportingEngine is None:
    reporting_engine = None
else:
    reporting_engine = ReportingEngine()
production_guard = ProductionGuardService(bot_manager)
adaptive_orchestrator = AdaptiveOrchestratorService(bot_manager, production_guard)
paper_monitor_runtime = PaperMonitorRuntimeService()

_auto_production_promotion_enabled = os.getenv("PRODUCTION_AUTO_PROMOTE_ENABLED", "true").lower() == "true"
_auto_production_promotion_interval_sec = max(30, int(os.getenv("PRODUCTION_AUTO_PROMOTE_INTERVAL_SEC", "180")))
_auto_production_lookback_hours = max(1, int(os.getenv("PRODUCTION_AUTO_PROMOTE_LOOKBACK_HOURS", "24")))
_auto_production_min_scored_trades = max(1, int(os.getenv("PRODUCTION_AUTO_PROMOTE_MIN_SCORED_TRADES", "12")))
_auto_production_top_n = max(1, int(os.getenv("PRODUCTION_AUTO_PROMOTE_TOP_N", "2")))
_auto_production_max_last_trade_age_hours = max(0.5, float(os.getenv("PRODUCTION_AUTO_PROMOTE_MAX_LAST_TRADE_AGE_HOURS", "6")))
_auto_production_loop_running = False
_auto_production_loop_task = None

_daily_blockers_enabled = os.getenv("PRODUCTION_BLOCKERS_DAILY_ENABLED", "true").lower() == "true"
_daily_blockers_interval_sec = max(900, int(os.getenv("PRODUCTION_BLOCKERS_DAILY_INTERVAL_SEC", "86400")))
_daily_blockers_lookback_hours = max(1, int(os.getenv("PRODUCTION_BLOCKERS_DAILY_LOOKBACK_HOURS", "24")))
_daily_blockers_min_scored_trades = max(1, int(os.getenv("PRODUCTION_BLOCKERS_DAILY_MIN_SCORED_TRADES", "8")))
_daily_blockers_loop_running = False
_daily_blockers_loop_task = None
_market_regime_cache_ttl_sec = max(30, int(os.getenv("MARKET_REGIME_CACHE_TTL_SEC", "300")))
_market_regime_cache: dict = {"updated_at": 0.0, "payload": None}
_db_backup_loop_running = False
_db_backup_loop_task = None
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_auth_failed_attempts: dict = {}


def _project_root_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _auth_enabled() -> bool:
    return str(os.getenv("APP_AUTH_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _auth_username() -> str:
    return str(os.getenv("APP_AUTH_USERNAME", "admin")).strip() or "admin"


def _auth_password_hash() -> str:
    return str(os.getenv("APP_AUTH_PASSWORD_HASH", "")).strip()


def _auth_secret_key() -> str:
    return str(os.getenv("APP_AUTH_SECRET_KEY", "")).strip()


def _auth_cookie_name() -> str:
    return str(os.getenv("APP_AUTH_COOKIE_NAME", "aaa_bot_session")).strip() or "aaa_bot_session"


def _auth_cookie_secure() -> bool:
    return str(os.getenv("APP_AUTH_COOKIE_SECURE", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _auth_totp_enabled() -> bool:
    return str(os.getenv("APP_AUTH_TOTP_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _auth_totp_secret() -> str:
    return str(os.getenv("APP_AUTH_TOTP_SECRET", "")).strip()


def _auth_idle_minutes() -> int:
    try:
        return max(5, int(os.getenv("APP_AUTH_IDLE_TIMEOUT_MINUTES", "30")))
    except Exception:
        return 30


def _auth_max_failed_attempts() -> int:
    try:
        return max(3, int(os.getenv("APP_AUTH_MAX_FAILED_ATTEMPTS", "5")))
    except Exception:
        return 5


def _auth_lockout_minutes() -> int:
    try:
        return max(1, int(os.getenv("APP_AUTH_LOCKOUT_MINUTES", "15")))
    except Exception:
        return 15


def _auth_session_minutes() -> int:
    try:
        return max(5, int(os.getenv("APP_AUTH_SESSION_MINUTES", "720")))
    except Exception:
        return 720


def _auth_is_configured() -> bool:
    if not _auth_enabled():
        return False
    if not (_auth_password_hash() and _auth_secret_key()):
        return False
    if _auth_totp_enabled() and not _auth_totp_secret():
        return False
    return True


def _verify_auth_password(password: str, stored_hash: str) -> bool:
    raw = str(stored_hash or "").strip()
    if not raw:
        return False

    # Preferred formats:
    # - pbkdf2_sha256:<iterations>:<salt_b64>:<digest_b64> (docker-friendly)
    # - pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64> (legacy)
    if raw.startswith("pbkdf2_sha256:") or raw.startswith("pbkdf2_sha256$"):
        delim = ":" if raw.startswith("pbkdf2_sha256:") else "$"
        parts = raw.split(delim)
        if len(parts) != 4:
            return False
        _, iter_s, salt_b64, digest_b64 = parts
        try:
            iterations = max(100_000, int(iter_s))
            salt = base64.urlsafe_b64decode(salt_b64.encode("utf-8"))
            expected = base64.urlsafe_b64decode(digest_b64.encode("utf-8"))
        except Exception:
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected),
        )
        return hmac.compare_digest(computed, expected)

    # Backward compatibility: passlib hash formats.
    try:
        return bool(_pwd_context.verify(password, raw))
    except Exception:
        return False


def _totp_secret_valid(secret: str) -> bool:
    if not secret:
        return False
    try:
        padded = secret.upper() + ("=" * ((8 - (len(secret) % 8)) % 8))
        base64.b32decode(padded.encode("utf-8"), casefold=True)
        return True
    except Exception:
        return False


def _totp_code(secret: str, for_ts: int, step_seconds: int = 30, digits: int = 6) -> str:
    padded = secret.upper() + ("=" * ((8 - (len(secret) % 8)) % 8))
    key = base64.b32decode(padded.encode("utf-8"), casefold=True)
    counter = int(for_ts // step_seconds)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits)


def _verify_totp_code(code: str, secret: str, window_steps: int = 1) -> bool:
    raw = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(raw) < 6:
        return False
    now = int(time.time())
    for drift in range(-window_steps, window_steps + 1):
        candidate = _totp_code(secret=secret, for_ts=now + (drift * 30))
        if hmac.compare_digest(candidate, raw[-6:]):
            return True
    return False


def _auth_attempt_key(request: Request, username: str) -> str:
    ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    ip_key = str(ip).split(",")[0].strip()
    return f"{ip_key}|{str(username or '').strip().lower()}"


def _auth_lockout_remaining_seconds(request: Request, username: str) -> int:
    key = _auth_attempt_key(request, username)
    data = _auth_failed_attempts.get(key) or {}
    locked_until = float(data.get("locked_until") or 0.0)
    now = _time.time()
    if locked_until <= now:
        return 0
    return int(max(1, locked_until - now))


def _register_auth_failure(request: Request, username: str) -> int:
    key = _auth_attempt_key(request, username)
    now = _time.time()
    data = dict(_auth_failed_attempts.get(key) or {})
    first_at = float(data.get("first_at") or now)
    failed = int(data.get("failed") or 0)
    # Reset rolling window after lockout window passes.
    if now - first_at > (_auth_lockout_minutes() * 60):
        failed = 0
        first_at = now
    failed += 1
    locked_until = 0.0
    if failed >= _auth_max_failed_attempts():
        locked_until = now + (_auth_lockout_minutes() * 60)
        failed = 0
        first_at = now
    _auth_failed_attempts[key] = {"first_at": first_at, "failed": failed, "locked_until": locked_until}
    return int(max(0, locked_until - now))


def _clear_auth_failures(request: Request, username: str) -> None:
    key = _auth_attempt_key(request, username)
    _auth_failed_attempts.pop(key, None)


def _create_auth_session_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "lseen": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_auth_session_minutes())).timestamp()),
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body_b64 = base64.urlsafe_b64encode(body).decode("utf-8").rstrip("=")
    sig = hmac.new(_auth_secret_key().encode("utf-8"), body_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{body_b64}.{sig_b64}"


def _decode_auth_session_token(token: str) -> dict | None:
    if not token or not _auth_secret_key():
        return None
    try:
        body_b64, sig_b64 = str(token).split(".", 1)
        expected_sig = hmac.new(
            _auth_secret_key().encode("utf-8"),
            body_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        received_sig = base64.urlsafe_b64decode(sig_b64 + ("=" * ((4 - len(sig_b64) % 4) % 4)))
        if not hmac.compare_digest(expected_sig, received_sig):
            return None
        raw = base64.urlsafe_b64decode(body_b64 + ("=" * ((4 - len(body_b64) % 4) % 4)))
        payload = json.loads(raw.decode("utf-8"))
        exp = int(payload.get("exp") or 0)
        if exp <= int(_time.time()):
            return None
        return dict(payload or {})
    except Exception:
        return None


def _request_authenticated_user(request: Request) -> str:
    token = request.cookies.get(_auth_cookie_name())
    if not token:
        raw_cookie = str(request.headers.get("cookie") or "")
        target = f"{_auth_cookie_name()}="
        for part in raw_cookie.split(";"):
            piece = part.strip()
            if piece.startswith(target):
                token = piece[len(target):]
                break
    if token:
        token = str(token).strip().strip('"').strip("'")
    if not token:
        return ""
    payload = _decode_auth_session_token(token)
    if not payload:
        return ""
    lseen = int(payload.get("lseen") or payload.get("iat") or 0)
    if lseen > 0:
        idle_timeout = _auth_idle_minutes() * 60
        if (_time.time() - lseen) > idle_timeout:
            return ""
    user = str(payload.get("sub") or "").strip()
    return user


def _refresh_auth_session_cookie(response, username: str) -> None:
    token = _create_auth_session_token(username)
    response.set_cookie(
        key=_auth_cookie_name(),
        value=token,
        max_age=_auth_session_minutes() * 60,
        httponly=True,
        secure=_auth_cookie_secure(),
        samesite="strict",
    )


def _database_url_runtime() -> str:
    url = str(os.getenv("DATABASE_URL", "")).strip()
    return url or "sqlite:///./trading.db"


def _database_kind(url: str) -> str:
    u = str(url or "").strip().lower()
    if u.startswith("sqlite"):
        return "sqlite"
    if u.startswith("postgresql") or u.startswith("postgres"):
        return "postgresql"
    return "unknown"


def _sqlite_file_path(url: str) -> str:
    # sqlite:///./trading.db | sqlite:////abs/path.db
    raw = str(url or "")
    if raw.startswith("sqlite:///"):
        candidate = raw.replace("sqlite:///", "", 1)
        if os.path.isabs(candidate):
            return candidate
        return os.path.abspath(os.path.join(_project_root_path(), candidate))
    if raw.startswith("sqlite://"):
        candidate = raw.replace("sqlite://", "", 1)
        return os.path.abspath(candidate)
    raise ValueError("invalid_sqlite_url")


def _db_backup_dir() -> str:
    raw = str(os.getenv("DB_BACKUP_DIR", "backups/db")).strip() or "backups/db"
    if os.path.isabs(raw):
        path = raw
    else:
        path = os.path.abspath(os.path.join(_project_root_path(), raw))
    os.makedirs(path, exist_ok=True)
    return path


def _db_backup_encryption_key() -> str:
    return str(os.getenv("DB_BACKUP_ENCRYPTION_KEY", "")).strip()


def _db_backup_enabled() -> bool:
    return str(os.getenv("DB_BACKUP_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _db_backup_interval_sec() -> int:
    try:
        return max(300, int(os.getenv("DB_BACKUP_INTERVAL_SEC", "3600")))
    except Exception:
        return 3600


def _db_backup_retention_days() -> int:
    try:
        return max(1, int(os.getenv("DB_BACKUP_RETENTION_DAYS", "14")))
    except Exception:
        return 14


def _sanitize_db_url_for_logs(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        if not parts.netloc:
            return url
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        user = parts.username or ""
        netloc = f"{user}@{host}{port}" if user else f"{host}{port}"
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return url


def _run_db_backup_once() -> dict:
    enc_key = _db_backup_encryption_key()
    if not enc_key:
        raise RuntimeError("DB_BACKUP_ENCRYPTION_KEY missing")

    db_url = _database_url_runtime()
    kind = _database_kind(db_url)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    backup_dir = _db_backup_dir()
    plain_payload: bytes = b""
    source_ref = ""

    if kind == "sqlite":
        sqlite_path = _sqlite_file_path(db_url)
        if not os.path.exists(sqlite_path):
            raise RuntimeError(f"sqlite_database_not_found:{sqlite_path}")
        source_ref = sqlite_path
        with open(sqlite_path, "rb") as f:
            plain_payload = f.read()
    elif kind == "postgresql":
        source_ref = _sanitize_db_url_for_logs(db_url)
        proc = subprocess.run(
            ["pg_dump", "--no-owner", "--no-privileges", db_url],
            capture_output=True,
            text=False,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
            raise RuntimeError(f"pg_dump_failed:{stderr.strip()}")
        plain_payload = bytes(proc.stdout or b"")
    else:
        raise RuntimeError(f"unsupported_database_kind:{kind}")

    compressed = gzip.compress(plain_payload, compresslevel=9)
    token = Fernet(enc_key.encode("utf-8")).encrypt(compressed)
    file_name = f"db_backup_{kind}_{stamp}.bin.enc"
    file_path = os.path.join(backup_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(token)

    meta = {
        "created_at": now.isoformat(),
        "database_kind": kind,
        "source": source_ref,
        "compressed_bytes": len(compressed),
        "encrypted_bytes": len(token),
        "path": file_path,
    }
    with open(f"{file_path}.meta.json", "w", encoding="utf-8") as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)

    retention_days = _db_backup_retention_days()
    cutoff = _time.time() - (retention_days * 86400)
    for name in os.listdir(backup_dir):
        if not name.startswith("db_backup_"):
            continue
        target = os.path.join(backup_dir, name)
        try:
            if os.path.isfile(target) and os.path.getmtime(target) < cutoff:
                os.remove(target)
        except Exception:
            continue

    return {
        "ok": True,
        "created_at": now.isoformat(),
        "database_kind": kind,
        "backup_path": file_path,
        "source": source_ref,
        "retention_days": retention_days,
    }


def _list_db_backups(limit: int = 30) -> list[dict]:
    backup_dir = _db_backup_dir()
    rows = []
    for name in sorted(os.listdir(backup_dir), reverse=True):
        if not name.endswith(".bin.enc"):
            continue
        full = os.path.join(backup_dir, name)
        if not os.path.isfile(full):
            continue
        rows.append(
            {
                "file": name,
                "path": full,
                "bytes": os.path.getsize(full),
                "modified_at": datetime.fromtimestamp(os.path.getmtime(full), tz=timezone.utc).isoformat(),
            }
        )
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def _infer_alert_context(reason_code: str, title: str, message: str, data: dict) -> dict:
    reason = str(reason_code or "").strip().lower()
    title_l = str(title or "").strip().lower()
    msg_l = str(message or "").strip().lower()
    data_s = json.dumps(data or {}, ensure_ascii=False).lower()
    text = " | ".join([reason, title_l, msg_l, data_s])

    # Exact reason_code mapping has priority over text heuristics.
    if reason in {"insufficient_trades", "no_monitoring_data"}:
        return {
            "probable_cause": "Datos insuficientes para validar el bot en producción.",
            "suggested_action": "Aumentar ventana de pruebas o bajar umbrales mínimos con cautela.",
        }
    if reason in {"consecutive_losses", "max_consecutive_losses"}:
        return {
            "probable_cause": "Racha de pérdidas consecutivas por encima del umbral.",
            "suggested_action": "Pausar bot, validar mercado actual y endurecer reglas de entrada.",
        }
    if reason in {"max_drawdown", "drawdown_limit"}:
        return {
            "probable_cause": "Se superó el drawdown máximo configurado.",
            "suggested_action": "Reducir riesgo (allocation/leverage) y revisar estrategia antes de reactivar.",
        }
    if reason in {"low_profit_factor"}:
        return {
            "probable_cause": "El ratio de beneficio (profit factor) cayó por debajo del mínimo permitido.",
            "suggested_action": "Retirar de producción, revisar entradas/salidas y volver a paper hasta recuperar ratio.",
        }
    if reason in {"auth_failed", "mainnet_auth_failed", "invalid_signature"}:
        return {
            "probable_cause": "Credenciales API inválidas o firma rechazada.",
            "suggested_action": "Revisar wallet/signing key y validar permisos en el entorno seleccionado.",
        }

    if "429" in text or "too many requests" in text or "rate limit" in text:
        return {
            "probable_cause": "Límite de peticiones del exchange (rate limit).",
            "suggested_action": "Reducir frecuencia de consultas y aplicar backoff/reintento.",
        }
    if "auth" in text or "invalid key" in text or "signature" in text or "unauthorized" in text:
        return {
            "probable_cause": "Credenciales API inválidas o firma rechazada.",
            "suggested_action": "Revisar wallet/signing key y validar permisos en el entorno seleccionado.",
        }
    if "drawdown" in text or "max_drawdown" in text:
        return {
            "probable_cause": "Se superó el drawdown máximo configurado.",
            "suggested_action": "Reducir riesgo (allocation/leverage) y revisar estrategia antes de reactivar.",
        }
    if "consecutive_losses" in text or "losses consecutivas" in text or "racha" in text:
        return {
            "probable_cause": "Racha de pérdidas consecutivas por encima del umbral.",
            "suggested_action": "Pausar bot, validar mercado actual y endurecer reglas de entrada.",
        }
    if "insufficient" in text or "min_trades" in text or "no_monitoring_data" in text:
        return {
            "probable_cause": "Datos insuficientes para validar el bot en producción.",
            "suggested_action": "Aumentar ventana de pruebas o bajar umbrales mínimos con cautela.",
        }
    if "snapshot" in text or "account" in text or "could not fetch" in text or "timeout" in text:
        return {
            "probable_cause": "Fallo temporal al consultar cuenta/estado en exchange.",
            "suggested_action": "Reintentar, comprobar conectividad y estado de APIs externas.",
        }

    return {
        "probable_cause": "Condición de guardrail o validación de producción no cumplida.",
        "suggested_action": "Revisar métricas del bot y alertas recientes para ajustar configuración.",
    }


def _env_file_path() -> str:
    return os.path.join(_project_root_path(), ".env")


def _sanitize_asset_key(value: str) -> str:
    key = (value or "").strip().upper()
    safe = []
    for ch in key:
        safe.append(ch if ch.isalnum() else "_")
    out = "".join(safe).strip("_")
    return out or "ASSET"


def _import_data_dir() -> str:
    path = os.path.join(_project_root_path(), "reports", "imported_market_data")
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_candles(candles: list) -> list:
    normalized = []
    for item in candles or []:
        try:
            time_v = int(float(item.get("time")))
            normalized.append(
                {
                    "time": time_v,
                    "open": float(item.get("open")),
                    "high": float(item.get("high")),
                    "low": float(item.get("low")),
                    "close": float(item.get("close")),
                    "volume": float(item.get("volume", 0.0) or 0.0),
                }
            )
        except Exception:
            continue
    normalized.sort(key=lambda c: c["time"])
    return normalized


def _parse_csv_candles(data_str: str) -> list:
    reader = csv.DictReader(io.StringIO(data_str or ""))
    rows = []
    for row in reader:
        rows.append(
            {
                "time": row.get("time"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume", 0.0),
            }
        )
    return _normalize_candles(rows)


def _candles_to_csv(candles: list) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["time", "open", "high", "low", "close", "volume"])
    writer.writeheader()
    for row in candles:
        writer.writerow(row)
    return output.getvalue()


def _timeframe_to_minutes(timeframe: str) -> int:
    tf = (timeframe or "").strip().lower()
    if not tf:
        return 60
    unit = tf[-1]
    value = tf[:-1]
    if not value.isdigit():
        return 60
    qty = int(value)
    if unit == "m":
        return max(1, qty)
    if unit == "h":
        return max(1, qty) * 60
    if unit == "d":
        return max(1, qty) * 1440
    if unit == "w":
        return max(1, qty) * 10080
    return 60


def _compute_candle_analysis(candles: list) -> dict:
    if not candles:
        return {
            "trend_pct": 0.0,
            "volatility_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "range_pct": 0.0,
            "avg_volume": 0.0,
            "last_close": 0.0,
        }

    closes = [float(c.get("close") or 0.0) for c in candles if float(c.get("close") or 0.0) > 0]
    highs = [float(c.get("high") or 0.0) for c in candles if float(c.get("high") or 0.0) > 0]
    lows = [float(c.get("low") or 0.0) for c in candles if float(c.get("low") or 0.0) > 0]
    volumes = [float(c.get("volume") or 0.0) for c in candles]

    returns_pct = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev > 0:
            returns_pct.append(((cur - prev) / prev) * 100)

    volatility_pct = 0.0
    if len(returns_pct) > 1:
        volatility_pct = float(pstdev(returns_pct))
    elif returns_pct:
        volatility_pct = float(mean(returns_pct))

    trend_pct = 0.0
    if len(closes) >= 2 and closes[0] > 0:
        trend_pct = ((closes[-1] - closes[0]) / closes[0]) * 100

    max_drawdown_pct = 0.0
    if closes:
        peak = closes[0]
        max_dd = 0.0
        for price in closes:
            if price > peak:
                peak = price
            if peak > 0:
                dd = ((price - peak) / peak) * 100
                if dd < max_dd:
                    max_dd = dd
        max_drawdown_pct = abs(max_dd)

    range_pct = 0.0
    if highs and lows:
        min_low = min(lows)
        max_high = max(highs)
        if min_low > 0:
            range_pct = ((max_high - min_low) / min_low) * 100

    avg_volume = (sum(volumes) / len(volumes)) if volumes else 0.0
    last_close = closes[-1] if closes else 0.0

    return {
        "trend_pct": round(trend_pct, 3),
        "volatility_pct": round(volatility_pct, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "range_pct": round(range_pct, 3),
        "avg_volume": round(avg_volume, 4),
        "last_close": round(last_close, 6),
    }


def _regime_from_analysis(analysis: dict) -> str:
    trend_pct = float((analysis or {}).get("trend_pct") or 0.0)
    volatility_pct = float((analysis or {}).get("volatility_pct") or 0.0)
    if trend_pct >= 2.5:
        return "bullish"
    if trend_pct <= -2.5:
        return "bearish"
    if abs(trend_pct) < 1.2 and volatility_pct >= 1.8:
        return "sideways_volatile"
    return "sideways"


def _fetch_binance_btc_candles(limit: int = 240) -> list:
    safe_limit = max(48, min(int(limit or 240), 1000))
    params = urllib.parse.urlencode(
        {"symbol": "BTCUSDT", "interval": "1h", "limit": safe_limit}
    )
    url = f"https://api.binance.com/api/v3/klines?{params}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    candles = []
    for row in raw or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        open_time_ms = int(row[0] or 0)
        candles.append(
            {
                "time": datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).isoformat(),
                "open": float(row[1] or 0.0),
                "high": float(row[2] or 0.0),
                "low": float(row[3] or 0.0),
                "close": float(row[4] or 0.0),
                "volume": float(row[5] or 0.0),
            }
        )
    return candles


def _get_market_regime_context() -> dict:
    now_ts = _time.time()
    cache_age = now_ts - float(_market_regime_cache.get("updated_at") or 0.0)
    cached_payload = _market_regime_cache.get("payload")
    if cached_payload and cache_age <= _market_regime_cache_ttl_sec:
        return dict(cached_payload)

    source = "fallback"
    candles = _load_imported_candles("BTC/USDT", "1h")
    if len(candles) >= 48:
        source = "imported"
    else:
        candles = []
        try:
            candles = _fetch_binance_btc_candles(limit=240)
            source = "live"
        except Exception as fetch_err:
            print(f"[MarketRegime] failed to fetch live BTC candles: {fetch_err}")

    if candles:
        analysis = _compute_candle_analysis(candles[-240:])
        regime = _regime_from_analysis(analysis)
        payload = {
            "regime": regime,
            "trend_pct": float(analysis.get("trend_pct") or 0.0),
            "volatility_pct": float(analysis.get("volatility_pct") or 0.0),
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        payload = {
            "regime": "mixed",
            "trend_pct": 0.0,
            "volatility_pct": 0.0,
            "source": "fallback",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    _market_regime_cache["updated_at"] = now_ts
    _market_regime_cache["payload"] = dict(payload)
    return payload


def _import_file_path(symbol: str, timeframe: str) -> str:
    file_name = f"{_sanitize_asset_key(symbol)}__{_sanitize_asset_key(timeframe)}.json"
    return os.path.join(_import_data_dir(), file_name)


def _save_imported_candles(symbol: str, timeframe: str, candles: list):
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "candles": candles,
    }
    with open(_import_file_path(symbol, timeframe), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _load_imported_candles(symbol: str, timeframe: str) -> list:
    path = _import_file_path(symbol, timeframe)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return _normalize_candles(payload.get("candles") or [])


def _read_env_values() -> dict:
    path = _env_file_path()
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _write_env_values(updates: dict):
    path = _env_file_path()
    existing = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read().splitlines()

    found = set()
    out = []
    for raw in existing:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in raw:
            key, _ = raw.split("=", 1)
            key = key.strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                found.add(key)
                continue
        out.append(raw)

    for key, value in updates.items():
        if key not in found:
            out.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")


def _persist_env_updates(updates: dict):
    """Escribe .env y actualiza os.environ para que el proceso vea los cambios sin reiniciar."""
    _write_env_values(updates)
    for key, value in updates.items():
        os.environ[key] = str(value)


def _mask_wallet(wallet: str) -> str:
    if not wallet or len(wallet) < 10:
        return ""
    return f"{wallet[:8]}...{wallet[-6:]}"


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _compute_consecutive_losses(scored_pnls: list[float]) -> int:
    streak = 0
    for pnl in reversed(scored_pnls or []):
        if pnl < 0:
            streak += 1
        else:
            break
    return streak


def _compute_max_drawdown_abs(scored_pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in scored_pnls or []:
        equity += float(pnl)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _adaptive_parameter_recommendation(strategy: str, config: dict, metrics: dict) -> dict:
    strategy = (strategy or "").lower()
    cfg = dict(config or {})
    scored_trades = int(metrics.get("scored_trades") or 0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    net_pnl = float(metrics.get("net_pnl") or 0.0)
    consecutive_losses = int(metrics.get("consecutive_losses") or 0)
    max_drawdown_abs = float(metrics.get("max_drawdown_abs") or 0.0)

    suggested_params = {}
    rationale = []
    level = "maintain"

    if scored_trades < 5:
        level = "insufficient_data"
        rationale.append("Muestra corta: menos de 5 trades con PnL real.")
        if "pair" in strategy:
            suggested_params["pair_entry_z"] = round(max(1.0, float(cfg.get("pair_entry_z", 1.4)) - 0.1), 3)
            suggested_params["pair_min_correlation"] = round(max(0.15, float(cfg.get("pair_min_correlation", 0.35)) - 0.05), 3)
            rationale.append("Reducir levemente filtros del pair para acelerar validación estadística.")
        return {
            "level": level,
            "summary": "Datos insuficientes para un ajuste fuerte.",
            "suggested_params": suggested_params,
            "rationale": rationale,
        }

    if win_rate < 45 or net_pnl < 0 or consecutive_losses >= 4:
        level = "defensive"
        rationale.append("Rendimiento débil o racha de pérdidas detectada.")

        current_alloc = float(cfg.get("allocation", cfg.get("capital_allocation", 100.0)) or 100.0)
        suggested_alloc = max(20.0, current_alloc * 0.85)
        suggested_params["allocation"] = round(suggested_alloc, 4)
        suggested_params["capital_allocation"] = round(suggested_alloc, 4)

        current_risk = dict(cfg.get("risk_config") or {})
        current_dd = float(current_risk.get("max_drawdown", 0.05) or 0.05)
        current_risk["max_drawdown"] = round(max(0.015, current_dd - 0.005), 4)
        suggested_params["risk_config"] = current_risk

        if "ema_cross" in strategy:
            fast = int(cfg.get("fast_ema", 9) or 9)
            slow = int(cfg.get("slow_ema", 21) or 21)
            suggested_params["fast_ema"] = min(30, fast + 1)
            suggested_params["slow_ema"] = min(80, max(slow + 3, fast + 5))
            rationale.append("EMA más conservadora para reducir sobre-operación.")
        elif "grid_trading" in strategy:
            grids = int(cfg.get("num_grids", 10) or 10)
            suggested_params["num_grids"] = min(30, grids + 2)
            rationale.append("Mayor densidad de rejilla para mejorar promedio de entradas.")
        elif "adaptive_learning" in strategy:
            min_flip = float(cfg.get("adaptive_min_flip_move_pct", 0.002) or 0.002)
            min_reentry = float(cfg.get("adaptive_min_reentry_move_pct", 0.0012) or 0.0012)
            suggested_params["adaptive_min_flip_move_pct"] = round(min_flip * 1.2, 6)
            suggested_params["adaptive_min_reentry_move_pct"] = round(min_reentry * 1.15, 6)
            suggested_params["adaptive_base_amount"] = round(max(0.001, float(cfg.get("adaptive_base_amount", 0.01) or 0.01) * 0.9), 6)
            rationale.append("Subir umbral de flip y bajar tamaño base para controlar drawdown.")
        elif "pair" in strategy:
            suggested_params["pair_entry_z"] = round(min(2.2, float(cfg.get("pair_entry_z", 1.4) or 1.4) + 0.1), 3)
            suggested_params["pair_exit_z"] = round(min(0.8, float(cfg.get("pair_exit_z", 0.25) or 0.25) + 0.05), 3)
            suggested_params["pair_min_correlation"] = round(min(0.85, float(cfg.get("pair_min_correlation", 0.35) or 0.35) + 0.05), 3)
            rationale.append("Endurecer filtro de entrada pair para evitar setups débiles.")
    elif win_rate >= 58 and net_pnl > 0 and consecutive_losses <= 2:
        level = "offensive"
        rationale.append("Rendimiento sólido y consistente en ventana reciente.")

        current_alloc = float(cfg.get("allocation", cfg.get("capital_allocation", 100.0)) or 100.0)
        suggested_alloc = min(current_alloc * 1.12, current_alloc + max(20.0, abs(net_pnl) * 0.35))
        suggested_params["allocation"] = round(suggested_alloc, 4)
        suggested_params["capital_allocation"] = round(suggested_alloc, 4)

        if "adaptive_learning" in strategy:
            suggested_params["reinvest_ratio"] = round(min(0.5, float(cfg.get("reinvest_ratio", 0.35) or 0.35) + 0.05), 4)
        if "pair" in strategy:
            suggested_params["pair_entry_z"] = round(max(1.0, float(cfg.get("pair_entry_z", 1.4) or 1.4) - 0.05), 3)
            suggested_params["pair_take_profit_pct"] = round(min(0.02, float(cfg.get("pair_take_profit_pct", 0.01) or 0.01) + 0.001), 4)
    else:
        rationale.append("Desempeño mixto: mantener configuración con ajustes menores.")

    summary = (
        f"win_rate={win_rate:.2f}% · net_pnl={net_pnl:.4f} · "
        f"loss_streak={consecutive_losses} · max_dd={max_drawdown_abs:.4f}"
    )
    return {
        "level": level,
        "summary": summary,
        "suggested_params": suggested_params,
        "rationale": rationale,
    }


def _bot_config_from_prompt(prompt: str, symbol: str, allocation: float) -> dict:
    prompt_text = (prompt or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="prompt is required")

    p = prompt_text.lower()
    normalized_symbol = (symbol or "BTC/USDT").strip() or "BTC/USDT"
    safe_allocation = max(20.0, float(allocation or 500.0))

    strategy = "ema_cross"
    if any(k in p for k in ["pair", "paired", "cointegration", "zscore", "z-score", "correl"]):
        strategy = "paired_balanced"
    elif any(k in p for k in ["grid", "rejilla", "rango", "range"]):
        strategy = "grid_trading"
    elif any(k in p for k in [
        "adaptive", "aprendiz", "learning", "reinvert", "scalp", "micro",
        "intradia", "intradia", "movimientos", "porcentaje", "pequeno", "pequenos",
        "comprar barato", "comprar barato vender caro",
    ]):
        strategy = "adaptive_learning"
    elif any(k in p for k in ["rsi", "macd", "fib", "fibonacci", "technical"]):
        strategy = "technical_pro"

    risk_level = "medium"
    if any(k in p for k in ["conserv", "bajo riesgo", "defens", "estable", "segur"]):
        risk_level = "low"
    elif any(k in p for k in ["agres", "alto riesgo", "ofens", "volatil", "apalanc"]):
        risk_level = "high"

    horizon = "medio"
    if any(k in p for k in ["scalp", "intradia", "intradía", "corto", "rápido", "rapido"]):
        horizon = "corto"
    elif any(k in p for k in ["largo", "swing", "seman", "mensual", "tendencia larga"]):
        horizon = "largo"

    cfg = {
        "strategy": strategy,
        "symbol": normalized_symbol,
        "executor": "paper",
        "capital_allocation": round(safe_allocation, 4),
        "allocation": round(safe_allocation, 4),
        "risk_config": {"max_drawdown": 0.05},
    }

    if strategy == "ema_cross":
        if horizon == "corto":
            cfg.update({"fast_ema": 7, "slow_ema": 18})
        elif horizon == "largo":
            cfg.update({"fast_ema": 20, "slow_ema": 55})
        else:
            cfg.update({"fast_ema": 9, "slow_ema": 21})
    elif strategy == "grid_trading":
        cfg.update({"upper_limit": 70000, "lower_limit": 60000, "num_grids": 10})
        if risk_level == "low":
            cfg["num_grids"] = 14
        elif risk_level == "high":
            cfg["num_grids"] = 8
    elif strategy == "paired_balanced":
        cfg.update(
            {
                "allow_short": True,
                "pair_symbol_a": normalized_symbol,
                "pair_symbol_b": "ETH/USDT",
                "pair_entry_z": 1.4,
                "pair_exit_z": 0.25,
                "pair_stop_loss_pct": 0.015,
                "pair_take_profit_pct": 0.01,
                "pair_profit_lock_pct": 0.004,
                "pair_min_correlation": 0.35,
            }
        )
        if risk_level == "low":
            cfg["pair_entry_z"] = 1.6
            cfg["pair_min_correlation"] = 0.45
        elif risk_level == "high":
            cfg["pair_entry_z"] = 1.2
            cfg["pair_min_correlation"] = 0.25
    elif strategy == "adaptive_learning":
        cfg.update(
            {
                "adaptive_short_window": 10,
                "adaptive_long_window": 36,
                "adaptive_base_amount": 0.008,
                "adaptive_min_flip_move_pct": 0.002,
                "adaptive_min_reentry_move_pct": 0.0012,
                "self_managed": True,
                "reinvest_ratio": 0.25,
                "min_allocation": round(max(60.0, safe_allocation * 0.35), 4),
                "max_allocation": round(max(500.0, safe_allocation * 2.8), 4),
                "leverage": 1,
            }
        )
        if horizon == "corto":
            cfg.update(
                {
                    "adaptive_short_window": 6,
                    "adaptive_long_window": 22,
                    "adaptive_base_amount": 0.006,
                    "adaptive_min_flip_move_pct": 0.0016,
                    "adaptive_min_reentry_move_pct": 0.0009,
                    "reinvest_ratio": 0.2,
                }
            )
        elif horizon == "largo":
            cfg.update(
                {
                    "adaptive_short_window": 14,
                    "adaptive_long_window": 55,
                    "adaptive_base_amount": 0.01,
                    "adaptive_min_flip_move_pct": 0.003,
                    "adaptive_min_reentry_move_pct": 0.0018,
                    "reinvest_ratio": 0.3,
                }
            )

    if risk_level == "low":
        cfg["risk_config"] = {"max_drawdown": 0.03}
    elif risk_level == "high":
        cfg["risk_config"] = {"max_drawdown": 0.08}

    return {
        "config": cfg,
        "meta": {
            "detected_strategy": strategy,
            "risk_level": risk_level,
            "horizon": horizon,
            "source": "prompt",
        },
    }


def _cfg_hyperliquid_testnet(cfg: dict) -> bool:
    """True si Hyperliquid está en testnet (explícito en config o por defecto env)."""
    conf = dict(cfg or {})
    if "hyperliquid_testnet" in conf and conf.get("hyperliquid_testnet") is not None:
        return bool(conf.get("hyperliquid_testnet"))
    return os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"


def _is_live_mainnet_config(cfg: dict) -> bool:
    conf = dict(cfg or {})
    executor = str(conf.get("executor") or "paper").strip().lower()
    if executor != "hyperliquid":
        return False
    return not _cfg_hyperliquid_testnet(conf)


def _analysis_gate_ok(cfg: dict) -> bool:
    conf = dict(cfg or {})
    return bool(
        conf.get("analysis_approved")
        or conf.get("candidate_for_production")
        or conf.get("production_ready")
    )


def _evaluate_production_readiness(
    *,
    strategy: str,
    metrics: dict,
    critical_open_count: int,
    runtime_ready: bool,
    min_scored_trades: int,
    market_regime_context: dict | None = None,
) -> dict:
    strategy_l = str(strategy or "").strip().lower()
    regime_ctx = dict(market_regime_context or {})
    regime = str(regime_ctx.get("regime") or "mixed").strip().lower()

    # Strategy-aware thresholds: tuned to accelerate promotion without weakening safety.
    min_win_rate = 55.0
    min_profit_factor = 1.05
    min_trades_required = int(min_scored_trades)
    if "grid" in strategy_l:
        min_trades_required = max(6, int(min_scored_trades) - 1)
    elif "adaptive" in strategy_l:
        min_win_rate = 56.0
        min_profit_factor = 1.04
    elif "pair" in strategy_l:
        min_win_rate = 57.0
        min_profit_factor = 1.06
        min_trades_required = max(10, int(min_scored_trades))

    # Regime-aware dynamic guardrails (bull/bear/sideways).
    strategy_is_trend = any(k in strategy_l for k in ["ema", "technical", "adaptive"])
    strategy_is_mean_reversion = any(k in strategy_l for k in ["grid", "pair"])
    if regime == "bullish":
        if strategy_is_trend:
            min_win_rate -= 1.0
            min_trades_required = max(5, min_trades_required - 1)
        elif strategy_is_mean_reversion:
            min_profit_factor += 0.02
    elif regime == "bearish":
        if strategy_is_mean_reversion:
            min_win_rate -= 1.0
            min_trades_required = max(5, min_trades_required - 1)
        elif strategy_is_trend:
            min_profit_factor += 0.03
            min_trades_required = min_trades_required + 1
    elif regime == "sideways_volatile":
        min_profit_factor += 0.03
        min_trades_required = min_trades_required + 1
    elif regime == "sideways":
        min_profit_factor += 0.01

    scored_trades = int(metrics.get("scored_trades") or 0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    net_pnl = float(metrics.get("net_pnl") or 0.0)
    profit_factor = float(metrics.get("profit_factor") or 0.0)
    consecutive_losses = int(metrics.get("consecutive_losses") or 0)

    checks = [
        {
            "code": "min_scored_trades",
            "ok": scored_trades >= min_trades_required,
            "actual": scored_trades,
            "required": f">={min_trades_required}",
            "message": f"Trades válidos {scored_trades}/{min_trades_required}",
        },
        {
            "code": "min_win_rate",
            "ok": win_rate >= min_win_rate,
            "actual": round(win_rate, 2),
            "required": f">={min_win_rate}",
            "message": f"Win rate {round(win_rate, 2)}% (mínimo {min_win_rate}%)",
        },
        {
            "code": "positive_net_pnl",
            "ok": net_pnl > 0.0,
            "actual": round(net_pnl, 6),
            "required": ">0",
            "message": f"Net PnL {round(net_pnl, 6)} (debe ser positivo)",
        },
        {
            "code": "min_profit_factor",
            "ok": profit_factor >= min_profit_factor,
            "actual": round(profit_factor, 4),
            "required": f">={min_profit_factor}",
            "message": f"Profit factor {round(profit_factor, 4)} (mínimo {min_profit_factor})",
        },
        {
            "code": "max_consecutive_losses",
            "ok": consecutive_losses <= 2,
            "actual": consecutive_losses,
            "required": "<=2",
            "message": f"Pérdidas consecutivas {consecutive_losses} (máximo 2)",
        },
        {
            "code": "critical_alerts",
            "ok": critical_open_count == 0,
            "actual": critical_open_count,
            "required": "==0",
            "message": f"Alertas críticas abiertas {critical_open_count} (deben ser 0)",
        },
    ]

    gate_ok = all(bool(item.get("ok")) for item in checks)
    operational_checks = [
        {
            "code": "runtime_running",
            "ok": runtime_ready,
            "actual": "running" if runtime_ready else "stopped",
            "required": "running",
            "message": "Bot en ejecución para promoción automática",
        }
    ]

    blockers = [item["message"] for item in checks if not item.get("ok")]
    if gate_ok:
        summary = "APTO PRODUCCION: métricas y guardrails superados"
    else:
        summary = "NO APTO / BLOQUEADO: " + " | ".join(blockers)

    return {
        "gate_ok": gate_ok,
        "label": "APTO PRODUCCION" if gate_ok else "NO APTO / BLOQUEADO",
        "summary": summary,
        "strategy": strategy,
        "market_regime": regime,
        "thresholds": {
            "min_scored_trades": min_trades_required,
            "min_win_rate": min_win_rate,
            "min_profit_factor": min_profit_factor,
            "min_net_pnl": 0.0,
            "max_consecutive_losses": 2,
            "critical_alerts": 0,
        },
        "checks": checks,
        "operational_checks": operational_checks,
        "blockers": blockers,
    }


def _recommended_action_for_blockers(blockers: list) -> str:
    text = " | ".join(str(b or "") for b in (blockers or [])).lower()
    if "trades válidos" in text:
        return "Mantener bot en paper/running con menor filtro de entrada hasta reunir muestra mínima."
    if "win rate" in text:
        return "Reducir riesgo (allocation/leverage) y endurecer entrada antes de volver a evaluar."
    if "net pnl" in text:
        return "Pausar escalado y optimizar parámetros de salida/stop para recuperar PnL neto positivo."
    if "profit factor" in text:
        return "Ajustar relación riesgo/beneficio (take profit y control de pérdidas) hasta PF objetivo."
    if "alertas críticas" in text:
        return "Resolver y cerrar alertas críticas abiertas antes de cualquier promoción."
    if "detenido" in text:
        return "Arrancar bot en paper/running para generar datos recientes antes de promover."
    return "Revisar bloqueadores y aplicar recomendación adaptativa antes de siguiente ciclo."


def _build_blockers_ranking_report(db: Session, *, lookback_hours: int, min_scored_trades: int) -> dict:
    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    rows = []
    for item in monitoring.get("results", []):
        readiness = dict(item.get("readiness") or {})
        if bool(readiness.get("gate_ok")):
            continue

        blockers = list(readiness.get("blockers") or [])
        rows.append(
            {
                "bot_id": item.get("bot_id"),
                "strategy": item.get("strategy"),
                "label": readiness.get("label") or "NO APTO / BLOQUEADO",
                "summary": readiness.get("summary") or "No apto para producción",
                "blockers": blockers,
                "recommended_action": _recommended_action_for_blockers(blockers),
                "metrics": item.get("metrics") or {},
            }
        )

    rows.sort(
        key=lambda r: (
            len(r.get("blockers") or []),
            -float((r.get("metrics") or {}).get("scored_trades") or 0.0),
            float((r.get("metrics") or {}).get("net_pnl") or 0.0),
        ),
        reverse=True,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "blocked_count": len(rows),
        "rows": rows,
    }


def _strict_production_policy_from_metrics(*, strategy: str, allocation: float, min_scored_trades: int, recommendation_level: str) -> dict:
    alloc = max(20.0, float(allocation or 0.0))
    strategy_l = str(strategy or "").strip().lower()
    level = str(recommendation_level or "").strip().lower()

    min_win_rate = 55.0
    min_profit_factor = 1.05
    min_trades = int(min_scored_trades)

    if "grid" in strategy_l:
        min_win_rate = 53.0
        min_profit_factor = 1.03
        min_trades = max(6, int(min_scored_trades) - 1)
    elif "adaptive" in strategy_l:
        min_win_rate = 55.0
        min_profit_factor = 1.04
    elif "pair" in strategy_l:
        min_win_rate = 57.0
        min_profit_factor = 1.06
        min_trades = max(10, int(min_scored_trades))

    if level == "defensive":
        min_win_rate = max(min_win_rate, 58.0)
        min_profit_factor = max(min_profit_factor, 1.08)
    elif level == "offensive":
        min_win_rate = max(52.0, min_win_rate - 1.0)
        min_profit_factor = max(1.02, min_profit_factor - 0.01)

    max_loss_abs = round(min(25.0, max(2.0, alloc * 0.015)), 4)

    return {
        "enabled": True,
        "window_trades": max(30, int(min_trades) * 3),
        "min_trades": int(min_trades),
        "min_win_rate": min_win_rate,
        "min_net_pnl": 0.0,
        "min_profit_factor": min_profit_factor,
        "max_consecutive_losses": 2,
        "max_loss_abs": max_loss_abs,
        "max_loss_pct_of_allocation": 0.015,
        "stop_on_unproductive": True,
    }


def _build_production_preparation_patch(*, item: dict, min_scored_trades: int) -> dict:
    metrics = dict(item.get("metrics") or {})
    recommendation = dict(item.get("recommendation") or {})
    rec_params = dict(recommendation.get("suggested_params") or {})
    candidate = bool(item.get("candidate_for_production"))
    strategy = str(item.get("strategy") or "")

    allocation = float(
        rec_params.get("allocation")
        or rec_params.get("capital_allocation")
        or metrics.get("net_pnl")
        or 100.0
    )
    allocation = max(20.0, abs(allocation))

    patch = dict(rec_params)
    patch["allocation"] = float(patch.get("allocation") or allocation)
    patch["capital_allocation"] = float(patch.get("capital_allocation") or patch.get("allocation") or allocation)
    patch["production_policy"] = _strict_production_policy_from_metrics(
        strategy=strategy,
        allocation=float(patch.get("capital_allocation") or allocation),
        min_scored_trades=min_scored_trades,
        recommendation_level=str(recommendation.get("level") or ""),
    )
    patch["analysis_approved"] = candidate
    patch["candidate_for_production"] = candidate
    patch["production_ready"] = candidate

    return patch


def _build_monitoring_test_results(db: Session, lookback_hours: int, min_scored_trades: int) -> dict:
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    market_regime_context = _get_market_regime_context()
    bots = db.query(BotDB).filter(BotDB.is_archived == False).all()
    trades = db.query(TradeDB).filter(TradeDB.time >= since).order_by(TradeDB.time.asc()).all()
    open_critical_alerts = (
        db.query(BotAlertDB)
        .filter(BotAlertDB.acknowledged == False, BotAlertDB.level == "critical")
        .all()
    )

    critical_map = {}
    for alert in open_critical_alerts:
        critical_map.setdefault(alert.bot_id, 0)
        critical_map[alert.bot_id] += 1

    grouped = {}
    for trade in trades:
        grouped.setdefault(trade.bot_id, []).append(trade)

    results = []
    for bot in bots:
        bot_trades = grouped.get(bot.id, [])
        scored = [float(t.pnl or 0.0) for t in bot_trades if float(t.pnl or 0.0) != 0.0]
        wins = sum(1 for pnl in scored if pnl > 0)
        losses = sum(1 for pnl in scored if pnl < 0)
        total_pnl = sum(float(t.pnl or 0.0) for t in bot_trades)
        total_fees = sum(float(t.fee or 0.0) for t in bot_trades)
        net_pnl = total_pnl - total_fees
        win_rate = (wins / len(scored) * 100) if scored else 0.0
        consecutive_losses = _compute_consecutive_losses(scored)
        max_drawdown_abs = _compute_max_drawdown_abs(scored)
        gross_profit = sum(pnl for pnl in scored if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in scored if pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        last_trade_at = bot_trades[-1].time if bot_trades else None

        metrics = {
            "total_trades": len(bot_trades),
            "scored_trades": len(scored),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 6),
            "total_fees": round(total_fees, 6),
            "net_pnl": round(net_pnl, 6),
            "avg_pnl_scored": round((sum(scored) / len(scored)) if scored else 0.0, 6),
            "consecutive_losses": consecutive_losses,
            "max_drawdown_abs": round(max_drawdown_abs, 6),
            "profit_factor": round(profit_factor, 4),
        }

        recommendation = _adaptive_parameter_recommendation(
            strategy=str(bot.strategy or ""),
            config=dict(bot.config or {}),
            metrics=metrics,
        )

        critical_open_count = int(critical_map.get(bot.id, 0) or 0)
        runtime_ready = str(bot.status or "").lower() == BotStatus.RUNNING
        readiness = _evaluate_production_readiness(
            strategy=str(bot.strategy or ""),
            metrics=metrics,
            critical_open_count=critical_open_count,
            runtime_ready=runtime_ready,
            min_scored_trades=min_scored_trades,
            market_regime_context=market_regime_context,
        )
        candidate_core = bool(readiness.get("gate_ok"))

        results.append(
            {
                "bot_id": bot.id,
                "strategy": bot.strategy,
                "status": bot.status,
                "last_trade_at": last_trade_at,
                "critical_open_alerts": critical_open_count,
                "candidate_for_production": candidate_core,
                "runtime_ready": runtime_ready,
                "metrics": metrics,
                "readiness": readiness,
                "recommendation": recommendation,
            }
        )

    results.sort(
        key=lambda item: (
            bool(item.get("candidate_for_production")),
            float(item.get("metrics", {}).get("net_pnl", 0.0)),
            float(item.get("metrics", {}).get("win_rate", 0.0)),
        ),
        reverse=True,
    )

    top_candidates = [item for item in results if item.get("candidate_for_production")][:5]
    profitable_count = sum(1 for item in results if float(item.get("metrics", {}).get("net_pnl", 0.0)) > 0)

    return {
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "market_regime": market_regime_context,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "bots_analyzed": len(results),
            "profitable_bots": profitable_count,
            "production_candidates": len(top_candidates),
            "critical_alerts_open": len(open_critical_alerts),
        },
        "top_candidates": top_candidates,
        "results": results,
    }


def _public_account_value(wallet: str, use_testnet: bool) -> float:
    return float(_public_account_snapshot(wallet, use_testnet).get("account_value") or 0.0)


def _public_account_snapshot(wallet: str, use_testnet: bool) -> dict:
    if not wallet:
        return {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }

    url = "https://api.hyperliquid-testnet.xyz/info" if use_testnet else "https://api.hyperliquid.xyz/info"
    payload = json.dumps({"type": "clearinghouseState", "user": wallet}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    margin = data.get("marginSummary") or {}
    account_value = float(margin.get("accountValue") or 0.0)
    withdrawable = float(data.get("withdrawable") or 0.0)
    exposure_notional = abs(float(margin.get("totalNtlPos") or 0.0))
    margin_used = max(account_value - withdrawable, 0.0)

    return {
        "account_value": account_value,
        "withdrawable": withdrawable,
        "margin_used": margin_used,
        "exposure_notional": exposure_notional,
    }


def _margin_usage_pct(snapshot: dict) -> float:
    try:
        account_value = float(snapshot.get("account_value") or 0.0)
        margin_used = float(snapshot.get("margin_used") or 0.0)
        if account_value <= 0:
            return 0.0
        return round((margin_used / account_value) * 100, 4)
    except Exception:
        return 0.0


async def _check_private_auth(wallet: str, signing_key: str, use_testnet: bool) -> tuple[bool, str]:
    exchange = ccxt.hyperliquid({"privateKey": signing_key, "walletAddress": wallet})
    if use_testnet:
        exchange.set_sandbox_mode(True)
    try:
        await exchange.fetch_balance()
        return True, "ok"
    except Exception as e:
        return False, str(e)
    finally:
        await exchange.close()


async def _sync_positions_with_best_executor() -> dict:
    env = _read_env_values()
    wallet = env.get("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = env.get("HYPERLIQUID_SIGNING_KEY", "")
    use_testnet = str(env.get("HYPERLIQUID_USE_TESTNET", "True")).strip().lower() == "true"

    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)

    executor_name = "paper"
    if wallet_ok and key_ok:
        os.environ["HYPERLIQUID_WALLET_ADDRESS"] = wallet
        os.environ["HYPERLIQUID_SIGNING_KEY"] = signing_key
        os.environ["HYPERLIQUID_USE_TESTNET"] = "True" if use_testnet else "False"
        executor = HyperliquidExecutor(use_testnet=use_testnet)
        executor_name = "hyperliquid_testnet" if use_testnet else "hyperliquid_mainnet"
    else:
        from apps.engine.paper_executor import PaperTradingExecutor

        executor = PaperTradingExecutor()

    sync_service = PositionSyncService(executor)
    results = await sync_service.sync_positions()
    results["executor"] = executor_name
    return results


def _append_production_activation_event(event: dict) -> None:
    try:
        reports_dir = os.path.join(_project_root_path(), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        file_path = os.path.join(reports_dir, f"production_activation_events_{day}.jsonl")
        with open(file_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        pass


def _audit_production_activation(
    db: Session,
    *,
    bot_id: str,
    trigger: str,
    activated: bool,
    reason: str,
    details: dict,
) -> None:
    timestamp = datetime.now(timezone.utc)
    title = "Auto activación a producción" if trigger.startswith("auto") else "Activación a producción"
    level = "info" if activated else "warning"
    message = (
        f"{title}: bot {bot_id} ACTIVADO en real market"
        if activated
        else f"{title}: bot {bot_id} BLOQUEADO ({reason})"
    )
    reason_code = "auto_prod_activated" if activated else "auto_prod_blocked"

    alert = BotAlertDB(
        bot_id=bot_id,
        level=level,
        title=title,
        message=message,
        reason_code=reason_code,
        data={"trigger": trigger, "reason": reason, "details": details},
        acknowledged=False,
    )
    db.add(alert)

    _append_production_activation_event(
        {
            "time": timestamp.isoformat(),
            "bot_id": bot_id,
            "trigger": trigger,
            "activated": activated,
            "reason": reason,
            "details": details,
        }
    )


async def _activate_bot_for_production_internal(
    db: Session,
    *,
    bot_id: str,
    lookback_hours: int,
    min_scored_trades: int,
    trigger: str,
) -> dict:
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        result = {"activated": False, "bot_id": bot_id, "reason": "bot_not_found"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_not_found", details={})
        db.commit()
        return result
    if bot_entry.is_archived:
        result = {"activated": False, "bot_id": bot_id, "reason": "bot_archived"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_archived", details={})
        db.commit()
        return result

    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    selected = next((item for item in monitoring.get("results", []) if item.get("bot_id") == bot_id), None)
    if not selected:
        result = {"activated": False, "bot_id": bot_id, "reason": "no_monitoring_data"}
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="no_monitoring_data", details={})
        db.commit()
        return result

    if not selected.get("candidate_for_production"):
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "bot_not_ready_for_production",
            "metrics": selected.get("metrics"),
            "critical_open_alerts": selected.get("critical_open_alerts"),
            "readiness": selected.get("readiness"),
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="bot_not_ready_for_production",
            details={
                "metrics": selected.get("metrics"),
                "critical_open_alerts": selected.get("critical_open_alerts"),
                "readiness": selected.get("readiness"),
            },
        )
        db.commit()
        return result

    cfg = dict(bot_entry.config or {})
    executor = str(cfg.get("executor") or "paper").lower()
    if executor != "hyperliquid":
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "executor_not_hyperliquid",
            "message": "Bot must use hyperliquid executor for real production activation",
            "suggested_patch": {"executor": "hyperliquid", "hyperliquid_testnet": False},
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="executor_not_hyperliquid", details={"executor": executor})
        db.commit()
        return result

    if _as_bool(cfg.get("hyperliquid_testnet"), default=False):
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "bot_configured_for_testnet",
            "message": "Set hyperliquid_testnet=false to allow real market production activation",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="bot_configured_for_testnet", details={})
        db.commit()
        return result

    env = _read_env_values()
    wallet = env.get("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = env.get("HYPERLIQUID_SIGNING_KEY", "")
    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)
    if not wallet_ok or not key_ok:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "invalid_hyperliquid_credentials",
            "message": "Hyperliquid credentials are not valid in settings",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="invalid_hyperliquid_credentials", details={})
        db.commit()
        return result

    mainnet_auth_ok, mainnet_auth_error = await _check_private_auth(wallet, signing_key, False)
    if not mainnet_auth_ok:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_auth_failed",
            "message": f"Mainnet auth failed: {mainnet_auth_error}",
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="mainnet_auth_failed",
            details={"error": mainnet_auth_error},
        )
        db.commit()
        return result

    try:
        mainnet_account_value = _public_account_value(wallet, False)
    except Exception as e:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_account_check_failed",
            "message": str(e),
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="mainnet_account_check_failed", details={"error": str(e)})
        db.commit()
        return result

    if mainnet_account_value <= 0:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "mainnet_account_empty",
            "message": "Mainnet account value is 0. Fund account before production activation",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="mainnet_account_empty", details={"mainnet_account_value": mainnet_account_value})
        db.commit()
        return result

    if bot_id in bot_manager.active_bots:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "already_running",
            "mainnet_account_value": mainnet_account_value,
        }
        _audit_production_activation(
            db,
            bot_id=bot_id,
            trigger=trigger,
            activated=False,
            reason="already_running",
            details={"mainnet_account_value": mainnet_account_value},
        )
        db.commit()
        return result

    started = bot_manager.start_bot(bot_id, cfg)
    if not started:
        result = {
            "activated": False,
            "bot_id": bot_id,
            "reason": "start_failed",
            "message": "Bot failed to start in production mode",
        }
        _audit_production_activation(db, bot_id=bot_id, trigger=trigger, activated=False, reason="start_failed", details={})
        db.commit()
        return result

    bot_entry.status = BotStatus.RUNNING
    result = {
        "activated": True,
        "bot_id": bot_id,
        "mode": "production",
        "mainnet_account_value": round(mainnet_account_value, 4),
        "monitoring_snapshot": {
            "win_rate": selected.get("metrics", {}).get("win_rate"),
            "net_pnl": selected.get("metrics", {}).get("net_pnl"),
            "scored_trades": selected.get("metrics", {}).get("scored_trades"),
        },
    }
    _audit_production_activation(
        db,
        bot_id=bot_id,
        trigger=trigger,
        activated=True,
        reason="activated",
        details={
            "mainnet_account_value": result.get("mainnet_account_value"),
            "monitoring_snapshot": result.get("monitoring_snapshot"),
        },
    )
    db.commit()
    return result


async def _db_backup_loop():
    global _db_backup_loop_running
    interval = _db_backup_interval_sec()
    while _db_backup_loop_running:
        try:
            info = _run_db_backup_once()
            print(
                "[DBBackup] ok "
                f"kind={info.get('database_kind')} file={info.get('backup_path')} retention={info.get('retention_days')}d"
            )
        except Exception as e:
            print(f"[DBBackup] error: {e}")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def startup_event():
    global _auto_production_loop_running, _auto_production_loop_task
    global _daily_blockers_loop_running, _daily_blockers_loop_task
    global _db_backup_loop_running, _db_backup_loop_task
    load_dotenv(_env_file_path(), override=True)
    init_db()
    if _auth_enabled() and not _auth_is_configured():
        raise RuntimeError("APP_AUTH_ENABLED=true requires APP_AUTH_PASSWORD_HASH + APP_AUTH_SECRET_KEY (+ APP_AUTH_TOTP_SECRET if TOTP enabled)")
    if _auth_totp_enabled() and not _totp_secret_valid(_auth_totp_secret()):
        raise RuntimeError("APP_AUTH_TOTP_SECRET must be a valid base32 secret")
    if _db_backup_enabled() and not _db_backup_encryption_key():
        raise RuntimeError("DB_BACKUP_ENABLED=true requires DB_BACKUP_ENCRYPTION_KEY")
    try:
        await asyncio.wait_for(bot_manager.resume_bots(), timeout=20)
    except Exception as e:
        print(f"[Startup] resume_bots skipped: {e}")

    try:
        await asyncio.wait_for(production_guard.start(), timeout=10)
    except Exception as e:
        print(f"[Startup] production_guard start skipped: {e}")

    if adaptive_orchestrator.enabled:
        try:
            await asyncio.wait_for(adaptive_orchestrator.start(), timeout=10)
        except Exception as e:
            print(f"[Startup] adaptive_orchestrator start skipped: {e}")

    if paper_monitor_runtime.enabled:
        try:
            await asyncio.wait_for(paper_monitor_runtime.start(trigger="startup"), timeout=10)
        except Exception as e:
            print(f"[Startup] paper_monitor_runtime start skipped: {e}")

    if _auto_production_promotion_enabled and (_auto_production_loop_task is None or _auto_production_loop_task.done()):
        _auto_production_loop_running = True
        _auto_production_loop_task = asyncio.create_task(_auto_production_promotion_loop())
        print(
            "[Startup] auto production promotion loop enabled "
            f"(interval={_auto_production_promotion_interval_sec}s, min_trades={_auto_production_min_scored_trades})"
        )

    if _daily_blockers_enabled and (_daily_blockers_loop_task is None or _daily_blockers_loop_task.done()):
        _daily_blockers_loop_running = True
        _daily_blockers_loop_task = asyncio.create_task(_daily_blockers_report_loop())
        print(
            "[Startup] daily blockers loop enabled "
            f"(interval={_daily_blockers_interval_sec}s, min_trades={_daily_blockers_min_scored_trades})"
        )

    if _db_backup_enabled() and (_db_backup_loop_task is None or _db_backup_loop_task.done()):
        _db_backup_loop_running = True
        _db_backup_loop_task = asyncio.create_task(_db_backup_loop())
        print(
            "[Startup] db backup loop enabled "
            f"(interval={_db_backup_interval_sec()}s, retention={_db_backup_retention_days()}d, dir={_db_backup_dir()})"
        )


@app.on_event("shutdown")
async def shutdown_event():
    global _auto_production_loop_running, _auto_production_loop_task
    global _daily_blockers_loop_running, _daily_blockers_loop_task
    global _db_backup_loop_running, _db_backup_loop_task
    _auto_production_loop_running = False
    if _auto_production_loop_task and not _auto_production_loop_task.done():
        _auto_production_loop_task.cancel()
        try:
            await _auto_production_loop_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Shutdown] auto promotion loop stop warning: {e}")

    _daily_blockers_loop_running = False
    if _daily_blockers_loop_task and not _daily_blockers_loop_task.done():
        _daily_blockers_loop_task.cancel()
        try:
            await _daily_blockers_loop_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Shutdown] daily blockers loop stop warning: {e}")

    _db_backup_loop_running = False
    if _db_backup_loop_task and not _db_backup_loop_task.done():
        _db_backup_loop_task.cancel()
        try:
            await _db_backup_loop_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Shutdown] db backup loop stop warning: {e}")

    await paper_monitor_runtime.stop(trigger="shutdown")
    await adaptive_orchestrator.stop()
    await production_guard.stop()

@app.get("/api/market/price/{symbol:path}")
async def get_market_price(symbol: str):
    """Obtiene el precio real de mercado para un símbolo dado."""
    try:
        # Re-initialize engine to ensure fresh connection if closed
        engine = MarketDataEngine()
        ticker = await engine.fetch_ticker(symbol)
        if not ticker:
            raise HTTPException(status_code=404, detail=f"Ticker not found for {symbol}")
        return {
            "symbol": symbol,
            "last": ticker.get('last'),
            "bid": ticker.get('bid'),
            "ask": ticker.get('ask'),
            "timestamp": ticker.get('timestamp')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    db_ok = db.execute(text("SELECT 1")).fetchone() is not None
    running_bots = db.query(BotDB).filter(BotDB.status == "running").count()
    uptime_s = int(_time.time() - _startup_time)
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    return {
        "status": "ok",
        "db": db_ok,
        "version": "1.2.0",
        "uptime": f"{h}h {m}m {s}s",
        "running_bots": running_bots,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/take-profit/status")
async def get_take_profit_status():
    env = _read_env_values()

    def _float_env(key: str, default: float) -> float:
        try:
            raw = env.get(key)
            if raw is None:
                return float(default)
            return float(str(raw).strip())
        except Exception:
            return float(default)

    state_path = env.get("HYPERLIQUID_TP_STATE_FILE", "reports/profit_guard_state.json")
    abs_state_path = os.path.join(_project_root_path(), state_path) if not os.path.isabs(state_path) else state_path

    raw_state = {}
    state_read_error = ""
    try:
        if os.path.exists(abs_state_path):
            with open(abs_state_path, "r", encoding="utf-8") as f:
                raw_state = json.load(f) or {}
    except Exception as e:
        state_read_error = str(e)
        raw_state = {}

    tracked_positions = []
    for _, payload in (raw_state or {}).items():
        if not isinstance(payload, dict):
            continue
        tracked_positions.append(
            {
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "qty": payload.get("qty"),
                "entry": payload.get("entry"),
                "best_price": payload.get("best_price"),
                "peak_gain_pct": payload.get("peak_gain_pct"),
                "last_mark": payload.get("last_mark"),
                "last_gain_pct": payload.get("last_gain_pct"),
                "last_retrace_pct": payload.get("last_retrace_pct"),
            }
        )

    tracked_positions.sort(
        key=lambda item: float(item.get("peak_gain_pct") or 0.0),
        reverse=True,
    )

    return {
        "profile": env.get("HYPERLIQUID_TRAILING_PROFILE", "manual"),
        "min_net_pnl": _float_env("HYPERLIQUID_MIN_NET_PNL", 1.0),
        "min_net_profit_pct": _float_env("HYPERLIQUID_MIN_NET_PROFIT_PCT", 0.0),
        "exit_slippage_pct": _float_env("HYPERLIQUID_EXIT_SLIPPAGE_PCT", 0.0002),
        "only_production_positions": str(env.get("HYPERLIQUID_TP_ONLY_PRODUCTION", "true")).strip().lower() in {"1", "true", "yes", "on"},
        "hard_take_profit_pct": _float_env("HYPERLIQUID_HARD_TAKE_PROFIT_PCT", 0.05),
        "trailing_trigger_pct": _float_env("HYPERLIQUID_TRAILING_TRIGGER_PCT", 0.02),
        "trailing_retrace_pct": _float_env("HYPERLIQUID_TRAILING_RETRACE_PCT", 0.0075),
        "stop_loss_pct": _float_env("HYPERLIQUID_STOP_LOSS_PCT", 0.02),
        "max_net_loss_abs": _float_env("HYPERLIQUID_MAX_NET_LOSS_ABS", 3.0),
        "trailing_ladder": env.get("HYPERLIQUID_TRAILING_LADDER", "0.02:0.0075,0.05:0.006,0.10:0.0045"),
        "volatility_timeframe": env.get("HYPERLIQUID_VOLATILITY_TIMEFRAME", "5m"),
        "volatility_lookback": int(_float_env("HYPERLIQUID_VOLATILITY_LOOKBACK", 48)),
        "volatility_low_threshold_pct": _float_env("HYPERLIQUID_VOLATILITY_LOW_THRESHOLD_PCT", 0.0015),
        "volatility_high_threshold_pct": _float_env("HYPERLIQUID_VOLATILITY_HIGH_THRESHOLD_PCT", 0.0035),
        "state_file": state_path,
        "state_exists": os.path.exists(abs_state_path),
        "state_read_error": state_read_error,
        "tracked_positions": tracked_positions[:5],
        "tracked_count": len(tracked_positions),
        "orchestrator_running": bool(adaptive_orchestrator.latest_status().get("running")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/settings/hyperliquid")
async def get_hyperliquid_settings(db: Session = Depends(get_db)):
    env = _read_env_values()
    wallet_res, sk_res = get_hyperliquid_wallet_and_key()
    wallet = (wallet_res or env.get("HYPERLIQUID_WALLET_ADDRESS", "")).strip()
    signing_key = (sk_res or "").strip()
    use_testnet = env.get("HYPERLIQUID_USE_TESTNET", "True").strip().lower() == "true"

    wallet_ok = HyperliquidExecutor._is_valid_wallet(wallet)
    key_ok = HyperliquidExecutor._is_valid_private_key(signing_key)

    testnet_snapshot = {
        "account_value": 0.0,
        "withdrawable": 0.0,
        "margin_used": 0.0,
        "exposure_notional": 0.0,
    }
    testnet_snapshot_error = ""
    mainnet_snapshot = {
        "account_value": 0.0,
        "withdrawable": 0.0,
        "margin_used": 0.0,
        "exposure_notional": 0.0,
    }
    mainnet_snapshot_error = ""
    if wallet_ok:
        try:
            testnet_snapshot = _public_account_snapshot(wallet, True)
        except Exception as e:
            testnet_snapshot_error = str(e)
        try:
            mainnet_snapshot = _public_account_snapshot(wallet, False)
        except Exception as e:
            mainnet_snapshot_error = str(e)

    mainnet_auth_ok = False
    mainnet_auth_error = ""
    selected_env_auth_ok = False
    selected_env_auth_error = ""
    if wallet_ok and key_ok:
        mainnet_auth_ok, mainnet_auth_error = await _check_private_auth(wallet, signing_key, False)
        selected_env_auth_ok, selected_env_auth_error = await _check_private_auth(wallet, signing_key, use_testnet)

    selected_env = "testnet" if use_testnet else "mainnet"
    selected_snapshot = testnet_snapshot if use_testnet else mainnet_snapshot
    selected_snapshot_error = testnet_snapshot_error if use_testnet else mainnet_snapshot_error

    return {
        "wallet_address": wallet,
        "wallet_masked": _mask_wallet(wallet),
        "signing_key_present": bool(signing_key),
        "use_testnet": use_testnet,
        "crypto": {
            "fernet_key_configured": fernet_configured(),
            "encrypted_credentials_in_database": encrypted_blob_exists(db),
        },
        "checks": {
            "selected_env": selected_env,
            "selected_env_auth_ok": selected_env_auth_ok,
            "selected_env_auth_error": selected_env_auth_error if not selected_env_auth_ok else "",
            "wallet_format_ok": wallet_ok,
            "signing_key_format_ok": key_ok,
            "mainnet_auth_ok": mainnet_auth_ok,
            "mainnet_auth_error": mainnet_auth_error if not mainnet_auth_ok else "",
            "selected_env_account_value": selected_snapshot.get("account_value", 0.0),
            "selected_env_withdrawable": selected_snapshot.get("withdrawable", 0.0),
            "selected_env_margin_used": selected_snapshot.get("margin_used", 0.0),
            "selected_env_margin_usage_pct": _margin_usage_pct(selected_snapshot),
            "selected_env_exposure_notional": selected_snapshot.get("exposure_notional", 0.0),
            "selected_env_account_error": selected_snapshot_error,
            "testnet_account_value": testnet_snapshot.get("account_value", 0.0),
            "testnet_withdrawable": testnet_snapshot.get("withdrawable", 0.0),
            "testnet_margin_used": testnet_snapshot.get("margin_used", 0.0),
            "testnet_margin_usage_pct": _margin_usage_pct(testnet_snapshot),
            "mainnet_account_value": mainnet_snapshot.get("account_value", 0.0),
            "mainnet_withdrawable": mainnet_snapshot.get("withdrawable", 0.0),
            "mainnet_margin_used": mainnet_snapshot.get("margin_used", 0.0),
            "mainnet_margin_usage_pct": _margin_usage_pct(mainnet_snapshot),
            "mainnet_exposure_notional": mainnet_snapshot.get("exposure_notional", 0.0),
            "ready_for_real_market": bool(wallet_ok and key_ok and mainnet_auth_ok and float(mainnet_snapshot.get("account_value", 0.0)) > 0),
        },
    }


@app.post("/api/settings/hyperliquid/save")
async def save_hyperliquid_settings(
    db: Session = Depends(get_db),
    payload: dict = None,
    x_secrets_admin_token: str | None = Header(default=None, alias="X-Secrets-Admin-Token"),
):
    payload = payload or {}
    admin = os.getenv("SECRETS_ADMIN_TOKEN", "").strip()
    if admin and (x_secrets_admin_token or "").strip() != admin:
        raise HTTPException(status_code=401, detail="X-Secrets-Admin-Token inválido o ausente")

    wallet = str(payload.get("wallet_address") or "").strip()
    signing_key = str(payload.get("signing_key") or "").strip()
    use_testnet = bool(payload.get("use_testnet", True))
    # Por defecto cifrar en BD solo si hay clave maestra; si no, .env en texto (compatibilidad).
    encrypt_db = bool(payload.get("encrypt_in_database", fernet_configured()))
    keep_existing_signing_key = bool(payload.get("keep_existing_signing_key", False))
    if not signing_key and keep_existing_signing_key:
        _, sk_cur = get_hyperliquid_wallet_and_key()
        signing_key = (sk_cur or "").strip()

    if not HyperliquidExecutor._is_valid_wallet(wallet):
        raise HTTPException(status_code=400, detail="Wallet inválida. Debe ser 0x + 40 hex")
    if not HyperliquidExecutor._is_valid_private_key(signing_key):
        raise HTTPException(
            status_code=400,
            detail="Signing key inválida o ausente. Debe ser 0x + 64 hex (API wallet / agente), "
            "o marca conservar clave existente si ya estaba guardada.",
        )

    if encrypt_db and not fernet_configured():
        raise HTTPException(
            status_code=400,
            detail="Para guardar cifrado define APP_CREDENTIALS_FERNET_KEY en .env (genera con: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")",
        )

    if encrypt_db:
        try:
            save_hyperliquid_credentials_encrypted(wallet, signing_key, db)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"No se pudo cifrar/guardar credenciales: {e}") from e
        _persist_env_updates(
            {
                "HYPERLIQUID_WALLET_ADDRESS": wallet,
                "HYPERLIQUID_SIGNING_KEY": "",
                "HYPERLIQUID_USE_TESTNET": "True" if use_testnet else "False",
                "HYPERLIQUID_USE_ENCRYPTED_CREDENTIALS": "True",
            }
        )
    else:
        if encrypted_blob_exists(db):
            delete_hyperliquid_encrypted_credentials(db)
        _persist_env_updates(
            {
                "HYPERLIQUID_WALLET_ADDRESS": wallet,
                "HYPERLIQUID_SIGNING_KEY": signing_key,
                "HYPERLIQUID_USE_TESTNET": "True" if use_testnet else "False",
                "HYPERLIQUID_USE_ENCRYPTED_CREDENTIALS": "False",
            }
        )
    invalidate_hyperliquid_credentials_cache()

    selected_auth_ok, selected_auth_error = await _check_private_auth(wallet, signing_key, use_testnet)

    try:
        testnet_snapshot = _public_account_snapshot(wallet, True)
        testnet_snapshot_error = ""
    except Exception as e:
        testnet_snapshot_error = str(e)
        testnet_snapshot = {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }
    try:
        mainnet_snapshot = _public_account_snapshot(wallet, False)
        mainnet_snapshot_error = ""
    except Exception as e:
        mainnet_snapshot_error = str(e)
        mainnet_snapshot = {
            "account_value": 0.0,
            "withdrawable": 0.0,
            "margin_used": 0.0,
            "exposure_notional": 0.0,
        }

    mainnet_auth_ok, _ = await _check_private_auth(wallet, signing_key, False)
    selected_env = "testnet" if use_testnet else "mainnet"
    selected_snapshot = testnet_snapshot if use_testnet else mainnet_snapshot
    selected_snapshot_error = testnet_snapshot_error if use_testnet else mainnet_snapshot_error

    return {
        "saved": True,
        "wallet_masked": _mask_wallet(wallet),
        "use_testnet": use_testnet,
        "encrypt_in_database": encrypt_db,
        "crypto": {
            "fernet_key_configured": fernet_configured(),
            "encrypted_credentials_in_database": encrypted_blob_exists(db),
        },
        "checks": {
            "selected_env": selected_env,
            "selected_env_auth_ok": selected_auth_ok,
            "selected_env_auth_error": selected_auth_error if not selected_auth_ok else "",
            "selected_env_account_value": selected_snapshot.get("account_value", 0.0),
            "selected_env_withdrawable": selected_snapshot.get("withdrawable", 0.0),
            "selected_env_margin_used": selected_snapshot.get("margin_used", 0.0),
            "selected_env_margin_usage_pct": _margin_usage_pct(selected_snapshot),
            "selected_env_exposure_notional": selected_snapshot.get("exposure_notional", 0.0),
            "selected_env_account_error": selected_snapshot_error,
            "testnet_account_value": testnet_snapshot.get("account_value", 0.0),
            "testnet_withdrawable": testnet_snapshot.get("withdrawable", 0.0),
            "testnet_margin_used": testnet_snapshot.get("margin_used", 0.0),
            "testnet_margin_usage_pct": _margin_usage_pct(testnet_snapshot),
            "mainnet_account_value": mainnet_snapshot.get("account_value", 0.0),
            "mainnet_withdrawable": mainnet_snapshot.get("withdrawable", 0.0),
            "mainnet_margin_used": mainnet_snapshot.get("margin_used", 0.0),
            "mainnet_margin_usage_pct": _margin_usage_pct(mainnet_snapshot),
            "mainnet_exposure_notional": mainnet_snapshot.get("exposure_notional", 0.0),
            "mainnet_auth_ok": mainnet_auth_ok,
            "ready_for_real_market": bool(mainnet_auth_ok and float(mainnet_snapshot.get("account_value", 0.0)) > 0),
        },
    }


@app.get("/api/production/status")
async def get_production_status():
    return production_guard.latest_status()


@app.post("/api/production/scan")
async def run_production_scan():
    return await production_guard.scan_once(trigger="manual")


@app.get("/api/autotrader/orchestrator/status")
async def autotrader_orchestrator_status():
    return adaptive_orchestrator.latest_status()


@app.post("/api/autotrader/orchestrator/run-once")
async def autotrader_orchestrator_run_once(payload: dict = None):
    payload = payload or {}
    symbol = payload.get("symbol")
    allocation = payload.get("allocation")
    return await adaptive_orchestrator.run_once(trigger="manual", symbol=symbol, allocation=allocation)


@app.post("/api/autotrader/orchestrator/start")
async def autotrader_orchestrator_start():
    await adaptive_orchestrator.start()
    return {
        "started": True,
        "running": True,
        "enabled": adaptive_orchestrator.enabled,
        "interval_sec": adaptive_orchestrator.interval_sec,
    }


@app.post("/api/autotrader/orchestrator/stop")
async def autotrader_orchestrator_stop():
    await adaptive_orchestrator.stop()
    return {
        "stopped": True,
        "running": False,
        "enabled": adaptive_orchestrator.enabled,
    }


@app.get("/api/paper-monitor/status")
async def paper_monitor_status():
    return paper_monitor_runtime.latest_status()


@app.post("/api/paper-monitor/start")
async def paper_monitor_start(payload: dict = None):
    payload = payload or {}
    hours = payload.get("hours")
    interval_sec = payload.get("interval_sec")
    prefix = payload.get("prefix")
    return await paper_monitor_runtime.start(hours=hours, interval_sec=interval_sec, prefix=prefix)


@app.post("/api/paper-monitor/stop")
async def paper_monitor_stop():
    return await paper_monitor_runtime.stop(trigger="manual")


@app.get("/api/production/alerts")
async def get_production_alerts(limit: int = 50, only_open: bool = False, db: Session = Depends(get_db)):
    query = db.query(BotAlertDB).order_by(BotAlertDB.created_at.desc())
    if only_open:
        query = query.filter(BotAlertDB.acknowledged == False)
    alerts = query.limit(limit).all()
    out = []
    for alert in alerts:
        context = _infer_alert_context(alert.reason_code, alert.title, alert.message, alert.data or {})
        out.append(
            {
                "id": alert.id,
                "created_at": alert.created_at,
                "bot_id": alert.bot_id,
                "level": alert.level,
                "title": alert.title,
                "message": alert.message,
                "reason_code": alert.reason_code,
                "data": alert.data,
                "acknowledged": alert.acknowledged,
                "probable_cause": context["probable_cause"],
                "suggested_action": context["suggested_action"],
            }
        )
    return out


@app.post("/api/production/alerts/{alert_id}/ack")
async def acknowledge_production_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(BotAlertDB).filter(BotAlertDB.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"message": f"Alert {alert_id} acknowledged"}


@app.get("/api/monitoring/recommendations/{bot_id}/why-not-running")
async def explain_why_not_running(bot_id: str, symbol: str = "", db: Session = Depends(get_db)):
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        raise HTTPException(status_code=404, detail="Bot not found")

    now = datetime.utcnow()
    cfg = dict(bot_entry.config or {})
    strategy = str(bot_entry.strategy or cfg.get("strategy") or "").strip().lower()
    target_symbol = (symbol or cfg.get("symbol") or "").strip()
    runtime_in_memory = bot_id in bot_manager.active_bots

    last_trade = (
        db.query(TradeDB)
        .filter(TradeDB.bot_id == bot_id)
        .order_by(TradeDB.time.desc())
        .first()
    )
    last_order = (
        db.query(OrderLogDB)
        .filter(OrderLogDB.bot_id == bot_id)
        .order_by(OrderLogDB.created_at.desc())
        .first()
    )
    open_positions = (
        db.query(PositionDB)
        .filter(PositionDB.bot_id == bot_id, PositionDB.is_open == True)
        .count()
    )
    recent_alerts = (
        db.query(BotAlertDB)
        .filter(BotAlertDB.bot_id == bot_id)
        .order_by(BotAlertDB.created_at.desc())
        .limit(5)
        .all()
    )

    state_query = db.query(BotLearningStateDB).filter(BotLearningStateDB.bot_id == bot_id)
    if target_symbol:
        state_query = state_query.filter(BotLearningStateDB.symbol == target_symbol)
    learning_rows = state_query.order_by(BotLearningStateDB.updated_at.desc()).limit(3).all()

    checks = {
        "is_archived": bool(bot_entry.is_archived),
        "db_status": str(bot_entry.status or "unknown").lower(),
        "in_memory_running": runtime_in_memory,
        "has_strategy": bool(strategy),
        "has_symbol": bool(target_symbol),
        "has_executor": bool(str(cfg.get("executor") or "").strip()),
        "open_positions": int(open_positions),
        "last_order_status": (str(last_order.status).lower() if last_order and last_order.status else "none"),
        "recent_alerts_count": len(recent_alerts),
    }

    reasons = []
    suggested_actions = []

    if checks["is_archived"]:
        reasons.append("bot_archived")
        suggested_actions.append("Restore bot before trying to start it")

    if checks["db_status"] != BotStatus.RUNNING:
        reasons.append("db_status_not_running")
        suggested_actions.append("Start bot with POST /api/bots/{bot_id}/start")

    if checks["db_status"] == BotStatus.RUNNING and not checks["in_memory_running"]:
        reasons.append("running_in_db_but_missing_in_memory")
        suggested_actions.append("Restart API or call start endpoint to resync bot runtime")

    if not checks["has_strategy"]:
        reasons.append("missing_strategy")
        suggested_actions.append("Set valid strategy in bot config")

    if not checks["has_symbol"] and ("pair" not in strategy):
        reasons.append("missing_symbol")
        suggested_actions.append("Set symbol in bot config (example: BTC/USDT)")

    if "pair" in strategy and not str(cfg.get("pair_symbol_b") or "").strip():
        reasons.append("missing_pair_symbol_b")
        suggested_actions.append("Set pair_symbol_b for paired strategy")

    if checks["last_order_status"] in {"failed", "cancelled"}:
        reasons.append("last_order_not_executed")
        suggested_actions.append("Review executor credentials, market symbol and order constraints")

    critical_alert = next((a for a in recent_alerts if str(a.level or "").lower() == "critical"), None)
    if critical_alert:
        reasons.append("critical_alert_recent")
        suggested_actions.append("Inspect /api/production/alerts and resolve critical conditions")

    if checks["db_status"] == BotStatus.RUNNING and checks["in_memory_running"] and not checks["is_archived"]:
        if last_trade:
            idle_minutes = int(max(0, (now - last_trade.time).total_seconds() // 60))
            if idle_minutes >= 120:
                reasons.append("running_but_no_recent_trades")
                suggested_actions.append("Tune thresholds or lower entry filters for current market regime")
        elif open_positions == 0:
            reasons.append("running_without_trade_history")
            suggested_actions.append("Allow warm-up time or loosen entry conditions")

    if not reasons:
        reasons.append("no_blocking_issue_detected")
        suggested_actions.append("Bot appears healthy; monitor more sample time for signal frequency")

    learning_state = []
    for row in learning_rows:
        state = dict(row.state or {})
        learning_state.append(
            {
                "symbol": row.symbol,
                "updated_at": row.updated_at,
                "last_decision": state.get("last_decision"),
                "last_open_error": state.get("last_open_error"),
                "last_pair_close_reason": state.get("last_pair_close_reason"),
                "win_rate": state.get("win_rate"),
                "cumulative_pnl": state.get("cumulative_pnl"),
            }
        )

    summary = {
        "bot_id": bot_id,
        "strategy": strategy,
        "symbol": target_symbol,
        "status": checks["db_status"],
        "in_memory_running": checks["in_memory_running"],
        "open_positions": checks["open_positions"],
        "last_trade_at": last_trade.time if last_trade else None,
        "last_order_status": checks["last_order_status"],
        "latest_alert": {
            "level": recent_alerts[0].level,
            "title": recent_alerts[0].title,
            "reason_code": recent_alerts[0].reason_code,
            "created_at": recent_alerts[0].created_at,
        } if recent_alerts else None,
    }

    return {
        "summary": summary,
        "checks": checks,
        "reasons": reasons,
        "suggested_actions": list(dict.fromkeys(suggested_actions)),
        "learning_state": learning_state,
    }

@app.get("/api/strategies")
async def list_strategies():
    return [
        {
            "id": "ema_cross",
            "name": "EMA Cross",
            "description": "Genera señales cuando la media móvil rápida cruza la lenta.",
            "params": [{"key": "fast_ema", "default": 9}, {"key": "slow_ema", "default": 21}]
        },
        {
            "id": "technical_pro",
            "name": "Technical Pro (RSI/MACD/Fib)",
            "description": "Combinación de RSI, MACD y niveles de Fibonacci.",
            "params": []
        },
        {
            "id": "algo_expert",
            "name": "AlgoExpert",
            "description": "EMA + RSI + ATR + VWAP multi-confirmación.",
            "params": []
        },
        {
            "id": "dynamic_reinvest",
            "name": "Dynamic Reinvestment",
            "description": "Reinvierte las ganancias automáticamente con un take profit configurable.",
            "params": [{"key": "take_profit_pct", "default": 0.02}]
        },
        {
            "id": "grid_trading",
            "name": "Grid Trading",
            "description": "Compra barato y vende caro dentro de un rango de precio con rejillas.",
            "params": [
                {"key": "upper_limit", "default": 70000},
                {"key": "lower_limit", "default": 60000},
                {"key": "num_grids", "default": 10}
            ]
        },
        {
            "id": "adaptive_learning",
            "name": "Adaptive Learning",
            "description": "Autogestión con aprendizaje de tendencia/histórico y reinversión dinámica.",
            "params": [
                {"key": "adaptive_short_window", "default": 12},
                {"key": "adaptive_long_window", "default": 48},
                {"key": "adaptive_base_amount", "default": 0.01},
                {"key": "reinvest_ratio", "default": 0.35},
                {"key": "self_managed", "default": True}
            ]
        }
    ]


@app.post("/api/market/compare")
async def compare_market_symbols(payload: dict = None):
    payload = payload or {}
    symbol_a = (payload.get("symbol_a") or "BTC/USDT").strip() or "BTC/USDT"
    symbol_b = (payload.get("symbol_b") or "ETH/USDT").strip() or "ETH/USDT"

    mde = MarketDataEngine('binance')
    try:
        ticker_a = await mde.fetch_ticker(symbol_a)
        ticker_b = await mde.fetch_ticker(symbol_b)

        price_a = float(ticker_a.get("last") or 0.0)
        price_b = float(ticker_b.get("last") or 0.0)

        if price_a <= 0 or price_b <= 0:
            raise HTTPException(status_code=400, detail="Could not fetch real market prices for one or both symbols")

        return {
            "symbol_a": symbol_a,
            "price_a": price_a,
            "symbol_b": symbol_b,
            "price_b": price_b,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "binance",
        }
    finally:
        await mde.close()


async def _resolve_market_candles(symbol: str, timeframe: str, limit: int, source: str) -> tuple[list, str]:
    src = (source or "live").strip().lower()
    if src == "imported":
        imported = _load_imported_candles(symbol, timeframe)
        return imported[-limit:] if limit > 0 else imported, "imported"

    mde = MarketDataEngine("binance")
    try:
        candles = await mde.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return _normalize_candles(candles), "live"
    finally:
        await mde.close()


@app.post("/api/market/data/import")
async def import_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    data_format = (payload.get("format") or "json").strip().lower()
    data_raw = payload.get("data")

    if not data_raw:
        raise HTTPException(status_code=400, detail="Missing import data")

    try:
        if data_format == "csv":
            candles = _parse_csv_candles(str(data_raw))
        else:
            parsed = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            if isinstance(parsed, dict) and "candles" in parsed:
                parsed = parsed.get("candles")
            if not isinstance(parsed, list):
                raise ValueError("Invalid JSON format; expected array of candles")
            candles = _normalize_candles(parsed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid import format: {e}")

    if not candles:
        raise HTTPException(status_code=400, detail="No valid candles found in imported data")

    _save_imported_candles(symbol, timeframe, candles)
    return {
        "imported": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": len(candles),
        "first_time": candles[0]["time"],
        "last_time": candles[-1]["time"],
        "source": "imported",
    }


@app.post("/api/market/data/fetch")
async def fetch_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    source = (payload.get("source") or "live").strip().lower()
    limit = int(payload.get("limit") or 300)
    limit = max(20, min(limit, 2000))

    candles, resolved_source = await _resolve_market_candles(symbol, timeframe, limit, source)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candles available for {symbol} ({resolved_source})")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": resolved_source,
        "rows": len(candles),
        "candles": candles,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/market/analysis")
async def analyze_market_history(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    source = (payload.get("source") or "live").strip().lower()
    days = int(payload.get("days") or 30)
    days = max(1, min(days, 90))

    raw_limit = payload.get("limit")
    limit = int(raw_limit) if raw_limit not in (None, "") else 0
    if limit <= 0:
        minutes = _timeframe_to_minutes(timeframe)
        candles_per_day = max(1, int(1440 / minutes))
        limit = int(days * candles_per_day)

    limit = max(20, min(limit, 2000))

    candles, resolved_source = await _resolve_market_candles(symbol, timeframe, limit, source)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candles available for {symbol} ({resolved_source})")

    analysis = _compute_candle_analysis(candles)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": resolved_source,
        "rows": len(candles),
        "days_requested": days,
        "analysis": analysis,
        "candles": candles,
        "first_time": candles[0]["time"],
        "last_time": candles[-1]["time"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/market/data/export")
async def export_market_data(payload: dict = None):
    payload = payload or {}
    symbol = (payload.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    timeframe = (payload.get("timeframe") or "1h").strip() or "1h"
    source = (payload.get("source") or "live").strip().lower()
    data_format = (payload.get("format") or "json").strip().lower()
    limit = int(payload.get("limit") or 500)
    limit = max(20, min(limit, 5000))

    candles, resolved_source = await _resolve_market_candles(symbol, timeframe, limit, source)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candles available for {symbol} ({resolved_source})")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"{_sanitize_asset_key(symbol)}_{_sanitize_asset_key(timeframe)}_{resolved_source}_{stamp}"

    if data_format == "csv":
        content = _candles_to_csv(candles)
        filename = f"{base_name}.csv"
    else:
        content = json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": resolved_source,
                "rows": len(candles),
                "candles": candles,
            },
            ensure_ascii=False,
            indent=2,
        )
        filename = f"{base_name}.json"

    return {
        "exported": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "source": resolved_source,
        "format": data_format,
        "rows": len(candles),
        "filename": filename,
        "content": content,
    }

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).all()
    total_trades = len(trades)
    total_fees = sum(t.fee or 0 for t in trades)
    total_pnl = sum(t.pnl or 0 for t in trades)
    net_pnl = total_pnl - total_fees
    total_volume = sum((t.price or 0) * (t.amount or 0) for t in trades)
    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
    win_rate = round((wins / total_trades * 100), 2) if total_trades > 0 else 0
    open_positions = db.query(PositionDB).filter(PositionDB.is_open == True).count()
    open_orders = db.query(OrderLogDB).filter(OrderLogDB.status == "open").count()
    return {
        "total_trades": total_trades,
        "total_fees": round(total_fees, 4),
        "total_pnl": round(total_pnl, 4),
        "net_pnl": round(net_pnl, 4),
        "total_volume": round(total_volume, 2),
        "win_rate": win_rate,
        "wins": wins,
        "losses": total_trades - wins,
        "open_positions": open_positions,
        "open_orders": open_orders
    }


@app.post("/api/monitoring/recommendations")
async def monitoring_recommendations(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 8) or 8)
    top_n = int(payload.get("top_n", 3) or 3)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))
    top_n = max(1, min(top_n, 20))

    activate = _as_bool(payload.get("activate", False), default=False)
    only_stopped = _as_bool(payload.get("only_stopped", True), default=True)
    require_positive_score = _as_bool(payload.get("require_positive_score", True), default=True)

    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    trades = db.query(TradeDB).filter(TradeDB.time >= since).all()
    bots = db.query(BotDB).filter(BotDB.is_archived == False).all()

    stats_by_bot = {
        bot.id: {
            "bot_id": bot.id,
            "status": bot.status,
            "strategy": bot.strategy,
            "total_trades": 0,
            "scored_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_volume": 0.0,
        }
        for bot in bots
    }

    for trade in trades:
        bot_metrics = stats_by_bot.get(trade.bot_id)
        if not bot_metrics:
            continue
        trade_fee = float(trade.fee or 0.0)
        trade_pnl = float(trade.pnl or 0.0)
        bot_metrics["total_trades"] += 1
        bot_metrics["total_fees"] += trade_fee
        bot_metrics["total_pnl"] += trade_pnl
        bot_metrics["total_volume"] += float((trade.price or 0.0) * (trade.amount or 0.0))

        if trade_pnl != 0.0:
            bot_metrics["scored_trades"] += 1
            if trade_pnl > 0:
                bot_metrics["wins"] += 1
            else:
                bot_metrics["losses"] += 1

    recommendations = []
    for bot in bots:
        bot_metrics = stats_by_bot[bot.id]
        scored_trades = bot_metrics["scored_trades"]
        total_pnl = bot_metrics["total_pnl"]
        total_fees = bot_metrics["total_fees"]
        net_pnl = total_pnl - total_fees
        win_rate = (bot_metrics["wins"] / scored_trades * 100) if scored_trades > 0 else 0.0
        activity_bonus = min(scored_trades, 20) * 0.5
        score = (win_rate * 0.35) + (net_pnl * 5.0) + activity_bonus

        eligible = scored_trades >= min_scored_trades
        if only_stopped and bot.status == BotStatus.RUNNING:
            eligible = False
        if require_positive_score and score <= 0:
            eligible = False
        if win_rate < 50:
            eligible = False
        if net_pnl <= 0:
            eligible = False

        recommendations.append(
            {
                **bot_metrics,
                "win_rate": round(win_rate, 2),
                "net_pnl": round(net_pnl, 6),
                "score": round(score, 4),
                "eligible": eligible,
            }
        )

    recommendations.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    suggested = [item for item in recommendations if item["eligible"]][:top_n]

    activation_results = []
    if activate:
        for item in suggested:
            bot_id = item["bot_id"]
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id, BotDB.is_archived == False).first()
            if not bot_entry:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "bot_not_found"})
                continue
            if bot_entry.status == BotStatus.RUNNING:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "already_running"})
                continue

            started = bot_manager.start_bot(bot_id, bot_entry.config or {})
            if started:
                bot_entry.status = BotStatus.RUNNING
                db.commit()
                activation_results.append({"bot_id": bot_id, "activated": True, "reason": "started"})
            else:
                activation_results.append({"bot_id": bot_id, "activated": False, "reason": "start_failed"})

    return {
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "top_n": top_n,
        "activate": activate,
        "only_stopped": only_stopped,
        "require_positive_score": require_positive_score,
        "sampled_bots": len(bots),
        "sampled_trades": len(trades),
        "suggested_to_activate": suggested,
        "activation_results": activation_results,
        "ranking": recommendations,
    }


@app.post("/api/monitoring/test-results")
async def monitoring_test_results(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 5) or 5)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))

    return _build_monitoring_test_results(db, lookback_hours, min_scored_trades)


@app.post("/api/monitoring/activate-production")
async def activate_bot_for_production(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    bot_id = str(payload.get("bot_id") or "").strip()
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 8) or 8)

    if not bot_id:
        raise HTTPException(status_code=400, detail="bot_id is required")

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))

    result = await _activate_bot_for_production_internal(
        db,
        bot_id=bot_id,
        lookback_hours=lookback_hours,
        min_scored_trades=min_scored_trades,
        trigger="manual_activate_production",
    )

    if result.get("reason") == "bot_not_found":
        raise HTTPException(status_code=404, detail="Bot not found")
    if result.get("reason") == "bot_archived":
        raise HTTPException(status_code=400, detail="Bot is archived. Restore it first.")

    return result


async def _auto_activate_ready_bots_internal(
    db: Session,
    *,
    lookback_hours: int,
    min_scored_trades: int,
    top_n: int,
    require_runtime_ready: bool,
    max_last_trade_age_hours: float,
    auto_patch_executor: bool,
    trigger: str,
) -> dict:
    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    now = datetime.utcnow()
    skipped_not_running = 0
    skipped_stale_trade = 0
    blocked_not_ready = 0
    blocked_not_ready_samples = []
    candidates = []

    for item in monitoring.get("results", []):
        bot_id = str(item.get("bot_id") or "").strip()
        readiness = dict(item.get("readiness") or {})

        if not item.get("candidate_for_production"):
            blocked_not_ready += 1
            if bot_id and len(blocked_not_ready_samples) < 10:
                blocked_not_ready_samples.append(
                    {
                        "bot_id": bot_id,
                        "label": readiness.get("label") or "NO APTO / BLOQUEADO",
                        "summary": readiness.get("summary") or "No cumple gate de producción",
                        "blockers": list(readiness.get("blockers") or []),
                    }
                )
            continue

        if require_runtime_ready and not item.get("runtime_ready"):
            skipped_not_running += 1
            continue

        # Only enforce recency when runtime-ready is required.
        if require_runtime_ready:
            last_trade_at = item.get("last_trade_at")
            if last_trade_at:
                try:
                    age_hours = (now - last_trade_at).total_seconds() / 3600.0
                    if age_hours > max_last_trade_age_hours:
                        skipped_stale_trade += 1
                        continue
                except Exception:
                    skipped_stale_trade += 1
                    continue

        candidates.append(item)

    selected = candidates[:top_n]
    activation_results = []
    for item in selected:
        bot_id = str(item.get("bot_id") or "").strip()
        if not bot_id:
            continue

        first_attempt = await _activate_bot_for_production_internal(
            db,
            bot_id=bot_id,
            lookback_hours=lookback_hours,
            min_scored_trades=min_scored_trades,
            trigger=trigger,
        )

        if (not first_attempt.get("activated")) and auto_patch_executor:
            reason = str(first_attempt.get("reason") or "")
            suggested_patch = dict(first_attempt.get("suggested_patch") or {})
            if reason == "executor_not_hyperliquid" and suggested_patch:
                bot_manager.update_bot_config(bot_id, suggested_patch)
                first_attempt = await _activate_bot_for_production_internal(
                    db,
                    bot_id=bot_id,
                    lookback_hours=lookback_hours,
                    min_scored_trades=min_scored_trades,
                    trigger=f"{trigger}_after_executor_patch",
                )
                first_attempt["auto_patched"] = True
                first_attempt["auto_patch"] = suggested_patch
            elif reason == "bot_configured_for_testnet":
                patch = {"hyperliquid_testnet": False}
                bot_manager.update_bot_config(bot_id, patch)
                first_attempt = await _activate_bot_for_production_internal(
                    db,
                    bot_id=bot_id,
                    lookback_hours=lookback_hours,
                    min_scored_trades=min_scored_trades,
                    trigger=f"{trigger}_after_testnet_patch",
                )
                first_attempt["auto_patched"] = True
                first_attempt["auto_patch"] = patch

        activation_results.append(first_attempt)

    activated_count = sum(1 for item in activation_results if item.get("activated"))
    blocked_count = len(activation_results) - activated_count

    return {
        "trigger": trigger,
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "top_n": top_n,
        "require_runtime_ready": require_runtime_ready,
        "max_last_trade_age_hours": max_last_trade_age_hours,
        "skipped_not_running": skipped_not_running,
        "skipped_stale_trade": skipped_stale_trade,
        "blocked_not_ready": blocked_not_ready,
        "blocked_not_ready_samples": blocked_not_ready_samples,
        "production_candidates_detected": len(candidates),
        "attempted": len(activation_results),
        "activated": activated_count,
        "blocked": blocked_count,
        "results": activation_results,
    }


async def _auto_production_promotion_loop() -> None:
    global _auto_production_loop_running
    while _auto_production_loop_running:
        try:
            ops_running = bool(paper_monitor_runtime.latest_status().get("running")) and bool(adaptive_orchestrator.latest_status().get("running"))
            if not ops_running:
                await asyncio.sleep(_auto_production_promotion_interval_sec)
                continue

            with SessionLocal() as db:
                summary = await _auto_activate_ready_bots_internal(
                    db,
                    lookback_hours=_auto_production_lookback_hours,
                    min_scored_trades=_auto_production_min_scored_trades,
                    top_n=_auto_production_top_n,
                    require_runtime_ready=False,
                    max_last_trade_age_hours=_auto_production_max_last_trade_age_hours,
                    auto_patch_executor=True,
                    trigger="auto_scheduler",
                )
            if summary.get("attempted") or summary.get("blocked_not_ready"):
                print(
                    "[AutoPromotion] "
                    f"activated={summary.get('activated', 0)} "
                    f"blocked={summary.get('blocked', 0)} "
                    f"not_ready={summary.get('blocked_not_ready', 0)}"
                )
        except Exception as e:
            print(f"[AutoPromotion] cycle failed: {e}")

        await asyncio.sleep(_auto_production_promotion_interval_sec)


def _write_daily_blockers_report_once(*, lookback_hours: int, min_scored_trades: int) -> dict:
    with SessionLocal() as db:
        report = _build_blockers_ranking_report(
            db,
            lookback_hours=lookback_hours,
            min_scored_trades=min_scored_trades,
        )

    os.makedirs("reports", exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = os.path.join("reports", f"production_blockers_ranking_{day}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {
        "path": path,
        "blocked_count": int(report.get("blocked_count") or 0),
        "generated_at": report.get("generated_at"),
    }


async def _daily_blockers_report_loop() -> None:
    global _daily_blockers_loop_running
    while _daily_blockers_loop_running:
        try:
            info = _write_daily_blockers_report_once(
                lookback_hours=_daily_blockers_lookback_hours,
                min_scored_trades=_daily_blockers_min_scored_trades,
            )
            print(
                "[DailyBlockers] "
                f"blocked={info.get('blocked_count', 0)} "
                f"file={info.get('path')}"
            )
        except Exception as e:
            print(f"[DailyBlockers] cycle failed: {e}")

        await asyncio.sleep(_daily_blockers_interval_sec)


@app.post("/api/monitoring/blockers-ranking")
async def generate_blockers_ranking(payload: dict = None):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", _daily_blockers_lookback_hours) or _daily_blockers_lookback_hours)
    min_scored_trades = int(payload.get("min_scored_trades", _daily_blockers_min_scored_trades) or _daily_blockers_min_scored_trades)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))

    info = _write_daily_blockers_report_once(
        lookback_hours=lookback_hours,
        min_scored_trades=min_scored_trades,
    )
    return {
        "generated": True,
        **info,
    }


@app.post("/api/monitoring/auto-activate-ready")
async def auto_activate_ready_bots(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 12) or 12)
    top_n = int(payload.get("top_n", 2) or 2)
    require_runtime_ready = bool(payload.get("require_runtime_ready", False))
    max_last_trade_age_hours = float(payload.get("max_last_trade_age_hours", 6.0) or 6.0)
    auto_patch_executor = bool(payload.get("auto_patch_executor", True))

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))
    top_n = max(1, min(top_n, 20))
    max_last_trade_age_hours = max(0.5, min(max_last_trade_age_hours, 24 * 30))

    return await _auto_activate_ready_bots_internal(
        db,
        lookback_hours=lookback_hours,
        min_scored_trades=min_scored_trades,
        top_n=top_n,
        require_runtime_ready=require_runtime_ready,
        max_last_trade_age_hours=max_last_trade_age_hours,
        auto_patch_executor=auto_patch_executor,
        trigger="auto_mode_on",
    )


@app.post("/api/monitoring/prepare-production")
async def prepare_bots_for_production(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    lookback_hours = int(payload.get("lookback_hours", 24) or 24)
    min_scored_trades = int(payload.get("min_scored_trades", 12) or 12)
    include_running = bool(payload.get("include_running", True))
    include_archived = bool(payload.get("include_archived", False))
    apply_recommendations = bool(payload.get("apply_recommendations", True))
    auto_activate_ready = bool(payload.get("auto_activate_ready", True))
    top_n_activate = int(payload.get("top_n_activate", 2) or 2)
    max_last_trade_age_hours = float(payload.get("max_last_trade_age_hours", 6.0) or 6.0)

    lookback_hours = max(1, min(lookback_hours, 24 * 30))
    min_scored_trades = max(1, min(min_scored_trades, 200))
    top_n_activate = max(1, min(top_n_activate, 20))
    max_last_trade_age_hours = max(0.5, min(max_last_trade_age_hours, 24 * 30))

    monitoring = _build_monitoring_test_results(db, lookback_hours, min_scored_trades)
    changed = 0
    skipped = 0
    prepared = []

    bots_map = {
        bot.id: bot
        for bot in db.query(BotDB).all()
    }

    for item in monitoring.get("results", []):
        bot_id = str(item.get("bot_id") or "").strip()
        if not bot_id:
            skipped += 1
            continue

        bot = bots_map.get(bot_id)
        if not bot:
            skipped += 1
            continue

        if bot.is_archived and not include_archived:
            skipped += 1
            continue

        if (not include_running) and str(bot.status or "").lower() == BotStatus.RUNNING:
            skipped += 1
            continue

        patch = _build_production_preparation_patch(item=item, min_scored_trades=min_scored_trades)
        if not apply_recommendations:
            patch = {
                "production_policy": patch.get("production_policy"),
                "analysis_approved": patch.get("analysis_approved"),
                "candidate_for_production": patch.get("candidate_for_production"),
                "production_ready": patch.get("production_ready"),
            }

        current_cfg = dict(bot.config or {})
        new_cfg = dict(current_cfg)
        new_cfg.update(patch)

        if new_cfg != current_cfg:
            bot.config = new_cfg
            changed += 1
            if bot_id in bot_manager.active_bots:
                bot_manager.active_bots[bot_id].reconfigure(new_cfg)

        readiness = dict(item.get("readiness") or {})
        prepared.append(
            {
                "bot_id": bot_id,
                "label": readiness.get("label") or ("APTO PRODUCCION" if item.get("candidate_for_production") else "NO APTO / BLOQUEADO"),
                "summary": readiness.get("summary") or "Sin resumen",
                "candidate_for_production": bool(item.get("candidate_for_production")),
                "recommendation_level": (item.get("recommendation") or {}).get("level"),
                "applied_patch_keys": sorted(list(patch.keys())),
            }
        )

    db.commit()

    auto_activation = None
    if auto_activate_ready:
        auto_activation = await _auto_activate_ready_bots_internal(
            db,
            lookback_hours=lookback_hours,
            min_scored_trades=min_scored_trades,
            top_n=top_n_activate,
            require_runtime_ready=True,
            max_last_trade_age_hours=max_last_trade_age_hours,
            auto_patch_executor=True,
            trigger="prepare_production",
        )

    return {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "bots_seen": len(monitoring.get("results", [])),
        "configs_changed": changed,
        "skipped": skipped,
        "prepared": prepared,
        "auto_activation": auto_activation,
    }

@app.get("/api/positions")
async def get_positions(sync: bool = True, db: Session = Depends(get_db)):
    if sync:
        try:
            await _sync_positions_with_best_executor()
        except Exception as e:
            print(f"[Positions] sync failed before read: {e}")

    positions = db.query(PositionDB).filter(PositionDB.is_open == True).order_by(PositionDB.opened_at.desc()).all()
    result = []
    for p in positions:
        result.append({
            "id": p.id,
            "bot_id": p.bot_id,
            "symbol": p.symbol,
            "side": p.side,
            "entry_price": p.entry_price,
            "quantity": p.quantity,
            "current_price": p.current_price,
            "unrealized_pnl": round(p.unrealized_pnl or 0, 4),
            "fee_paid": round(p.fee_paid or 0, 4),
            "opened_at": p.opened_at
        })
    return result

@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str, db: Session = Depends(get_db)):
    position = db.query(PositionDB).filter(PositionDB.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    
    position.is_open = False
    position.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"Position {position_id} closed manually"}


# Nuevo endpoint: aumentar capital de una posición abierta si el bot está activo
from fastapi import Body

@app.post("/api/positions/{position_id}/increase-capital")
async def increase_position_capital(position_id: str, amount: float = Body(..., embed=True), db: Session = Depends(get_db)):
    position = db.query(PositionDB).filter(PositionDB.id == position_id, PositionDB.is_open == True).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found or not open")

    # Comprobar si el bot está activo
    bot_id = position.bot_id
    bot = bot_manager.active_bots.get(bot_id)
    if not bot or getattr(bot, 'status', None) != BotStatus.RUNNING:
        return {"success": False, "message": "El bot no está activo. Solo puedes aumentar capital si el bot está en ejecución y la posición está abierta."}

    # Lógica para aumentar la posición (ejemplo: enviar orden de incremento)
    try:
        # Aquí deberías llamar a la función real de tu executor para aumentar la posición
        # Por ejemplo: bot.increase_position(position, amount)
        # Simulación:
        # Actualiza la cantidad localmente (en producción, deberías validar con el exchange)
        position.quantity += amount
        position.updated_at = datetime.utcnow()
        db.commit()
        return {"success": True, "message": f"Capital aumentado en {amount}. Nueva cantidad: {position.quantity}", "new_quantity": position.quantity}
    except Exception as e:
        return {"success": False, "message": f"Error al aumentar capital: {e}"}

@app.get("/api/orders")
async def get_order_log(limit: int = 100, db: Session = Depends(get_db)):
    orders = db.query(OrderLogDB).order_by(OrderLogDB.created_at.desc()).limit(limit).all()
    return [
        {
            "id": o.id,
            "bot_id": o.bot_id,
            "symbol": o.symbol,
            "side": o.side,
            "status": o.status,
            "price": o.price,
            "amount": o.amount,
            "filled_amount": o.filled_amount,
            "fee": round(o.fee or 0, 6),
            "pnl": round(o.pnl or 0, 4),
            "strategy": o.strategy,
            "executor": o.executor,
            "created_at": o.created_at,
            "updated_at": o.updated_at
        }
        for o in orders
    ]

@app.post("/risk/kill-switch")
async def activate_kill_switch():
    risk_engine.trigger_kill_switch()
    # Stop all bots in manager as well
    for bot_id in list(bot_manager.active_bots.keys()):
        bot_manager.stop_bot(bot_id)
    return {"message": "Global Kill Switch activated. All trades and bots stopped."}

@app.get("/api/bots")
async def list_bots(include_system: bool = True, db: Session = Depends(get_db)):
    db_bots = db.query(BotDB).all()
    if include_system:
        return db_bots

    def _is_system_managed(bot: BotDB) -> bool:
        cfg = bot.config or {}
        managed_by = str(cfg.get("managed_by") or "").strip().lower()
        bot_id = str(bot.id or "").strip().upper()
        return managed_by == "adaptive_orchestrator" or bot_id.startswith("AUTO-ADAPT-")

    return [bot for bot in db_bots if not _is_system_managed(bot)]


@app.get("/api/bots/performance-summary")
async def bots_performance_summary(
    lookback_hours: int = 168,
    min_scored_trades: int = 8,
    db: Session = Depends(get_db),
):
    """
    Métricas por bot en una ventana (por defecto 7 días) + readiness para producción
    y checklist de seguridad para pasar a Hyperliquid mainnet.
    """
    since = datetime.utcnow() - timedelta(hours=max(1, int(lookback_hours)))
    market_regime_context = _get_market_regime_context()
    bots = db.query(BotDB).filter(BotDB.is_archived == False).all()
    trades = db.query(TradeDB).filter(TradeDB.time >= since).order_by(TradeDB.time.asc()).all()
    open_critical = (
        db.query(BotAlertDB)
        .filter(BotAlertDB.acknowledged == False, BotAlertDB.level == "critical")
        .all()
    )
    critical_map: dict = {}
    for alert in open_critical:
        critical_map.setdefault(alert.bot_id, 0)
        critical_map[alert.bot_id] += 1

    grouped: dict = {}
    for trade in trades:
        grouped.setdefault(trade.bot_id, []).append(trade)

    results = []
    for bot in bots:
        cfg = dict(bot.config or {})
        bot_trades = grouped.get(bot.id, [])
        scored_pnls = [float(t.pnl or 0.0) for t in bot_trades if float(t.pnl or 0.0) != 0.0]
        wins = sum(1 for p in scored_pnls if p > 0)
        total_pnl = sum(float(t.pnl or 0.0) for t in bot_trades)
        total_fees = sum(float(t.fee or 0.0) for t in bot_trades)
        net_pnl = total_pnl - total_fees
        win_rate = (wins / len(scored_pnls) * 100) if scored_pnls else 0.0
        gross_profit = sum(max(p, 0.0) for p in scored_pnls)
        gross_loss = abs(sum(min(p, 0.0) for p in scored_pnls))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        consecutive_losses = _compute_consecutive_losses(scored_pnls)

        metrics = {
            "total_trades": len(bot_trades),
            "scored_trades": len(scored_pnls),
            "wins": wins,
            "losses": len(scored_pnls) - wins,
            "win_rate": round(win_rate, 2),
            "net_pnl": round(net_pnl, 6),
            "profit_factor": round(profit_factor, 4),
            "consecutive_losses": consecutive_losses,
        }

        readiness = _evaluate_production_readiness(
            strategy=str(bot.strategy or ""),
            metrics={
                "scored_trades": len(scored_pnls),
                "win_rate": win_rate,
                "net_pnl": net_pnl,
                "profit_factor": profit_factor,
                "consecutive_losses": consecutive_losses,
            },
            critical_open_count=int(critical_map.get(bot.id, 0) or 0),
            runtime_ready=str(bot.status or "").lower() == BotStatus.RUNNING,
            min_scored_trades=min_scored_trades,
            market_regime_context=market_regime_context,
        )

        live_main = _is_live_mainnet_config(cfg)
        gate_ok = _analysis_gate_ok(cfg)
        executor = str(cfg.get("executor") or "paper").strip().lower()
        if executor == "paper":
            network_label = "PAPER"
        elif executor == "hyperliquid":
            network_label = "HL TESTNET" if _cfg_hyperliquid_testnet(cfg) else "HL MAINNET"
        else:
            network_label = executor.upper()

        results.append(
            {
                "bot_id": bot.id,
                "strategy": bot.strategy,
                "status": bot.status,
                "executor": executor,
                "network_label": network_label,
                "hyperliquid_testnet": _cfg_hyperliquid_testnet(cfg) if executor == "hyperliquid" else None,
                "metrics_window_hours": int(lookback_hours),
                "metrics": metrics,
                "readiness": {
                    "gate_ok": bool(readiness.get("gate_ok")),
                    "label": readiness.get("label"),
                    "summary": readiness.get("summary"),
                    "market_regime": readiness.get("market_regime"),
                    "blockers": readiness.get("blockers", [])[:6],
                },
                "mainnet_safety": {
                    "is_live_mainnet": live_main,
                    "analysis_gate_ok": gate_ok,
                    "flags": {
                        "analysis_approved": bool(cfg.get("analysis_approved")),
                        "candidate_for_production": bool(cfg.get("candidate_for_production")),
                        "production_ready": bool(cfg.get("production_ready")),
                    },
                    "can_start_live_without_force": (not live_main) or gate_ok,
                    "promotion_checklist": [
                        "Operar en paper o HL testnet hasta cumplir umbral de trades y win rate",
                        "Revisar Net PnL y profit factor en la ventana de 7 días",
                        "Sin alertas críticas abiertas",
                        "Marcar en config: production_ready o analysis_approved antes de mainnet",
                        "Iniciar mainnet con capital reducido y kill switch probado",
                    ],
                },
            }
        )

    return {
        "lookback_hours": lookback_hours,
        "min_scored_trades": min_scored_trades,
        "market_regime": market_regime_context,
        "bots": results,
    }


@app.get("/api/bot-presets")
async def list_bot_presets_api():
    return {"presets": list_bot_presets()}


@app.post("/api/bot-advisor/analyze")
async def analyze_bot_options(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    symbol = payload.get("symbol", "BTC/USDT")
    allocation = payload.get("allocation", 500)
    return await build_bot_advice(db, symbol=symbol, allocation=allocation)


@app.post("/api/bot-advisor/from-text")
async def build_bot_from_text(payload: dict = None):
    payload = payload or {}
    prompt = str(payload.get("prompt") or "").strip()
    symbol = str(payload.get("symbol") or "BTC/USDT").strip()
    allocation = float(payload.get("allocation") or 500)
    return _bot_config_from_prompt(prompt=prompt, symbol=symbol, allocation=allocation)


@app.post("/api/bot-advisor/execute")
async def execute_bot_advisor(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    horizon = (payload.get("horizon") or "").strip().lower()
    symbol = payload.get("symbol", "BTC/USDT")
    allocation = payload.get("allocation", 500)
    force_new = bool(payload.get("force_new", True))

    if horizon not in {"corto", "medio", "largo"}:
        raise HTTPException(status_code=400, detail="horizon must be one of: corto, medio, largo")

    analysis = await build_bot_advice(db, symbol=symbol, allocation=allocation)
    rec = next((item for item in analysis.get("recommendations", []) if item.get("horizon") == horizon), None)
    if not rec:
        raise HTTPException(status_code=404, detail="No recommendation available for selected horizon")

    if (not force_new) and rec.get("recommended_action") in {"tune_existing", "reduce_risk"} and rec.get("recommended_bot_id") and rec.get("edited_config"):
        bot_id = rec.get("recommended_bot_id")
        success = bot_manager.update_bot_config(bot_id, rec.get("edited_config") or {})
        if not success:
            raise HTTPException(status_code=404, detail=f"Recommended bot {bot_id} not found")

        return {
            "executed": True,
            "action": rec.get("recommended_action"),
            "bot_id": bot_id,
            "horizon": horizon,
            "message": f"Bot {bot_id} updated using advisor recommendation ({rec.get('recommended_action')})",
        }

    config = (rec.get("new_bot_config") or rec.get("edited_config") or {}).copy()
    new_bot_id = f"advisor_{horizon}_{uuid.uuid4().hex[:6]}"
    config["id"] = new_bot_id

    existing = db.query(BotDB).filter(BotDB.id == new_bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Unable to create advisor bot: duplicate id")
    bot_entry = BotDB(
        id=new_bot_id,
        strategy=str(config.get("strategy") or "ema_cross"),
        status=BotStatus.STOPPED,
        config=config,
        is_archived=False,
    )
    db.add(bot_entry)
    db.commit()

    return {
        "executed": True,
        "action": "create_new",
        "bot_id": new_bot_id,
        "horizon": horizon,
        "message": f"Advisor created bot {new_bot_id} in STOPPED mode (analysis-first)",
    }


@app.post("/api/bot-presets/{preset_id}/create")
async def create_bot_from_preset(preset_id: str, payload: dict = None, db: Session = Depends(get_db)):
    preset = get_bot_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    payload = payload or {}
    overrides = payload.get("overrides", {}) if isinstance(payload, dict) else {}

    base_config = preset.get("config", {}).copy()
    base_config.update(overrides)

    bot_id = (payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not bot_id:
        bot_id = f"{preset_id}_{uuid.uuid4().hex[:6]}"

    base_config["id"] = bot_id

    existing = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bot ID already exists")

    bot_entry = BotDB(
        id=bot_id,
        strategy=str(base_config.get("strategy") or preset.get("strategy") or "ema_cross"),
        status=BotStatus.STOPPED,
        config=base_config,
        is_archived=False,
    )
    db.add(bot_entry)
    db.commit()

    return {
        "bot_id": bot_id,
        "status": BotStatus.STOPPED,
        "preset_id": preset_id,
        "preset_name": preset.get("name"),
        "message": "Bot created in STOPPED mode. Run analysis, then start explicitly.",
    }


@app.post("/api/bot-presets/{preset_id}/save")
async def save_bot_from_preset_to_vault(
    preset_id: str,
    payload: dict = None,
    db: Session = Depends(get_db),
):
    preset = get_bot_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    payload = payload or {}
    overrides = payload.get("overrides", {}) if isinstance(payload, dict) else {}

    base_config = preset.get("config", {}).copy()
    base_config.update(overrides)

    bot_id = (payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not bot_id:
        bot_id = f"{preset_id}_{uuid.uuid4().hex[:6]}"

    existing = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bot ID already exists")

    base_config["id"] = bot_id

    bot_entry = BotDB(
        id=bot_id,
        strategy=base_config.get("strategy", preset.get("strategy", "ema_cross")),
        status=BotStatus.STOPPED,
        config=base_config,
        is_archived=True,
    )
    db.add(bot_entry)
    db.commit()

    return {
        "bot_id": bot_id,
        "status": BotStatus.STOPPED,
        "is_archived": True,
        "preset_id": preset_id,
        "preset_name": preset.get("name"),
        "message": "Bot saved in Vault without launch",
    }

@app.post("/api/bots")
async def create_bot(bot_config: dict, db: Session = Depends(get_db)):
    bot_id = bot_config.get("id", "").strip()
    if not bot_id:
        # Fallback to auto-generation if not provided at all, but only if empty string wasn't explicitly sent
        if "id" not in bot_config or not bot_config["id"]:
            bot_id = f"bot_{len(bot_manager.active_bots) + 1}"
        else:
            raise HTTPException(status_code=400, detail="Bot ID cannot be empty or whitespace")

    existing = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bot ID already exists")

    cfg = dict(bot_config or {})
    cfg["id"] = bot_id

    # Safety default: create bots stopped; explicit start is required.
    bot_entry = BotDB(
        id=bot_id,
        strategy=str(cfg.get("strategy") or "ema_cross"),
        status=BotStatus.STOPPED,
        config=cfg,
        is_archived=False,
    )
    db.add(bot_entry)
    db.commit()

    return {
        "bot_id": bot_id,
        "status": BotStatus.STOPPED,
        "message": "Bot created in STOPPED mode. Run analysis, then start explicitly.",
    }

@app.patch("/api/bots/{bot_id}")
async def update_bot(bot_id: str, new_config: dict):
    success = bot_manager.update_bot_config(bot_id, new_config)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    return {"message": f"Bot {bot_id} configuration updated", "id": bot_id}

@app.post("/api/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    success = bot_manager.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found or not running")
    return {"message": f"Bot {bot_id} stopped"}

@app.delete("/api/bots/{bot_id}")
async def delete_bot(bot_id: str):
    success = bot_manager.delete_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} deleted"}

@app.post("/api/bots/{bot_id}/archive")
async def archive_bot(bot_id: str):
    success = bot_manager.archive_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} archived"}

@app.post("/api/bots/{bot_id}/restore")
async def restore_bot(bot_id: str):
    success = bot_manager.restore_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"message": f"Bot {bot_id} restored"}

@app.post("/api/bots/{bot_id}/start")
async def start_existing_bot(bot_id: str, payload: dict = None, db: Session = Depends(get_db)):
    bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot_entry:
        raise HTTPException(status_code=404, detail="Bot not found in database")
    
    if bot_entry.is_archived:
        raise HTTPException(
            status_code=400,
            detail="No se puede iniciar un bot archivado. Restáuralo desde la cápsula primero.",
        )
    
    # If already running in memory, treat as success (idempotent)
    if bot_id in bot_manager.active_bots:
        return {"message": f"Bot {bot_id} is already running"}

    payload = payload or {}
    cfg = dict(bot_entry.config or {})
    if _is_live_mainnet_config(cfg):
        bypass_gate = bool(payload.get("force_start_live", False))
        if (not _analysis_gate_ok(cfg)) and (not bypass_gate):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Bloqueo mainnet: este bot usa Hyperliquid en MAINNET y requiere análisis previo. "
                    "Opciones: (1) En la config del bot activa analysis_approved, candidate_for_production o production_ready; "
                    "(2) Cambia a testnet (hyperliquid_testnet: true); "
                    "(3) Envía force_start_live: true en el POST solo si aceptas el riesgo."
                ),
            )

    success = bot_manager.start_bot(bot_id, bot_entry.config)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="No se pudo iniciar el bot (p. ej. ya está en ejecución). Recarga la lista de bots.",
        )
    return {"message": f"Bot {bot_id} started"}

@app.get("/api/trades")
async def list_trades(db: Session = Depends(get_db)):
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).limit(50).all()
    return trades

@app.get("/api/portfolio/{bot_id}")
async def get_portfolio(bot_id: str, db: Session = Depends(get_db)):
    """Obtiene el portfolio de paper trading de un bot específico"""
    portfolio = db.query(PaperPortfolioDB).filter(PaperPortfolioDB.bot_id == bot_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found for this bot")
    
    return {
        "bot_id": portfolio.bot_id,
        "cash_balance": portfolio.cash_balance,
        "positions": portfolio.positions,
        "total_equity": portfolio.total_equity,
        "realized_pnl": portfolio.realized_pnl,
        "updated_at": portfolio.updated_at
    }

@app.get("/api/ai/explain/{trade_id}")
async def explain_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(TradeDB).filter(TradeDB.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    explanation = await ai_engine.generate_explanation({
        "symbol": trade.symbol,
        "side": trade.side,
        "price": trade.price,
        "amount": trade.amount,
        "bot_id": trade.bot_id
    })
    return {"explanation": explanation}

@app.get("/api/reports/json")
async def get_json_report(db: Session = Depends(get_db)):
    if reporting_engine is None:
        raise HTTPException(status_code=503, detail="Reporting engine unavailable on this runtime")
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).all()
    metrics = calculate_metrics(trades)
    return reporting_engine.generate_json_report(trades, metrics)

@app.get("/api/reports/pdf")
async def get_pdf_report(db: Session = Depends(get_db)):
    if reporting_engine is None:
        raise HTTPException(status_code=503, detail="PDF reporting unavailable on this runtime")
    trades = db.query(TradeDB).order_by(TradeDB.time.desc()).all()
    metrics = calculate_metrics(trades)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    file_path = reporting_engine.generate_pdf_report(filename, trades, metrics)
    return FileResponse(file_path, filename=filename, media_type="application/pdf")

@app.post("/api/backtest/run")
async def run_backtest(params: dict):
    symbol = params.get("symbol", "BTC/USDT")
    timeframe = params.get("timeframe", "1h")
    limit = params.get("limit", 100)
    
    strategy_name = params.get("strategy", "ema_cross")
    if "technical_pro" in strategy_name.lower():
        from apps.engine.technical_pro import TechnicalProStrategy
        strategy = TechnicalProStrategy()
    elif "algo_expert" in strategy_name.lower():
        from apps.engine.algo_expert import AlgoExpertStrategy
        strategy = AlgoExpertStrategy()
    elif "dynamic_reinvest" in strategy_name.lower():
        from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
        tp = params.get("take_profit_pct", 0.02)
        strategy = DynamicReinvestStrategy(take_profit_pct=tp)
    else:
        from apps.engine.ema_cross import EMACrossStrategy
        strategy = EMACrossStrategy()
        
    engine = BacktestEngine(strategy)
    
    try:
        historical_data = await engine.fetch_historical_data(symbol, timeframe, limit)
        results = await engine.run(historical_data)
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync/positions")
async def sync_positions():
    """Sincroniza las posiciones del exchange con la DB local."""
    return await _sync_positions_with_best_executor()

@app.post("/api/bots/adopt")
async def adopt_bot(bot_id: str, symbol: str, strategy: str = "algo_expert"):
    """Adopta una posición huérfana con un nuevo bot."""
    config = {
        "symbol": symbol,
        "strategy": strategy,
        "executor": "paper" # Por defecto para esta versión
    }
    success = await bot_manager.adopt_position(bot_id, symbol, strategy, config)
    if success:
        return {"message": f"Bot {bot_id} adopted position for {symbol}"}
    raise HTTPException(status_code=400, detail="Could not adopt position")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _auth_enabled():
        return await call_next(request)

    path = request.url.path
    is_api = path.startswith("/api/")
    public_paths = {
        "/health",
        "/api/health",
        "/api/auth/login",
        "/api/auth/status",
        "/login",
        "/favicon.ico",
    }
    if path in public_paths or path.startswith("/static/"):
        return await call_next(request)

    user = _request_authenticated_user(request)
    if user:
        request.state.auth_user = user
        # If user already authenticated, avoid leaving on login page.
        if path == "/login":
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response = await call_next(request)
        # Sliding session: refresh last activity on each authenticated request.
        _refresh_auth_session_cookie(response, user)
        return response

    if is_api:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "authentication_required"},
        )

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", include_in_schema=False)
async def read_login():
    if not _auth_enabled():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    if _auth_is_configured():
        return FileResponse(os.path.join(static_dir, "login.html"))
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "auth_enabled_but_not_configured"},
    )


@app.post("/api/auth/login")
async def auth_login(request: Request, payload: dict = None):
    payload = payload or {}
    if not _auth_enabled():
        return {"ok": True, "auth_enabled": False}
    if not _auth_is_configured():
        raise HTTPException(status_code=503, detail="auth_enabled_but_not_configured")

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    lock_remain = _auth_lockout_remaining_seconds(request=request, username=username)
    if lock_remain > 0:
        raise HTTPException(status_code=429, detail=f"too_many_attempts_try_in_{lock_remain}s")
    if username != _auth_username():
        _register_auth_failure(request=request, username=username)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    ok_pwd = _verify_auth_password(password, _auth_password_hash())
    if not ok_pwd:
        _register_auth_failure(request=request, username=username)
        raise HTTPException(status_code=401, detail="invalid_credentials")

    if _auth_totp_enabled():
        totp_code = str(payload.get("totp_code") or "").strip()
        if not _verify_totp_code(totp_code, _auth_totp_secret()):
            _register_auth_failure(request=request, username=username)
            raise HTTPException(status_code=401, detail="invalid_totp_code")

    _clear_auth_failures(request=request, username=username)

    token = _create_auth_session_token(username)
    response = JSONResponse(
        content={
            "ok": True,
            "auth_enabled": True,
            "username": username,
            "requires_totp": _auth_totp_enabled(),
            "idle_timeout_minutes": _auth_idle_minutes(),
        }
    )
    _refresh_auth_session_cookie(response, username)
    return response


@app.post("/api/auth/logout")
async def auth_logout():
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(key=_auth_cookie_name())
    return response


@app.get("/api/auth/status")
async def auth_status(request: Request):
    user = _request_authenticated_user(request)
    lock_remain = 0
    if not user:
        lock_remain = _auth_lockout_remaining_seconds(request=request, username=_auth_username())
    return {
        "auth_enabled": _auth_enabled(),
        "authenticated": bool(user),
        "username": user if user else None,
        "requires_totp": bool(_auth_totp_enabled()),
        "idle_timeout_minutes": _auth_idle_minutes(),
        "max_failed_attempts": _auth_max_failed_attempts(),
        "lockout_minutes": _auth_lockout_minutes(),
        "lockout_remaining_sec": lock_remain,
    }


@app.get("/api/db-backups/status")
async def db_backups_status():
    return {
        "enabled": _db_backup_enabled(),
        "loop_running": bool(_db_backup_loop_running),
        "interval_sec": _db_backup_interval_sec(),
        "retention_days": _db_backup_retention_days(),
        "backup_dir": _db_backup_dir(),
        "database_kind": _database_kind(_database_url_runtime()),
        "database_ref": _sanitize_db_url_for_logs(_database_url_runtime()),
        "encrypted": bool(_db_backup_encryption_key()),
    }


@app.get("/api/db-backups/list")
async def db_backups_list(limit: int = 30):
    return {"items": _list_db_backups(limit=max(1, min(limit, 200)))}


@app.post("/api/db-backups/run")
async def db_backups_run():
    if not _db_backup_encryption_key():
        raise HTTPException(status_code=400, detail="DB_BACKUP_ENCRYPTION_KEY missing")
    try:
        return _run_db_backup_once()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"backup_failed: {e}")


# Mount static files last
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon_path = os.path.join(static_dir, "favicon.svg")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="favicon_not_found")
