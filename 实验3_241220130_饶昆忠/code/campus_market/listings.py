"""Listing drafts, review, publishing and public search."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from .base import BaseService, identifier, json_value, listing_view
from .constants import ListingStatus
from .errors import MarketError, require
from .security import utc_now, validate_text
from .storage import many, one


def price_to_cents(value: str | int | float) -> int:
    """Convert user supplied yuan to exact integer cents."""
    require(not isinstance(value, bool), "invalid_price", "价格格式错误")
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MarketError("invalid_price", "价格格式错误") from None
    require(price.is_finite(), "invalid_price", "价格格式错误")
    require(price.as_tuple().exponent >= -2, "invalid_price", "价格最多两位小数")
    cents = int(price * 100)
    require(0 < cents <= 100_000_000, "invalid_price", "价格须大于零且不超过一百万元")
    return cents


def bound_to_cents(value: str | int | float) -> int:
    """Parse a nonnegative price bound, including zero."""
    require(not isinstance(value, bool), "invalid_price", "价格格式错误")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MarketError("invalid_price", "价格格式错误") from None
    require(amount.is_finite() and amount.as_tuple().exponent >= -2,
            "invalid_price", "价格最多两位小数")
    cents = int(amount * 100)
    require(0 <= cents <= 100_000_000, "invalid_price", "价格范围须在零到一百万元之间")
    return cents


def validate_images(images: list[str]) -> list[str]:
    require(isinstance(images, list), "invalid_images", "图片必须是数组")
    require(len(images) <= 9, "invalid_images", "最多上传 9 张图片")
    output = []
    for image in images:
        cleaned = validate_text(image, "图片地址", 1, 500)
        require(
            cleaned.startswith("https://"),
            "invalid_images",
            "图片地址须使用 HTTPS",
        )
        output.append(cleaned)
    return output


def validate_listing_content(payload: dict, complete: bool) -> dict:
    require(isinstance(payload, dict), "invalid_input", "商品内容必须是对象")
    result = {}
    if "title" in payload:
        result["title"] = validate_text(payload["title"], "名称", 1, 100)
    if "description" in payload:
        result["description"] = validate_text(payload["description"], "描述", 1, 3000)
    if "category" in payload:
        result["category"] = validate_text(payload["category"], "分类", 1, 40)
    if "price" in payload:
        result["price_cents"] = price_to_cents(payload["price"])
    if "images" in payload:
        result["images_json"] = json_value(validate_images(payload["images"]))
    if complete:
        require(result.get("title"), "incomplete_listing", "请填写名称")
        require(result.get("description"), "incomplete_listing", "请填写描述")
        require(result.get("category"), "incomplete_listing", "请填写分类")
        require(result.get("price_cents"), "incomplete_listing", "请填写价格")
        require(
            json.loads(result.get("images_json", "[]")),
            "incomplete_listing", "请上传图片",
        )
    return result


class ListingService(BaseService):
    """Manage the lifecycle shown by the Experiment 2 listing state diagram."""

    def create_listing(self, actor: dict, payload: dict, request_id: str) -> dict:
        self.student(actor)
        content = validate_listing_content(payload, complete=False)

        def action(connection):
            listing_id = identifier()
            now = utc_now()
            connection.execute(
                """INSERT INTO listings
                   (id, seller_id, title, description, category, price_cents,
                    images_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
                (
                    listing_id, actor["id"], content.get("title", ""),
                    content.get("description", ""), content.get("category", ""),
                    content.get("price_cents", 0), content.get("images_json", "[]"),
                    now, now,
                ),
            )
            self.audit(
                connection, actor["id"], "listing.create", listing_id,
                None, ListingStatus.DRAFT, "success", request_id,
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.create", "new", content, action,
        )

    def edit_listing(
        self, actor: dict, listing_id: str, payload: dict,
        expected_version: int, request_id: str,
    ) -> dict:
        self.student(actor)
        changes = validate_listing_content(payload, complete=False)
        require(bool(changes), "invalid_input", "至少修改一个字段")

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            require(listing["seller_id"] == actor["id"], "forbidden", "不能修改他人的商品", 403)
            self.check_version(listing, expected_version)
            require(
                listing["status"] in (
                    ListingStatus.DRAFT, ListingStatus.REJECTED, ListingStatus.PUBLISHED,
                ),
                "invalid_state", "当前状态不能编辑商品", 409,
            )
            merged = {**listing, **changes}
            if listing["status"] == ListingStatus.PUBLISHED:
                require(
                    bool(merged["title"]) and bool(merged["description"])
                    and bool(merged["category"]) and merged["price_cents"] > 0
                    and bool(json.loads(merged["images_json"])),
                    "incomplete_listing", "商品信息不完整",
                )
                next_status = ListingStatus.PENDING
            else:
                next_status = listing["status"]
            fields = [f"{name} = ?" for name in changes]
            args = list(changes.values())
            fields.extend(["status = ?", "version = version + 1", "updated_at = ?"])
            args.extend([next_status, utc_now(), listing_id])
            connection.execute(
                f"UPDATE listings SET {', '.join(fields)} WHERE id = ?", args
            )
            self.audit(
                connection, actor["id"], "listing.edit", listing_id,
                listing["status"], next_status, "success", request_id,
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.edit", listing_id,
            {"changes": changes, "version": expected_version}, action,
        )

    def submit_listing(
        self, actor: dict, listing_id: str, expected_version: int, request_id: str
    ) -> dict:
        self.student(actor)

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            require(listing["seller_id"] == actor["id"], "forbidden", "不能提交他人的商品", 403)
            self.check_version(listing, expected_version)
            require(
                listing["status"] in (ListingStatus.DRAFT, ListingStatus.REJECTED),
                "invalid_state", "当前状态不能提交审核", 409,
            )
            require(
                all((listing["title"], listing["description"], listing["category"]))
                and listing["price_cents"] > 0
                and bool(json.loads(listing["images_json"])),
                "incomplete_listing", "请补齐名称、描述、分类、价格和图片",
            )
            connection.execute(
                """UPDATE listings SET status = 'pending_review',
                   version = version + 1, updated_at = ? WHERE id = ?""",
                (utc_now(), listing_id),
            )
            self.audit(
                connection, actor["id"], "listing.submit", listing_id,
                listing["status"], ListingStatus.PENDING, "success", request_id,
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.submit", listing_id,
            {"version": expected_version}, action,
        )

    def withdraw_listing(
        self, actor: dict, listing_id: str, expected_version: int, request_id: str
    ) -> dict:
        self.student(actor)

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            require(listing["seller_id"] == actor["id"], "forbidden", "不能撤回他人的商品", 403)
            self.check_version(listing, expected_version)
            require(
                listing["status"] == ListingStatus.PENDING,
                "invalid_state", "仅待审核商品可撤回", 409,
            )
            connection.execute(
                """UPDATE listings SET status = 'draft', version = version + 1,
                   updated_at = ? WHERE id = ?""",
                (utc_now(), listing_id),
            )
            self.audit(
                connection, actor["id"], "listing.withdraw", listing_id,
                ListingStatus.PENDING, ListingStatus.DRAFT, "success", request_id,
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.withdraw", listing_id,
            {"version": expected_version}, action,
        )

    def review_listing(
        self, actor: dict, listing_id: str, approved: bool,
        reason: str, expected_version: int, request_id: str,
    ) -> dict:
        self.admin(actor)
        require(isinstance(approved, bool), "invalid_input", "审核结果必须为布尔值")
        cleaned_reason = validate_text(reason, "驳回理由", 1, 1000) if not approved else ""

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            self.check_version(listing, expected_version)
            require(
                listing["status"] == ListingStatus.PENDING,
                "invalid_state", "商品已不是待审核状态", 409,
            )
            next_status = ListingStatus.PUBLISHED if approved else ListingStatus.REJECTED
            now = utc_now()
            connection.execute(
                """UPDATE listings SET status = ?, version = version + 1,
                   audited_by = ?, audited_at = ?, audit_reason = ?,
                   published_at = ?, updated_at = ? WHERE id = ?""",
                (
                    next_status, actor["id"], now, cleaned_reason or None,
                    now if approved else listing["published_at"], now, listing_id,
                ),
            )
            self.audit(
                connection, actor["id"], "listing.review", listing_id,
                listing["status"], next_status, "success", request_id, cleaned_reason,
            )
            self.notify(
                connection, listing["seller_id"], f"listing-review:{listing_id}:{now}",
                "listing_review", "商品审核通过" if approved else f"商品审核驳回：{cleaned_reason}",
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.review", listing_id,
            {"approved": approved, "reason": cleaned_reason, "version": expected_version},
            action,
        )

    def remove_listing(
        self, actor: dict, listing_id: str, expected_version: int, request_id: str
    ) -> dict:
        self.student(actor)

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            require(listing["seller_id"] == actor["id"], "forbidden", "不能下架他人的商品", 403)
            self.check_version(listing, expected_version)
            require(
                listing["status"] == ListingStatus.PUBLISHED,
                "invalid_state", "仅已发布商品可由卖家下架", 409,
            )
            now = utc_now()
            connection.execute(
                """UPDATE listings SET status = 'seller_removed',
                   version = version + 1, updated_at = ? WHERE id = ?""",
                (now, listing_id),
            )
            self.close_pending_reports(connection, listing_id, "seller_removed")
            self.audit(
                connection, actor["id"], "listing.remove", listing_id,
                ListingStatus.PUBLISHED, ListingStatus.REMOVED, "success", request_id,
            )
            return listing_view(self.load_listing(connection, listing_id))

        return self.mutate(
            actor, request_id, "listing.remove", listing_id,
            {"version": expected_version}, action,
        )

    def public_listings(
        self, keyword: str = "", category: str = "",
        min_price: str | None = None, max_price: str | None = None,
        sort: str = "newest", limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        require(sort in ("newest", "price_asc", "price_desc"), "invalid_sort", "排序方式不支持")
        require(isinstance(limit, int) and 1 <= limit <= 100, "invalid_limit", "分页大小为 1 到 100")
        require(isinstance(offset, int) and offset >= 0, "invalid_offset", "偏移量不可为负")
        lower = bound_to_cents(min_price) if min_price is not None else None
        upper = bound_to_cents(max_price) if max_price is not None else None
        require(
            lower is None or upper is None or lower <= upper,
            "invalid_price_range", "价格下限不得高于上限",
        )
        conditions = ["status = 'published'"]
        args = []
        if keyword:
            conditions.append("(title LIKE ? OR description LIKE ?)")
            args.extend([f"%{keyword}%", f"%{keyword}%"])
        if category:
            conditions.append("category = ?")
            args.append(category)
        if lower is not None:
            conditions.append("price_cents >= ?")
            args.append(lower)
        if upper is not None:
            conditions.append("price_cents <= ?")
            args.append(upper)
        order = {
            "newest": "published_at DESC, id DESC",
            "price_asc": "price_cents ASC, published_at DESC",
            "price_desc": "price_cents DESC, published_at DESC",
        }[sort]
        query = (
            f"SELECT * FROM listings WHERE {' AND '.join(conditions)} "
            f"ORDER BY {order} LIMIT ? OFFSET ?"
        )
        with self.storage.transaction() as connection:
            rows = many(connection, query, tuple(args + [limit, offset]))
            return [listing_view(row) for row in rows]

    def listing_detail(self, actor: dict | None, listing_id: str) -> dict:
        with self.storage.transaction() as connection:
            listing = self.load_listing(connection, listing_id)
            if listing["status"] != ListingStatus.PUBLISHED:
                allowed = actor is not None and (
                    actor["role"] == "admin"
                    or actor["id"] == listing["seller_id"]
                    or one(
                        connection,
                        "SELECT id FROM reservations WHERE listing_id = ? AND buyer_id = ?",
                        (listing_id, actor["id"]),
                    ) is not None
                )
                require(allowed, "not_found", "商品不存在", 404)
            return listing_view(listing)

    def my_listings(self, actor: dict, status: str | None = None) -> list[dict]:
        self.student(actor)
        with self.storage.transaction() as connection:
            if status:
                rows = many(
                    connection,
                    """SELECT * FROM listings WHERE seller_id = ? AND status = ?
                       ORDER BY created_at DESC""",
                    (actor["id"], status),
                )
            else:
                rows = many(
                    connection,
                    "SELECT * FROM listings WHERE seller_id = ? ORDER BY created_at DESC",
                    (actor["id"],),
                )
            return [listing_view(row) for row in rows]

    def admin_listings(self, actor: dict, status: str | None = None) -> list[dict]:
        self.admin(actor)
        with self.storage.transaction() as connection:
            if status:
                rows = many(
                    connection,
                    "SELECT * FROM listings WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                rows = many(connection, "SELECT * FROM listings ORDER BY created_at DESC")
            return [listing_view(row) for row in rows]
