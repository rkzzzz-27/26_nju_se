"""School email registration, sessions and account administration."""

from __future__ import annotations

import hashlib
import secrets

from .base import BaseService, identifier, public_account, timestamp_after
from .errors import require
from .security import (
    hash_password,
    new_token,
    new_verification_code,
    normalize_email,
    token_digest,
    utc_now,
    validate_text,
    verify_password,
)
from .storage import one


class AccountService(BaseService):
    """Account workflows and server-side bearer authentication."""

    def issue_code(self, email: str) -> dict:
        normalized = normalize_email(email, self.school_domain)
        code = new_verification_code()
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        with self.storage.transaction(write=True) as connection:
            require(
                one(connection, "SELECT id FROM accounts WHERE email = ?", (normalized,))
                is None,
                "email_exists",
                "邮箱已注册",
                409,
            )
            connection.execute(
                """INSERT INTO verification_codes
                   (email, code_hash, expires_at, issued_at, attempts)
                   VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(email) DO UPDATE SET
                     code_hash=excluded.code_hash,
                     expires_at=excluded.expires_at,
                     issued_at=excluded.issued_at,
                     attempts=0""",
                (normalized, digest, timestamp_after(600), utc_now()),
            )
        return {"email": normalized, "verification_code": code, "expires_in": 600}

    def register(self, email: str, code: str, password: str, contact: str) -> dict:
        normalized = normalize_email(email, self.school_domain)
        cleaned_contact = validate_text(contact, "联系方式", 1, 120)
        password_hash = hash_password(password)
        require(isinstance(code, str) and len(code) == 6, "invalid_code", "验证码错误")
        with self.storage.transaction(write=True) as connection:
            record = one(
                connection, "SELECT * FROM verification_codes WHERE email = ?", (normalized,)
            )
            require(record is not None, "invalid_code", "请先获取验证码")
            require(record["expires_at"] > utc_now(), "code_expired", "验证码已过期")
            require(record["attempts"] < 5, "code_locked", "验证码尝试次数过多")
            actual = hashlib.sha256(code.encode("utf-8")).hexdigest()
            if not secrets.compare_digest(actual, record["code_hash"]):
                connection.execute(
                    "UPDATE verification_codes SET attempts = attempts + 1 WHERE email = ?",
                    (normalized,),
                )
                self.audit(
                    connection, None, "register.verify", None,
                    None, None, "invalid_code", None, normalized,
                )
                return {"error": "invalid_code", "message": "验证码错误"}
            account_id = identifier()
            connection.execute(
                """INSERT INTO accounts
                   (id, role, email, password_hash, verified, contact, created_at)
                   VALUES (?, 'student', ?, ?, 1, ?, ?)""",
                (account_id, normalized, password_hash, cleaned_contact, utc_now()),
            )
            connection.execute(
                "DELETE FROM verification_codes WHERE email = ?", (normalized,)
            )
            self.audit(
                connection, account_id, "register.verify", account_id,
                None, "verified", "success",
            )
            account = one(connection, "SELECT * FROM accounts WHERE id = ?", (account_id,))
        return public_account(account)

    def login(self, email: str, password: str) -> dict:
        normalized = normalize_email(email, self.school_domain)
        require(isinstance(password, str), "invalid_password", "密码格式错误")
        with self.storage.transaction(write=True) as connection:
            account = one(
                connection, "SELECT * FROM accounts WHERE email = ?", (normalized,)
            )
            valid = (
                account is not None
                and bool(account["enabled"])
                and bool(account["verified"])
                and verify_password(password, account["password_hash"])
            )
            if not valid:
                self.audit(
                    connection, account["id"] if account else None,
                    "account.login", None, None, None,
                    "failure", None, "凭据错误或账号不可用",
                )
                return {"error": "login_failed", "message": "邮箱或密码错误"}
            token = new_token()
            connection.execute(
                """INSERT INTO sessions
                   (token_hash, account_id, expires_at, created_at)
                   VALUES (?, ?, ?, ?)""",
                (token_digest(token), account["id"], timestamp_after(86400), utc_now()),
            )
            self.audit(
                connection, account["id"], "account.login", account["id"],
                None, "authenticated", "success",
            )
        return {"token": token, "expires_in": 86400, "account": public_account(account)}

    def authenticate(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self.storage.transaction() as connection:
            return one(
                connection,
                """SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND a.enabled = 1""",
                (token_digest(token), utc_now()),
            )

    def logout(self, actor: dict, token: str) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        with self.storage.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ? AND account_id = ?",
                (token_digest(token), actor["id"]),
            )
        return {"logged_out": True}

    def my_profile(self, actor: dict) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        result = public_account(actor)
        result["contact"] = actor["contact"]
        return result

    def update_contact(self, actor: dict, contact: str, request_id: str) -> dict:
        self.student(actor)
        cleaned = validate_text(contact, "联系方式", 1, 120)

        def action(connection):
            current = one(
                connection, "SELECT contact FROM accounts WHERE id = ?", (actor["id"],)
            )
            connection.execute(
                "UPDATE accounts SET contact = ? WHERE id = ?",
                (cleaned, actor["id"]),
            )
            self.audit(
                connection, actor["id"], "account.contact", actor["id"],
                current["contact"], "updated", "success", request_id,
            )
            return {"contact": cleaned}

        return self.mutate(
            actor, request_id, "account.contact", actor["id"],
            {"contact": cleaned}, action,
        )

    def bootstrap_admin(self, email: str, password: str) -> dict:
        """Local owner command; deliberately not exposed as an HTTP endpoint."""
        normalized = normalize_email(email, self.school_domain)
        password_hash = hash_password(password)
        with self.storage.transaction(write=True) as connection:
            require(
                one(connection, "SELECT id FROM accounts WHERE email = ?", (normalized,))
                is None,
                "email_exists", "邮箱已注册", 409,
            )
            account_id = identifier()
            connection.execute(
                """INSERT INTO accounts
                   (id, role, email, password_hash, verified, contact, created_at)
                   VALUES (?, 'admin', ?, ?, 1, '', ?)""",
                (account_id, normalized, password_hash, utc_now()),
            )
            self.audit(
                connection, None, "admin.bootstrap", account_id,
                None, "enabled", "success", None, "本机命令开通",
            )
            account = one(connection, "SELECT * FROM accounts WHERE id = ?", (account_id,))
        return public_account(account)
