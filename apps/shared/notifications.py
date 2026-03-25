import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def telegram_enabled() -> bool:
    return _as_bool(os.getenv("NOTIFY_TELEGRAM_ENABLED", "false"))


def _telegram_config():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    return token, chat_id


def send_telegram_message(text: str) -> bool:
    if not telegram_enabled():
        return False

    token, chat_id = _telegram_config()
    if not token or not chat_id:
        return False

    payload = {
        "chat_id": chat_id,
        "text": text[:3900],  # telegram max ~4096
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def notify_event(title: str, details: dict | None = None) -> bool:
    details = details or {}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"{title}", f"ts: {ts}"]
    for k, v in details.items():
        lines.append(f"{k}: {v}")
    message = "\n".join(lines)
    return send_telegram_message(message)


def verify_telegram_secret(secret: str | None) -> bool:
    expected = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return False
    return (secret or "").strip() == expected


def parse_telegram_update_text(payload: dict) -> tuple[str, str]:
    msg = dict(payload.get("message") or payload.get("edited_message") or {})
    text = str(msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id") or "").strip()
    return text, chat_id

