"""Behavior tests for the main state transitions and authorization rules."""

from __future__ import annotations

import concurrent.futures
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from campus_market.errors import MarketError
from campus_market.http_api import make_handler
from campus_market.service import MarketService
from campus_market.storage import one


def rid() -> str:
    return str(uuid.uuid4())


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "market.db")
        self.service = MarketService(self.database, "campus.edu.cn")
        self.seller = self.student("seller")
        self.buyer = self.student("buyer")
        self.other = self.student("other")
        self.admin = self.service.bootstrap_admin("admin@campus.edu.cn", "passw0rd-admin")
        self.admin = self.actor(self.admin["id"])

    def tearDown(self):
        self.directory.cleanup()

    def actor(self, account_id: str) -> dict:
        with self.service.storage.transaction() as connection:
            return one(connection, "SELECT * FROM accounts WHERE id = ?", (account_id,))

    def student(self, name: str) -> dict:
        email = f"{name}@campus.edu.cn"
        code = self.service.issue_code(email)["verification_code"]
        account = self.service.register(email, code, "passw0rd-student", name + "@phone")
        return self.actor(account["id"])

    def published(self, price="10.50") -> dict:
        listing = self.service.create_listing(
            self.seller,
            {
                "title": "二手教材", "description": "九成新，校内当面交付",
                "category": "图书", "price": price,
                "images": ["https://example.org/book.jpg"],
            },
            rid(),
        )
        submitted = self.service.submit_listing(
            self.seller, listing["id"], listing["version"], rid()
        )
        return self.service.review_listing(
            self.admin, listing["id"], True, "", submitted["version"], rid()
        )

    def confirmed(self) -> tuple[dict, dict]:
        listing = self.published()
        reservation = self.service.reserve(
            self.buyer, listing["id"], listing["version"], rid()
        )
        reservation = self.service.decide_reservation(
            self.seller, reservation["id"], True, "", "", rid()
        )
        return listing, reservation

    def test_registration_login_and_role_permissions(self):
        login = self.service.login("buyer@campus.edu.cn", "passw0rd-student")
        self.assertIn("token", login)
        self.assertEqual(self.service.authenticate(login["token"])["id"], self.buyer["id"])
        self.assertEqual(
            self.service.login("buyer@campus.edu.cn", "wrong")["error"],
            "login_failed",
        )
        self.assertEqual(self.service.logout(self.buyer, login["token"]), {"logged_out": True})
        self.assertIsNone(self.service.authenticate(login["token"]))
        with self.assertRaises(MarketError):
            self.service.create_listing(self.admin, {}, rid())
        with self.assertRaises(MarketError):
            self.service.admin_listings(self.buyer)

    def test_draft_review_search_and_stale_version(self):
        listing = self.service.create_listing(self.seller, {"title": "草稿"}, rid())
        self.assertEqual(self.service.public_listings(), [])
        edited = self.service.edit_listing(
            self.seller, listing["id"],
            {
                "description": "完整描述", "category": "图书", "price": "20.00",
                "images": ["https://example.org/image.jpg"],
            },
            listing["version"], rid(),
        )
        with self.assertRaises(MarketError) as context:
            self.service.submit_listing(self.seller, listing["id"], listing["version"], rid())
        self.assertEqual(context.exception.code, "stale_version")
        submitted = self.service.submit_listing(
            self.seller, listing["id"], edited["version"], rid()
        )
        with self.assertRaises(MarketError):
            self.service.listing_detail(None, listing["id"])
        published = self.service.review_listing(
            self.admin, listing["id"], True, "", submitted["version"], rid()
        )
        self.assertEqual(published["status"], "published")
        self.assertEqual(len(self.service.public_listings(keyword="草稿", min_price="20.00")), 1)
        self.assertEqual(self.service.public_listings(max_price="19.99"), [])
        with self.assertRaises(MarketError):
            self.service.public_listings(min_price="21", max_price="20")

    def test_reservation_replay_conflict_and_price_snapshot(self):
        listing = self.published("12.34")
        request = rid()
        first = self.service.reserve(self.buyer, listing["id"], listing["version"], request)
        repeated = self.service.reserve(self.buyer, listing["id"], listing["version"], request)
        self.assertEqual(first["id"], repeated["id"])
        self.assertEqual(first["price_snapshot_cents"], 1234)
        with self.assertRaises(MarketError) as context:
            self.service.reserve(self.buyer, listing["id"], listing["version"] + 1, request)
        self.assertEqual(context.exception.code, "request_id_conflict")
        with self.assertRaises(MarketError):
            self.service.reserve(self.other, listing["id"], listing["version"], rid())
        self.assertEqual(
            self.service.reserve(self.buyer, listing["id"], listing["version"], rid())["id"],
            first["id"],
        )
        with self.service.storage.transaction() as connection:
            count = one(
                connection,
                """SELECT COUNT(*) AS count FROM reservations
                   WHERE listing_id = ? AND status IN ('pending_seller', 'confirmed')""",
                (listing["id"],),
            )["count"]
        self.assertEqual(count, 1)

    def test_contact_only_during_confirmed_and_completion(self):
        listing = self.published()
        reservation = self.service.reserve(self.buyer, listing["id"], listing["version"], rid())
        with self.assertRaises(MarketError):
            self.service.other_contact(self.buyer, reservation["id"])
        confirmed = self.service.decide_reservation(
            self.seller, reservation["id"], True, "", "", rid()
        )
        self.assertEqual(
            self.service.other_contact(self.buyer, reservation["id"])["contact"],
            self.seller["contact"],
        )
        with self.assertRaises(MarketError):
            self.service.other_contact(self.other, reservation["id"])
        with self.assertRaises(MarketError):
            self.service.complete_reservation(self.seller, reservation["id"], True, rid())
        completed = self.service.complete_reservation(
            self.buyer, reservation["id"], True, rid()
        )
        self.assertEqual(completed["status"], "completed")
        with self.assertRaises(MarketError):
            self.service.other_contact(self.buyer, reservation["id"])
        month = completed["ended_at"][:7]
        statistics = self.service.monthly_statistics(self.seller, month)
        self.assertEqual(statistics["count"], 1)
        self.assertEqual(statistics["total_cents"], 1050)

    def test_report_merge_and_transactional_violation(self):
        listing = self.published()
        reservation = self.service.reserve(self.buyer, listing["id"], listing["version"], rid())
        first = self.service.create_report(
            self.buyer, listing["id"], "虚假商品", "描述与实物不符", [], rid()
        )
        repeated = self.service.create_report(
            self.buyer, listing["id"], "虚假商品", "换一条说明", [], rid()
        )
        self.assertEqual(first["id"], repeated["id"])
        second = self.service.create_report(
            self.other, listing["id"], "价格欺诈", "报价不一致", [], rid()
        )
        decision = self.service.decide_report(
            self.admin, first["id"], True, "确认违规", rid()
        )
        self.assertEqual(decision["merged_count"], 1)
        self.assertEqual(self.service.report_detail(self.other, second["id"])["status"], "merged")
        self.assertEqual(
            self.service.reservation_detail(self.buyer, reservation["id"])["status"],
            "violation_terminated",
        )
        self.assertEqual(
            self.service.listing_detail(self.admin, listing["id"])["status"],
            "violation_removed",
        )

    def test_due_jobs_idempotent_and_cancellation(self):
        listing = self.published()
        reservation = self.service.reserve(self.buyer, listing["id"], listing["version"], rid())
        created = datetime.fromisoformat(reservation["created_at"])
        at_12h = (created + timedelta(hours=12, seconds=1)).isoformat(timespec="seconds")
        first = self.service.run_due_jobs(at_12h)
        self.assertEqual(first["reminders"], 2)
        self.assertEqual(self.service.run_due_jobs(at_12h)["reminders"], 0)
        at_24h = (created + timedelta(hours=24, seconds=1)).isoformat(timespec="seconds")
        self.assertEqual(self.service.run_due_jobs(at_24h)["expired"], 1)
        self.assertEqual(self.service.run_due_jobs(at_24h)["expired"], 0)
        with self.assertRaises(MarketError):
            self.service.cancel_reservation(
                self.buyer, reservation["id"], "无法联系", "", rid()
            )
        self.assertEqual(self.service.listing_detail(None, listing["id"])["status"], "published")

    def test_two_buyers_racing_for_one_listing(self):
        listing = self.published()
        buyers = [self.buyer, self.other]

        def attempt(buyer):
            try:
                return self.service.reserve(buyer, listing["id"], listing["version"], rid())
            except MarketError as error:
                return error.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, buyers))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertEqual(len(self.service.public_listings()), 0)

    def test_one_hundred_reservation_races(self):
        """Exercise the REQ-023 acceptance count with two buyers per listing."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for _ in range(100):
                listing = self.published()
                submitted = [
                    pool.submit(
                        self.service.reserve, buyer, listing["id"],
                        listing["version"], rid(),
                    )
                    for buyer in (self.buyer, self.other)
                ]
                winners = 0
                for future in submitted:
                    try:
                        future.result()
                        winners += 1
                    except MarketError as error:
                        self.assertIn(error.code, ("stale_version", "listing_unavailable"))
                self.assertEqual(winners, 1)
                with self.service.storage.transaction() as connection:
                    active = one(
                        connection,
                        """SELECT COUNT(*) AS count FROM reservations
                           WHERE listing_id = ?
                           AND status IN ('pending_seller', 'confirmed')""",
                        (listing["id"],),
                    )["count"]
                self.assertEqual(active, 1)

    def test_report_closes_when_listing_completes_first(self):
        listing, reservation = self.confirmed()
        report = self.service.create_report(
            self.other, listing["id"], "虚假商品", "商品描述不符", [], rid()
        )
        self.service.complete_reservation(self.buyer, reservation["id"], True, rid())
        with self.assertRaises(MarketError) as context:
            self.service.decide_report(
                self.admin, report["id"], True, "确认违规", rid()
            )
        self.assertEqual(context.exception.code, "invalid_state")
        self.assertEqual(
            self.service.report_detail(self.other, report["id"])["status"],
            "invalid_closed",
        )
        self.assertEqual(
            self.service.listing_detail(self.admin, listing["id"])["status"],
            "completed",
        )

    def test_http_login_create_and_public_query(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def call(path, method="GET", data=None, token=None):
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if data is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                base + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers=headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                try:
                    return error.code, json.load(error)
                finally:
                    error.close()

        try:
            status, login = call(
                "/auth/login", "POST",
                {"email": "seller@campus.edu.cn", "password": "passw0rd-student"},
            )
            self.assertEqual(status, 200)
            status, listing = call(
                "/listings", "POST",
                {
                    "request_id": rid(),
                    "listing": {
                        "title": "自行车", "description": "可在校门口交付",
                        "category": "出行", "price": "99.00",
                        "images": ["https://example.org/bike.jpg"],
                    },
                },
                login["token"],
            )
            self.assertEqual(status, 201)
            self.assertEqual(listing["status"], "draft")
            status, found = call("/listings")
            self.assertEqual((status, found), (200, []))
            status, denied = call("/me/listings")
            self.assertEqual(status, 401)
            self.assertEqual(denied["error"], "unauthorized")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
