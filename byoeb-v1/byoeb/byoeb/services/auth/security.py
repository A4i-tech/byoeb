import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)

from byoeb.chat_app.configuration import config as env_config

_TOKEN_TTL_SECONDS = int(env_config.env_auth_token_ttl_seconds or "3600")
_TOKEN_SECRET = env_config.env_auth_token_secret or ""
if not _TOKEN_SECRET:
    raise RuntimeError("AUTH_TOKEN_SECRET must be set for token signing.")

_PBKDF2_ITERATIONS = int(env_config.env_auth_password_iterations or "200000")


def hash_password(password: str, salt: bytes | None = None) -> Tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return salt.hex(), hashed.hex()


def verify_password(password: str, user_doc: Dict[str, Any]) -> bool:
    password_hash = user_doc.get("password_hash")
    password_salt = user_doc.get("password_salt")
    if password_hash and password_salt:
        try:
            salt_bytes = bytes.fromhex(password_salt)
        except ValueError:
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, _PBKDF2_ITERATIONS).hex()
        return hmac.compare_digest(check, password_hash)

    stored_password = user_doc.get("password")
    if stored_password is not None:
        return hmac.compare_digest(stored_password, password)

    return False


def create_access_token(subject: str, tenant_id: UUID) -> Tuple[str, int]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_TOKEN_TTL_SECONDS)
    payload = {"sub": subject, "tenant_id": str(tenant_id), "exp": int(expires_at.timestamp())}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_TOKEN_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    token = ".".join([
        base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    ])
    return token, _TOKEN_TTL_SECONDS


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        raise ValueError("Invalid token format")

    payload_padding = "=" * (-len(payload_b64) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + payload_padding)
    expected_signature = hmac.new(_TOKEN_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    signature_padding = "=" * (-len(signature_b64) % 4)
    if not hmac.compare_digest(expected_signature, base64.urlsafe_b64decode(signature_b64 + signature_padding)):
        raise ValueError("Invalid token signature")

    payload = json.loads(payload_bytes.decode("utf-8"))
    exp = payload.get("exp")
    if exp is None:
        raise ValueError("Token missing exp claim")
    if int(exp) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expired")
    return payload
