"""Student reports and administrator violation decisions."""

from __future__ import annotations

from .base import BaseService, identifier, json_value, report_view
from .constants import ListingStatus, REPORT_CATEGORIES, ReportStatus
from .errors import MarketError, require
from .security import utc_now, validate_text
from .storage import many, one


class ReportService(BaseService):
    """Close related cases in the same transaction as a listing decision."""

    def close_pending_reports(self, connection, listing_id: str, final_state: str) -> int:
        pending = many(
            connection,
            "SELECT * FROM reports WHERE listing_id = ? AND status = 'pending'",
            (listing_id,),
        )
        now = utc_now()
        for report in pending:
            connection.execute(
                """UPDATE reports SET status = 'invalid_closed', handled_at = ?,
                   decision_reason = ? WHERE id = ?""",
                (now, f"商品已进入终态：{final_state}", report["id"]),
            )
            self.notify(
                connection, report["reporter_id"], f"report-invalid:{report['id']}",
                "report_closed", f"举报已失效关闭，商品终态：{final_state}",
            )
        return len(pending)

    def create_report(
        self, actor: dict, listing_id: str, category: str,
        description: str, evidence: list[str], request_id: str,
    ) -> dict:
        self.student(actor)
        require(category in REPORT_CATEGORIES, "invalid_category", "请选择举报类别")
        cleaned_description = validate_text(description, "举报说明", 1, 2000)
        require(
            isinstance(evidence, list) and len(evidence) <= 6,
            "invalid_evidence", "证据图片最多 6 张",
        )
        cleaned_evidence = []
        for item in evidence:
            value = validate_text(item, "证据地址", 1, 500)
            require(value.startswith("https://"), "invalid_evidence", "证据地址须使用 HTTPS")
            cleaned_evidence.append(value)

        def action(connection):
            listing = self.load_listing(connection, listing_id)
            existing = one(
                connection,
                """SELECT * FROM reports WHERE listing_id = ? AND reporter_id = ?
                   AND status = 'pending'""",
                (listing_id, actor["id"]),
            )
            if existing is not None:
                return report_view(existing)
            require(
                listing["status"] in (ListingStatus.PUBLISHED, ListingStatus.RESERVED),
                "invalid_state", "当前商品不能举报", 409,
            )
            report_id = identifier()
            connection.execute(
                """INSERT INTO reports
                   (id, listing_id, reporter_id, category, description,
                    evidence_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    report_id, listing_id, actor["id"], category,
                    cleaned_description, json_value(cleaned_evidence), utc_now(),
                ),
            )
            self.audit(
                connection, actor["id"], "report.create", report_id,
                None, ReportStatus.PENDING, "success", request_id,
            )
            return report_view(self.load_report(connection, report_id))

        return self.mutate(
            actor, request_id, "report.create", listing_id,
            {
                "category": category, "description": cleaned_description,
                "evidence": cleaned_evidence,
            }, action,
        )

    def decide_report(
        self, actor: dict, report_id: str, violation: bool,
        reason: str, request_id: str,
    ) -> dict:
        self.admin(actor)
        require(isinstance(violation, bool), "invalid_input", "处理结果必须为布尔值")
        cleaned_reason = validate_text(reason, "处理理由", 1, 1000)

        def action(connection):
            report = self.load_report(connection, report_id)
            require(
                report["status"] == ReportStatus.PENDING,
                "invalid_state", "举报已处理", 409,
            )
            listing = self.load_listing(connection, report["listing_id"])
            if listing["status"] not in (ListingStatus.PUBLISHED, ListingStatus.RESERVED):
                self.close_pending_reports(connection, listing["id"], listing["status"])
                return {
                    "status": "invalid_closed",
                    "listing_status": listing["status"],
                    "report": report_view(self.load_report(connection, report_id)),
                }
            now = utc_now()
            if not violation:
                connection.execute(
                    """UPDATE reports SET status = 'rejected', handled_by = ?,
                       handled_at = ?, decision_reason = ? WHERE id = ?""",
                    (actor["id"], now, cleaned_reason, report_id),
                )
                self.audit(
                    connection, actor["id"], "report.decide", report_id,
                    ReportStatus.PENDING, ReportStatus.REJECTED,
                    "success", request_id, cleaned_reason,
                )
                self.notify(
                    connection, report["reporter_id"], f"report-rejected:{report_id}",
                    "report_result", f"举报未认定违规：{cleaned_reason}",
                )
                return report_view(self.load_report(connection, report_id))

            connection.execute(
                """UPDATE listings SET status = 'violation_removed',
                   version = version + 1, updated_at = ? WHERE id = ?""",
                (now, listing["id"]),
            )
            active = one(
                connection,
                """SELECT * FROM reservations WHERE listing_id = ?
                   AND status IN ('pending_seller', 'confirmed')""",
                (listing["id"],),
            )
            if active:
                connection.execute(
                    """UPDATE reservations SET status = 'violation_terminated',
                       ended_at = ?, end_reason = ? WHERE id = ?""",
                    (now, cleaned_reason, active["id"]),
                )
                self.notify(
                    connection, active["buyer_id"],
                    f"reservation-violation:{active['id']}",
                    "reservation_terminated", "商品违规下架，预约已终止",
                )
            connection.execute(
                """UPDATE reports SET status = 'violation_confirmed',
                   handled_by = ?, handled_at = ?, decision_reason = ? WHERE id = ?""",
                (actor["id"], now, cleaned_reason, report_id),
            )
            others = many(
                connection,
                """SELECT * FROM reports WHERE listing_id = ? AND id != ?
                   AND status = 'pending'""",
                (listing["id"], report_id),
            )
            for other in others:
                connection.execute(
                    """UPDATE reports SET status = 'merged', handled_by = ?,
                       handled_at = ?, decision_reason = ?, merged_into_id = ?
                       WHERE id = ?""",
                    (actor["id"], now, cleaned_reason, report_id, other["id"]),
                )
                self.notify(
                    connection, other["reporter_id"],
                    f"report-merged:{other['id']}", "report_result",
                    f"举报已合并处理，关联处理编号 {report_id}：{cleaned_reason}",
                )
            self.notify(
                connection, report["reporter_id"], f"report-violation:{report_id}",
                "report_result", f"举报确认违规：{cleaned_reason}",
            )
            self.notify(
                connection, listing["seller_id"], f"listing-violation:{listing['id']}",
                "listing_removed", f"商品因违规下架：{cleaned_reason}",
            )
            self.audit(
                connection, actor["id"], "report.decide", report_id,
                ReportStatus.PENDING, ReportStatus.VIOLATION,
                "success", request_id, cleaned_reason,
            )
            return {
                "report": report_view(self.load_report(connection, report_id)),
                "merged_count": len(others),
                "listing_status": ListingStatus.VIOLATION,
            }

        result = self.mutate(
            actor, request_id, "report.decide", report_id,
            {"violation": violation, "reason": cleaned_reason}, action,
        )
        if isinstance(result, dict) and result.get("status") == "invalid_closed":
            raise MarketError(
                "listing_terminal",
                f"商品已进入终态 {result['listing_status']}，举报已失效关闭；请刷新页面",
                409,
            )
        return result

    def report_detail(self, actor: dict, report_id: str) -> dict:
        require(actor is not None, "unauthorized", "请先登录", 401)
        with self.storage.transaction() as connection:
            report = self.load_report(connection, report_id)
            require(
                actor["role"] == "admin" or actor["id"] == report["reporter_id"],
                "forbidden", "无权查看举报", 403,
            )
            return report_view(report)

    def my_reports(self, actor: dict) -> list[dict]:
        self.student(actor)
        with self.storage.transaction() as connection:
            return [
                report_view(row) for row in many(
                    connection,
                    "SELECT * FROM reports WHERE reporter_id = ? ORDER BY created_at DESC",
                    (actor["id"],),
                )
            ]

    def admin_reports(self, actor: dict, status: str | None = None) -> list[dict]:
        self.admin(actor)
        with self.storage.transaction() as connection:
            if status:
                rows = many(
                    connection,
                    "SELECT * FROM reports WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                rows = many(connection, "SELECT * FROM reports ORDER BY created_at DESC")
            return [report_view(row) for row in rows]
