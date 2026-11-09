"""State names and controlled input choices shared by services."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class ListingStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending_review"
    REJECTED = "rejected"
    PUBLISHED = "published"
    RESERVED = "reserved"
    COMPLETED = "completed"
    REMOVED = "seller_removed"
    VIOLATION = "violation_removed"


class ReservationStatus(StrEnum):
    PENDING = "pending_seller"
    CONFIRMED = "confirmed"
    REJECTED = "seller_rejected"
    BUYER_CANCELLED = "buyer_cancelled"
    SELLER_CANCELLED = "seller_cancelled"
    EXPIRED = "expired"
    COMPLETED = "completed"
    VIOLATION = "violation_terminated"


class ReportStatus(StrEnum):
    PENDING = "pending"
    REJECTED = "rejected"
    VIOLATION = "violation_confirmed"
    MERGED = "merged"
    INVALID = "invalid_closed"


ACTIVE_RESERVATIONS = (ReservationStatus.PENDING, ReservationStatus.CONFIRMED)
REPORTABLE_LISTINGS = (ListingStatus.PUBLISHED, ListingStatus.RESERVED)
TERMINAL_LISTINGS = (
    ListingStatus.COMPLETED,
    ListingStatus.REMOVED,
    ListingStatus.VIOLATION,
)
CANCEL_REASONS = (
    "无法联系",
    "时间地点无法协调",
    "商品情况变化",
    "其他",
)
REPORT_CATEGORIES = (
    "虚假商品",
    "违禁物品",
    "价格欺诈",
    "其他",
)
PENDING_SECONDS = 24 * 60 * 60
CONFIRMED_SECONDS = 7 * 24 * 60 * 60
PENDING_REMINDER_SECONDS = 12 * 60 * 60
CONFIRMED_REMINDER_BEFORE_SECONDS = 24 * 60 * 60
