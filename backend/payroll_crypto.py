"""Encrypt salary snapshots at rest. The key never goes into a payroll document."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_FILE = Path(__file__).resolve().parent / "payroll_data.key"


def _fernet() -> Fernet:
    raw = (os.environ.get("PAYROLL_DATA_KEY") or "").strip()
    if raw:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    secret = (os.environ.get("PAYROLL_DATA_SECRET") or "").strip()
    if secret:
        derived = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"kelasa-payroll-v1", 120_000, dklen=32)
        return Fernet(base64.urlsafe_b64encode(derived))
    if _KEY_FILE.exists():
        return Fernet(_KEY_FILE.read_text().strip().encode())
    key = Fernet.generate_key()
    _KEY_FILE.write_text(key.decode())
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    return Fernet(key)


def encrypt_json(payload: dict) -> str:
    blob = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return _fernet().encrypt(blob).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    return json.loads(_fernet().decrypt(token.encode()).decode())
