"""Reminder jobs, inbox, statistics and audit search."""

from __future__ import annotations

from .base import BaseService, parse_time
from .constants import (
    CONFIRMED_REMINDER_BEFORE_SECONDS,
    CONFIRMED_SECONDS,
    PENDING_REMINDER_SECONDS,
    PENDING_SECONDS,
    ReservationStatus,
)
from .errors import require
from .security import utc_now
from .storage import many, one


class OperationService(BaseService):
    """Read models and a retry-safe scheduler for time-based changes."""

    def run_due_jobs(self, now: str | None = None) -> dict:
        """Call at least once every five minutes in an actual deployment."""
        current = now or utc_now()
        parse_time(current)
        changed = 0
        reminders = 0
        with self.storage.transaction(write=True) as connection:
            reservations = many(
                connection,
                """SELECT * FROM reservations
                   WHERE status IN ('pending_seller', 'confirmed')
                   ORDER BY created_at""",
            )
            now_seconds = parse_time(current).timestamp()
            for reservation in reservations:
                listing = self.load_listing(connection, reservation["listing_id"])
                if reservation["status"] == ReservationStatus.PENDING:
                    elapsed = now_seconds - parse_time(reservation["created_at"]).timestamp()
                    if elapsed >= PENDING_SECONDS:
                        self._expire_if_due(connection, reservation, current)
                        changed += 1
                    elif (
                        elapsed >= PENDING_REMINDER_SECONDS
                        and not reservation["pending_reminded_at"]
                    ):
                        self.notify(
                            connection, listing["seller_id"],
                            f"pending-reminder:{reservation['id']}",
                            "pending_reminder", "预约已等待 12 小时，请及时处理",
                        )
                        self.notify(
                            connection, reservation["buyer_id"],
                            f"pending-progress:{reservation['id']}",
                            "pending_progress", "预约仍在等待卖家确认",
                        )
                        connection.execute(
                            """UPDATE reservations SET pending_reminded_at = ?
                               WHERE id = ?""",
                            (current, reservation["id"]),
                        )
                        reminders += 2
                elif reservation["status"] == ReservationStatus.CONFIRMED:
                    elapsed = now_seconds - parse_time(reservation["confirmed_at"]).timestamp()
                    if elapsed >= CONFIRMED_SECONDS:
                        self._expire_if_due(connection, reservation, current)
                        changed += 1
                    elif (
                        elapsed >= CONFIRMED_SECONDS - CONFIRMED_REMINDER_BEFORE_SECONDS
                        and not reservation["confirmed_reminded_at"]
                    ):
                        for recipient in (listing["seller_id"], reservation["buyer_id"]):
                            self.notify(
                                connection, recipient,
                                f"confirmed-reminder:{reservation['id']}",
                                "confirmed_reminder", "预约将在 24 小时内到期",
                            )
                        connection.execute(
                            """UPDATE reservations SET confirmed_reminded_at = ?
                               WHERE id = ?""",
                            (current, reservation["id"]),
                        )
                        reminders += 2
        return {"expired": changed, "reminders": reminders}

    def notifications(self, actor: dict, unread_only: bool = False) -> list[dict]:
        require(actor is not None, "unauthorized", "请先登录", 401)
        with self.storage.transaction() as connection:
            if unread_only:
                return many(
                    connection,
                    """SELECT * FROM notifications WHERE recipient_id = ?
                       AND read_at IS NULL ORDER BY created_at DESC LIMIT 100""",
                    (actor["id"],),
                )
            return many(
                connection,
                """SELECT * FROM notifications WHERE recipient_id = ?
                   ORDER BY created_at DESC LIMIT 100""",
                (actor["id"],),
            )

    def mark_notification_read(
        self, actor: dict, notification_id: str, request_id: str
    ) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)

        def action(connection):
            item = one(
                connection,
                "SELECT * FROM notifications WHERE id = ? AND recipient_id = ?",
                (notification_id, actor["id"]),
            )
            require(item is not None, "not_found", "消息不存在", 404)
            connection.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
                (utc_now(), notification_id),
            )
            return one(connection, "SELECT * FROM notifications WHERE id = ?", (notification_id,))

        return self.mutate(
            actor, request_id, "notification.read", notification_id, {}, action,
        )

    def monthly_statistics(self, actor: dict, month: str) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        require(
            isinstance(month, str) and len(month) == 7 and month[4] == "-"
            and month[:4].isdigit() and month[5:].isdigit()
            and 1 <= int(month[5:]) <= 12,
            "invalid_month", "月份格式须为 YYYY-MM",
        )
        with self.storage.transaction() as connection:
            if actor["role"] == "admin":
                row = one(
                    connection,
                    """SELECT COUNT(*) AS count,
                       COALESCE(SUM(r.price_snapshot_cents), 0) AS total_cents
                       FROM reservations r WHERE r.status = 'completed'
                       AND substr(r.ended_at, 1, 7) = ?""",
                    (month,),
                )
            else:
                self.student(actor)
                row = one(
                    connection,
                    """SELECT COUNT(*) AS count,
                       COALESCE(SUM(r.price_snapshot_cents), 0) AS total_cents
                       FROM reservations r JOIN listings l ON l.id = r.listing_id
                       WHERE r.status = 'completed' AND l.seller_id = ?
                       AND substr(r.ended_at, 1, 7) = ?""",
                    (actor["id"], month),
                )
        return {"month": month, "count": row["count"], "total_cents": row["total_cents"]}

    def audit_search(
        self, actor: dict, operation: str = "", actor_id: str = "",
        target_id: str = "", since: str = "", until: str = "",
        limit: int = 100,
    ) -> list[dict]:
        self.admin(actor)
        require(isinstance(limit, int) and 1 <= limit <= 500, "invalid_limit", "最多返回 500 条")
        clauses = ["1 = 1"]
        args = []
        for key, value in (
            ("operation", operation), ("actor_id", actor_id),
            ("target_id", target_id),
        ):
            if value:
                clauses.append(f"{key} = ?")
                args.append(value)
        if since:
            parse_time(since)
            clauses.append("occurred_at >= ?")
            args.append(since)
        if until:
            parse_time(until)
            clauses.append("occurred_at <= ?")
            args.append(until)
        query = (
            f"SELECT * FROM audit_logs WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC LIMIT ?"
        )
        with self.storage.transaction() as connection:
            return many(connection, query, tuple(args + [limit]))
