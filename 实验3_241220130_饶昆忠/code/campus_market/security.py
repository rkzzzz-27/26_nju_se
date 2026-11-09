"""Credential and token helpers using only the Python standard library."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone

from .errors import MarketError, require


EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)$")
HASH_ITERATIONS = 240_000


def utc_now() -> str:
    """Return a lexically sortable UTC timestamp with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(email: str, allowed_domain: str) -> str:
    require(isinstance(email, str), "invalid_email", "邮箱必须是字符串")
    candidate = email.strip().lower()
    match = EMAIL_PATTERN.fullmatch(candidate)
    require(match is not None, "invalid_email", "邮箱格式不正确")
    require(
        match.group(1) == allowed_domain.lower(),
        "school_email_required",
        "请使用配置的学校邮箱域名",
    )
    return candidate


def validate_password(password: str) -> None:
    require(isinstance(password, str), "invalid_password", "密码必须是字符串")
    require(8 <= len(password) <= 128, "invalid_password", "密码长度须为 8 到 128 位")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds)
        )
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def validate_text(value: str, name: str, minimum: int, maximum: int) -> str:
    require(isinstance(value, str), "invalid_input", f"{name}必须是字符串")
    cleaned = value.strip()
    require(
        minimum <= len(cleaned) <= maximum,
        "invalid_input",
        f"{name}长度须为 {minimum} 到 {maximum} 位",
    )
    return cleaned


def validate_request_id(request_id: str) -> str:
    return validate_text(request_id, "请求编号", 1, 100)


def require_authenticated(actor: dict | None) -> dict:
    if actor is None:
        raise MarketError("unauthorized", "请先登录", 401)
    return actor
