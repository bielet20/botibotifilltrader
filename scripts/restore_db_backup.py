#!/usr/bin/env python3
import argparse
import gzip
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet


def db_url_runtime() -> str:
    return (os.getenv("DATABASE_URL") or "").strip() or "sqlite:///./trading.db"


def db_kind(db_url: str) -> str:
    u = db_url.lower()
    if u.startswith("sqlite"):
        return "sqlite"
    if u.startswith("postgresql") or u.startswith("postgres"):
        return "postgresql"
    return "unknown"


def sqlite_file_path(db_url: str) -> Path:
    if db_url.startswith("sqlite:///"):
        candidate = db_url.replace("sqlite:///", "", 1)
        p = Path(candidate)
        if p.is_absolute():
            return p
        return (Path(__file__).resolve().parents[1] / p).resolve()
    if db_url.startswith("sqlite://"):
        return Path(db_url.replace("sqlite://", "", 1)).resolve()
    raise RuntimeError("invalid_sqlite_url")


def load_meta(backup_file: Path) -> dict:
    meta_file = Path(f"{backup_file}.meta.json")
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser(description="Restaura backup cifrado de base de datos")
    parser.add_argument("--file", required=True, help="Ruta al archivo .bin.enc")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permite restaurar sin confirmación interactiva",
    )
    args = parser.parse_args()

    enc_key = (os.getenv("DB_BACKUP_ENCRYPTION_KEY") or "").strip()
    if not enc_key:
        raise SystemExit("DB_BACKUP_ENCRYPTION_KEY no configurada.")

    backup_path = Path(args.file).expanduser().resolve()
    if not backup_path.exists():
        raise SystemExit(f"No existe backup: {backup_path}")

    db_url = db_url_runtime()
    kind = db_kind(db_url)
    if kind not in {"sqlite", "postgresql"}:
        raise SystemExit(f"Base de datos no soportada: {db_url}")

    meta = load_meta(backup_path)
    backup_kind = str(meta.get("database_kind") or "")
    if backup_kind and backup_kind != kind:
        raise SystemExit(f"Tipo de backup ({backup_kind}) no coincide con DB runtime ({kind}).")

    if not args.force:
        print(f"Se restaurará backup: {backup_path}")
        print(f"DB runtime detectada: {db_url}")
        ok = input("Escribe 'RESTORE' para confirmar: ").strip()
        if ok != "RESTORE":
            raise SystemExit("Cancelado por usuario.")

    encrypted = backup_path.read_bytes()
    compressed = Fernet(enc_key.encode("utf-8")).decrypt(encrypted)
    payload = gzip.decompress(compressed)

    if kind == "sqlite":
        target = sqlite_file_path(db_url)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            bak = target.with_suffix(target.suffix + f".pre_restore_{stamp}.bak")
            shutil.copy2(target, bak)
            print(f"Backup previo local: {bak}")
        target.write_bytes(payload)
        print(f"SQLite restaurada: {target}")
        return

    # PostgreSQL restore via psql
    proc = subprocess.run(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1"],
        input=payload,
        capture_output=True,
        text=False,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
        raise SystemExit(f"Restore PostgreSQL falló: {stderr.strip()}")
    print("PostgreSQL restaurada correctamente.")


if __name__ == "__main__":
    main()
