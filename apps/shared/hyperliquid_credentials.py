"""
Resolución de credenciales Hyperliquid: .env en texto o almacén cifrado en BD.

Prioridad:
1) HYPERLIQUID_WALLET_ADDRESS + HYPERLIQUID_SIGNING_KEY válidos en entorno (.env cargado en proceso).
2) Si hay APP_CREDENTIALS_FERNET_KEY y fila `hyperliquid` en encrypted_credentials, descifrar JSON.

La clave Fernet nunca se guarda en la BD; solo en variables de entorno del servidor.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

HL_CREDENTIAL_ROW_ID = "hyperliquid"

_cache: Optional[Tuple[Optional[str], Optional[str], float]] = None
_CACHE_TTL_SEC = 30.0


def _valid_wallet(wallet: Optional[str]) -> bool:
    if not wallet:
        return False
    value = wallet.strip()
    return value.startswith("0x") and len(value) == 42


def _valid_private_key(private_key: Optional[str]) -> bool:
    if not private_key:
        return False
    value = private_key.strip()
    if "tu_nueva_clave_de_agente_aqui" in value.lower():
        return False
    if not value.startswith("0x") or len(value) != 66:
        return False
    hex_part = value[2:]
    return all(ch in "0123456789abcdefABCDEF" for ch in hex_part)


def _fernet_instance() -> Optional[Fernet]:
    key = os.getenv("APP_CREDENTIALS_FERNET_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        return None


def fernet_configured() -> bool:
    return _fernet_instance() is not None


def invalidate_hyperliquid_credentials_cache() -> None:
    global _cache
    _cache = None


def encrypted_blob_exists(db: Session) -> bool:
    from apps.shared.models import EncryptedCredentialDB

    row = db.query(EncryptedCredentialDB).filter(EncryptedCredentialDB.id == HL_CREDENTIAL_ROW_ID).first()
    return bool(row and row.ciphertext)


def save_hyperliquid_credentials_encrypted(
    wallet: str,
    signing_key: str,
    db: Session,
) -> None:
    """Cifra wallet + signing_key y persiste un único registro. Requiere APP_CREDENTIALS_FERNET_KEY."""
    from apps.shared.models import EncryptedCredentialDB

    f = _fernet_instance()
    if not f:
        raise RuntimeError("APP_CREDENTIALS_FERNET_KEY no configurada o inválida")

    payload = json.dumps(
        {"v": 1, "wallet": wallet.strip(), "signing_key": signing_key.strip()},
        ensure_ascii=False,
    )
    token = f.encrypt(payload.encode("utf-8")).decode("ascii")

    row = db.query(EncryptedCredentialDB).filter(EncryptedCredentialDB.id == HL_CREDENTIAL_ROW_ID).first()
    if row:
        row.ciphertext = token
    else:
        db.add(EncryptedCredentialDB(id=HL_CREDENTIAL_ROW_ID, ciphertext=token))
    db.commit()
    invalidate_hyperliquid_credentials_cache()


def delete_hyperliquid_encrypted_credentials(db: Session) -> None:
    from apps.shared.models import EncryptedCredentialDB

    db.query(EncryptedCredentialDB).filter(EncryptedCredentialDB.id == HL_CREDENTIAL_ROW_ID).delete()
    db.commit()
    invalidate_hyperliquid_credentials_cache()


def _decrypt_blob(db: Session) -> Optional[dict[str, Any]]:
    from apps.shared.models import EncryptedCredentialDB

    f = _fernet_instance()
    if not f:
        return None
    row = db.query(EncryptedCredentialDB).filter(EncryptedCredentialDB.id == HL_CREDENTIAL_ROW_ID).first()
    if not row or not row.ciphertext:
        return None
    try:
        raw = f.decrypt(row.ciphertext.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (InvalidToken, json.JSONDecodeError, UnicodeError):
        return None
    return None


def get_hyperliquid_wallet_and_key() -> Tuple[Optional[str], Optional[str]]:
    """
    Devuelve (wallet_address, signing_key) o (None, None) si no hay forma válida de firmar.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and (now - _cache[2]) < _CACHE_TTL_SEC:
        return _cache[0], _cache[1]

    wa = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip()
    sk = os.getenv("HYPERLIQUID_SIGNING_KEY", "").strip()

    if _valid_wallet(wa) and _valid_private_key(sk):
        _cache = (wa, sk, now)
        return wa, sk

    from apps.shared.database import SessionLocal

    db = SessionLocal()
    try:
        data = _decrypt_blob(db)
        if not data:
            _cache = (None, None, now)
            return None, None

        wa2 = (data.get("wallet") or "").strip()
        sk2 = (data.get("signing_key") or "").strip()

        # Wallet en .env tiene prioridad si está definida (coherencia con UI)
        wallet_out = wa if _valid_wallet(wa) else wa2
        if not _valid_wallet(wallet_out) or not _valid_private_key(sk2):
            _cache = (None, None, now)
            return None, None

        _cache = (wallet_out, sk2, now)
        return wallet_out, sk2
    finally:
        db.close()
