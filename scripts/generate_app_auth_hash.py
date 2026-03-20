#!/usr/bin/env python3
import getpass
import os
import base64
import hashlib


def main():
    password = getpass.getpass("Nueva contraseña de acceso: ").strip()
    if not password:
        raise SystemExit("Contraseña vacía.")
    confirm = getpass.getpass("Confirma contraseña: ").strip()
    if password != confirm:
        raise SystemExit("No coincide la confirmación.")
    iterations = 240000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("utf-8")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("utf-8")
    # Use ":" delimiter to avoid docker-compose interpolation issues with "$".
    hashed = f"pbkdf2_sha256:{iterations}:{salt_b64}:{digest_b64}"
    print("\nGuarda esto en .env:")
    print(f"APP_AUTH_PASSWORD_HASH={hashed}")


if __name__ == "__main__":
    main()
