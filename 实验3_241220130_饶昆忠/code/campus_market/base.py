"""Common service helpers for authorization, receipts and audit logs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .constants import Role
from .errors import MarketError, require
from .security import utc_now, validate_request_id
from .storage import Storage, one


def identifier() -> str:
    return str(uuid.uuid4())


def timestamp_after(seconds: int) -> str:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + seconds, timezone.utc
    ).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def public_account(account: dict) -> dict:
    return {
        "id": account["id"],
        "role": account["role"],
        "email": account["email"],
        "verified": bool(account["verified"]),
        "created_at": account["created_at"],
    }


def listing_view(listing: dict) -> dict:
    result = dict(listing)
    result["images"] = json.loads(result.pop("images_json"))
    return result


def report_view(report: dict) -> dict:
    result = dict(report)
    result["evidence"] = json.loads(result.pop("evidence_json"))
    return result


class BaseService:
    """Shared transaction and security rules used by domain service mixins."""

    def __init__(self, database_path: str, school_domain: str):
        self.storage = Storage(database_path)
        self.school_domain = school_domain.strip().lower()
        require(bool(self.school_domain), "invalid_config", "需配置学校邮箱域名")

    @staticmethod
    def student(actor: dict | None) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        require(actor["role"] == Role.STUDENT, "forbidden", "仅学生可执行", 403)
        require(bool(actor["enabled"]), "forbidden", "账号已停用", 403)
        require(bool(actor["verified"]), "forbidden", "请先验证邮箱", 403)
        return actor

    @staticmethod
    def admin(actor: dict | None) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        require(actor["role"] == Role.ADMIN, "forbidden", "仅管理员可执行", 403)
        require(bool(actor["enabled"]), "forbidden", "管理员账号已停用", 403)
        return actor

    @staticmethod
    def load_listing(connection: sqlite3.Connection, listing_id: str) -> dict:
        listing = one(connection, "SELECT * FROM listings WHERE id = ?", (listing_id,))
        require(listing is not None, "not_found", "商品不存在", 404)
        return listing

    @staticmethod
    def load_reservation(connection: sqlite3.Connection, reservation_id: str) -> dict:
        reservation = one(
            connection, "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        )
        require(reservation is not None, "not_found", "预约不存在", 404)
        return reservation

    @staticmethod
    def load_report(connection: sqlite3.Connection, report_id: str) -> dict:
        report = one(connection, "SELECT * FROM reports WHERE id = ?", (report_id,))
        require(report is not None, "not_found", "举报不存在", 404)
        return report

    @staticmethod
    def check_version(record: dict, expected_version: int | None) -> None:
        if expected_version is None:
            return
        require(
            isinstance(expected_version, int) and not isinstance(expected_version, bool),
            "invalid_version",
            "版本号必须是整数",
        )
        require(
            record["version"] == expected_version,
            "stale_version",
            "页面版本已过期，请刷新后重试",
            409,
        )

    @staticmethod
    def audit(
        connection: sqlite3.Connection,
        actor_id: str | None,
        operation: str,
        target_id: str | None,
        before: str | None,
        after: str | None,
        result: str,
        request_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO audit_logs
               (id, actor_id, operation, target_id, before_state, after_state,
                result, request_id, reason, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                identifier(), actor_id, operation, target_id, before, after,
                result, request_id, reason, utc_now(),
            ),
        )

    @staticmethod
    def notify(
        connection: sqlite3.Connection,
        recipient_id: str,
        event_id: str,
        kind: str,
        content: str,
    ) -> None:
        connection.execute(
            """INSERT OR IGNORE INTO notifications
               (id, recipient_id, event_id, kind, content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (identifier(), recipient_id, event_id, kind, content, utc_now()),
        )

    def mutate(
        self,
        actor: dict,
        request_id: str,
        operation: str,
        target_id: str,
        parameters: dict,
        action: Callable[[sqlite3.Connection], dict],
    ) -> dict:
        """Serialize changes and replay the first result for an identical request.

        A savepoint lets us store a rejected first result without committing any
        partial writes made before a domain check failed.
        """
        validate_request_id(request_id)
        digest = hashlib.sha256(
            json_value({"operation": operation, "target": target_id, "params": parameters})
            .encode("utf-8")
        ).hexdigest()
        with self.storage.transaction(write=True) as connection:
            receipt = one(
                connection,
                "SELECT * FROM request_receipts WHERE account_id = ? AND request_id = ?",
                (actor["id"], request_id),
            )
            if receipt is not None:
                require(
                    receipt["request_digest"] == digest,
                    "request_id_conflict",
                    "请求编号已用于其他操作或参数",
                    409,
                )
                stored = json.loads(receipt["first_result_json"])
                if stored["ok"]:
                    return stored["data"]
                raise MarketError(**stored["error"])

            connection.execute("SAVEPOINT business_action")
            try:
                data = action(connection)
                connection.execute("RELEASE SAVEPOINT business_action")
                stored = {"ok": True, "data": data}
                outcome = None
            except MarketError as error:
                connection.execute("ROLLBACK TO SAVEPOINT business_action")
                connection.execute("RELEASE SAVEPOINT business_action")
                stored = {
                    "ok": False,
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "status": error.status,
                    },
                }
                outcome = error
                self.audit(
                    connection, actor["id"], operation, target_id,
                    None, None, error.code, request_id, error.message,
                )

            connection.execute(
                """INSERT INTO request_receipts
                   (account_id, request_id, operation, target_id,
                    request_digest, first_result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor["id"], request_id, operation, target_id,
                    digest, json_value(stored), utc_now(),
                ),
            )
        if outcome is not None:
            raise outcome
        return stored["data"]
