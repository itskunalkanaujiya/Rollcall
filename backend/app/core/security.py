"""Password hashing, JWT handling and at-rest encryption of biometric templates."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"


# ---- passwords -------------------------------------------------------------
def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; pre-hash so long passphrases are not truncated.
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    try:
        return bcrypt.checkpw(digest, hashed.encode())
    except ValueError:
        return False


# A real hash used to equalise timing when the username does not exist.
DUMMY_HASH = hash_password("not-a-real-password")


# ---- JWT -------------------------------------------------------------------
def create_access_token(user_id: int, token_version: int) -> tuple[str, datetime]:
    s = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    payload = {"sub": str(user_id), "ver": token_version, "exp": expires, "typ": "access"}
    return jwt.encode(payload, s.secret_key, algorithm=JWT_ALGORITHM), expires


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "access" else None


# ---- embedding encryption --------------------------------------------------
def _fernet() -> Fernet:
    # Accept any >=32 char secret; derive a valid Fernet key from it.
    raw = hashlib.sha256(get_settings().embedding_encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise ValueError(
            "Cannot decrypt stored face template: EMBEDDING_ENCRYPTION_KEY does not match "
            "the key used at enrollment."
        ) from exc
