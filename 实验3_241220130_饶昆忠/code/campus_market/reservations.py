"""Atomic reservation and listing state changes."""

from __future__ import annotations

from .base import BaseService, identifier, parse_time
from .constants import (
    ACTIVE_RESERVATIONS,
    CANCEL_REASONS,
    CONFIRMED_SECONDS,
    ListingStatus,
    PENDING_SECONDS,
    ReservationStatus,
)
from .errors import require
from .security import utc_now, validate_text
from .storage import many, one


def reason_text(choice: str, details: str = "") -> str:
    require(choice in CANCEL_REASONS, "invalid_reason", "请选择规定的原因")
    if choice == "其他":
        return f"其他：{validate_text(details, '补充说明', 1, 500)}"
    require(not details or isinstance(details, str), "invalid_reason", "补充说明格式错误")
    return choice


class ReservationService(BaseService):
    """Enforces the state machine for both product and reservation."""

    def _active_reservation(self, connection, listing_id: str) -> dict | None:
        return one(
            connection,
            """SELECT * FROM reservations WHERE listing_id = ?
               AND status IN ('pending_seller', 'confirmed')""",
            (listing_id,),
        )

    def _expire_if_due(self, connection, reservation: dict, now: str) -> dict:
        deadline = None
        if reservation["status"] == ReservationStatus.PENDING:
            deadline = parse_time(reservation["created_at"]).timestamp() + PENDING_SECONDS
        elif reservation["status"] == ReservationStatus.CONFIRMED:
            deadline = parse_time(reservation["confirmed_at"]).timestamp() + CONFIRMED_SECONDS
        if deadline is None or parse_time(now).timestamp() < deadline:
            return reservation
        listing = self.load_listing(connection, reservation["listing_id"])
        connection.execute(
            """UPDATE reservations SET status = 'expired', ended_at = ?,
               end_reason = '到期自动失效' WHERE id = ?
               AND status IN ('pending_seller', 'confirmed')""",
            (now, reservation["id"]),
        )
        if listing["status"] == ListingStatus.RESERVED:
            connection.execute(
                """UPDATE listings SET status = 'published',
                   version = version + 1, updated_at = ? WHERE id = ?""",
                (now, listing["id"]),
            )
        self.audit(
            connection, None, "reservation.expire", reservation["id"],
            reservation["status"], ReservationStatus.EXPIRED, "success",
        )
        self.notify(
            connection, reservation["buyer_id"], f"reservation-expired:{reservation['id']}",
            "reservation_expired", "预约已到期失效",
        )
        self.notify(
            connection, listing["seller_id"], f"reservation-expired:{reservation['id']}",
            "reservation_expired", "预约已到期失效",
        )
        return self.load_reservation(connection, reservation["id"])

    def reserve(
        self, actor: dict, listing_id: str, expected_version: int,
        request_id: str,
    ) -> dict:
        self.student(actor)
        # Apply due expirations before checking whether a listing is available.
        self.run_due_jobs()

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            require(listing["seller_id"] != actor["id"], "own_listing", "不能预约自己的商品")
            existing = self._active_reservation(connection, listing_id)
            if existing is not None and existing["buyer_id"] == actor["id"]:
                return existing
            self.check_version(listing, expected_version)
            require(
                listing["status"] == ListingStatus.PUBLISHED and existing is None,
                "listing_unavailable", "商品当前不可预约", 409,
            )
            reservation_id = identifier()
            now = utc_now()
            connection.execute(
                """INSERT INTO reservations
                   (id, listing_id, buyer_id, request_id, price_snapshot_cents,
                    status, created_at) VALUES (?, ?, ?, ?, ?, 'pending_seller', ?)""",
                (
                    reservation_id, listing_id, actor["id"], request_id,
                    listing["price_cents"], now,
                ),
            )
            connection.execute(
                """UPDATE listings SET status = 'reserved', version = version + 1,
                   updated_at = ? WHERE id = ?""",
                (now, listing_id),
            )
            self.audit(
                connection, actor["id"], "reservation.create", reservation_id,
                None, ReservationStatus.PENDING, "success", request_id,
            )
            self.notify(
                connection, listing["seller_id"], f"reservation-created:{reservation_id}",
                "reservation_created", "有买家预约了你的商品，请在 24 小时内处理",
            )
            return self.load_reservation(connection, reservation_id)

        return self.mutate(
            actor, request_id, "reservation.create", listing_id,
            {"version": expected_version}, action,
        )

    def decide_reservation(
        self, actor: dict, reservation_id: str, approved: bool,
        reason: str, details: str, request_id: str,
    ) -> dict:
        self.student(actor)
        require(isinstance(approved, bool), "invalid_input", "决定必须为布尔值")
        cleaned_reason = "" if approved else reason_text(reason, details)
        self.run_due_jobs()

        def action(connection):
            reservation = self.load_reservation(connection, reservation_id)
            listing = self.load_listing(connection, reservation["listing_id"])
            require(listing["seller_id"] == actor["id"], "forbidden", "仅商品卖家可处理", 403)
            now = utc_now()
            reservation = self._expire_if_due(connection, reservation, now)
            require(
                reservation["status"] == ReservationStatus.PENDING,
                "invalid_state", "预约已不能处理", 409,
            )
            require(
                listing["status"] == ListingStatus.RESERVED,
                "invalid_state", "商品状态已变化", 409,
            )
            next_status = ReservationStatus.CONFIRMED if approved else ReservationStatus.REJECTED
            connection.execute(
                """UPDATE reservations SET status = ?, confirmed_at = ?,
                   ended_at = ?, end_reason = ? WHERE id = ?""",
                (
                    next_status, now if approved else None,
                    None if approved else now, cleaned_reason or None, reservation_id,
                ),
            )
            if not approved:
                connection.execute(
                    """UPDATE listings SET status = 'published',
                       version = version + 1, updated_at = ? WHERE id = ?""",
                    (now, listing["id"]),
                )
            self.audit(
                connection, actor["id"], "reservation.decide", reservation_id,
                ReservationStatus.PENDING, next_status, "success", request_id, cleaned_reason,
            )
            self.notify(
                connection, reservation["buyer_id"],
                f"reservation-decided:{reservation_id}", "reservation_decided",
                "卖家已确认预约" if approved else f"卖家拒绝预约：{cleaned_reason}",
            )
            return self.load_reservation(connection, reservation_id)

        return self.mutate(
            actor, request_id, "reservation.decide", reservation_id,
            {"approved": approved, "reason": cleaned_reason}, action,
        )

    def cancel_reservation(
        self, actor: dict, reservation_id: str,
        reason: str, details: str, request_id: str,
    ) -> dict:
        self.student(actor)
        cleaned_reason = reason_text(reason, details)
        self.run_due_jobs()

        def action(connection):
            reservation = self.load_reservation(connection, reservation_id)
            listing = self.load_listing(connection, reservation["listing_id"])
            is_buyer = reservation["buyer_id"] == actor["id"]
            is_seller = listing["seller_id"] == actor["id"]
            require(is_buyer or is_seller, "forbidden", "无权取消此预约", 403)
            now = utc_now()
            reservation = self._expire_if_due(connection, reservation, now)
            require(
                reservation["status"] in ACTIVE_RESERVATIONS,
                "invalid_state", "预约已结束", 409,
            )
            require(
                is_buyer or reservation["status"] == ReservationStatus.CONFIRMED,
                "invalid_state", "卖家只能取消已确认预约", 409,
            )
            next_status = (
                ReservationStatus.BUYER_CANCELLED if is_buyer
                else ReservationStatus.SELLER_CANCELLED
            )
            connection.execute(
                """UPDATE reservations SET status = ?, ended_at = ?,
                   end_reason = ? WHERE id = ?""",
                (next_status, now, cleaned_reason, reservation_id),
            )
            if listing["status"] == ListingStatus.RESERVED:
                connection.execute(
                    """UPDATE listings SET status = 'published',
                       version = version + 1, updated_at = ? WHERE id = ?""",
                    (now, listing["id"]),
                )
            self.audit(
                connection, actor["id"], "reservation.cancel", reservation_id,
                reservation["status"], next_status, "success", request_id, cleaned_reason,
            )
            recipient = listing["seller_id"] if is_buyer else reservation["buyer_id"]
            self.notify(
                connection, recipient, f"reservation-cancelled:{reservation_id}",
                "reservation_cancelled", f"预约已取消：{cleaned_reason}",
            )
            return self.load_reservation(connection, reservation_id)

        return self.mutate(
            actor, request_id, "reservation.cancel", reservation_id,
            {"reason": cleaned_reason}, action,
        )

    def complete_reservation(
        self, actor: dict, reservation_id: str, confirmed_receipt: bool,
        request_id: str,
    ) -> dict:
        self.student(actor)
        require(
            confirmed_receipt is True,
            "confirmation_required",
            "请先确认：我已线下收到商品，此操作不可撤销",
        )
        self.run_due_jobs()

        def action(connection):
            reservation = self.load_reservation(connection, reservation_id)
            require(
                reservation["buyer_id"] == actor["id"],
                "forbidden", "仅买家可确认完成", 403,
            )
            listing = self.load_listing(connection, reservation["listing_id"])
            now = utc_now()
            reservation = self._expire_if_due(connection, reservation, now)
            require(
                reservation["status"] == ReservationStatus.CONFIRMED
                and listing["status"] == ListingStatus.RESERVED,
                "invalid_state", "当前预约不能确认完成", 409,
            )
            connection.execute(
                """UPDATE reservations SET status = 'completed', ended_at = ?
                   WHERE id = ?""",
                (now, reservation_id),
            )
            connection.execute(
                """UPDATE listings SET status = 'completed',
                   version = version + 1, updated_at = ? WHERE id = ?""",
                (now, listing["id"]),
            )
            self.close_pending_reports(connection, listing["id"], "completed")
            self.audit(
                connection, actor["id"], "reservation.complete", reservation_id,
                ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED,
                "success", request_id,
            )
            self.notify(
                connection, listing["seller_id"], f"reservation-completed:{reservation_id}",
                "reservation_completed", "买家已确认线下收货，交易完成",
            )
            return self.load_reservation(connection, reservation_id)

        return self.mutate(
            actor, request_id, "reservation.complete", reservation_id,
            {"confirmed_receipt": True}, action,
        )

    def reservation_detail(self, actor: dict, reservation_id: str) -> dict:
        self.student(actor)
        with self.storage.transaction() as connection:
            reservation = self.load_reservation(connection, reservation_id)
            listing = self.load_listing(connection, reservation["listing_id"])
            require(
                actor["id"] in (reservation["buyer_id"], listing["seller_id"]),
                "forbidden", "无权查看此预约", 403,
            )
            return reservation

    def my_reservations(self, actor: dict, status: str | None = None) -> list[dict]:
        self.student(actor)
        with self.storage.transaction() as connection:
            if status:
                return many(
                    connection,
                    """SELECT * FROM reservations WHERE buyer_id = ? AND status = ?
                       ORDER BY created_at DESC""",
                    (actor["id"], status),
                )
            return many(
                connection,
                "SELECT * FROM reservations WHERE buyer_id = ? ORDER BY created_at DESC",
                (actor["id"],),
            )

    def seller_reservations(self, actor: dict, status: str | None = None) -> list[dict]:
        self.student(actor)
        with self.storage.transaction() as connection:
            query = (
                """SELECT r.* FROM reservations r JOIN listings l ON l.id = r.listing_id
                   WHERE l.seller_id = ?"""
            )
            args = [actor["id"]]
            if status:
                query += " AND r.status = ?"
                args.append(status)
            query += " ORDER BY r.created_at DESC"
            return many(connection, query, tuple(args))

    def other_contact(self, actor: dict, reservation_id: str) -> dict:
        self.student(actor)
        with self.storage.transaction(write=True) as connection:
            reservation = self.load_reservation(connection, reservation_id)
            listing = self.load_listing(connection, reservation["listing_id"])
            require(
                actor["id"] in (reservation["buyer_id"], listing["seller_id"]),
                "forbidden", "无权查看联系方式", 403,
            )
            reservation = self._expire_if_due(connection, reservation, utc_now())
            require(
                reservation["status"] == ReservationStatus.CONFIRMED
                and listing["status"] == ListingStatus.RESERVED,
                "contact_unavailable", "当前状态不提供对方联系方式", 403,
            )
            other_id = (
                listing["seller_id"] if actor["id"] == reservation["buyer_id"]
                else reservation["buyer_id"]
            )
            other = one(connection, "SELECT contact FROM accounts WHERE id = ?", (other_id,))
            return {"contact": other["contact"]}
