"""Small JSON HTTP adapter; all permissions remain in the service layer."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .errors import MarketError, require
from .service import MarketService


def only(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def integer(value: str, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise MarketError("invalid_input", f"{name}必须是整数") from None


def body_value(body: dict, name: str, default=None):
    if name not in body:
        return default
    return body[name]


def dispatch(
    service: MarketService,
    method: str,
    path: str,
    query: dict[str, list[str]],
    body: dict,
    actor: dict | None,
    token: str | None,
) -> tuple[int, dict | list]:
    """Map documented JSON routes onto application service methods."""
    parts = [piece for piece in path.split("/") if piece]
    request_id = body.get("request_id", "")

    if method == "GET" and path == "/health":
        return 200, {"status": "ok"}
    if method == "POST" and path == "/auth/code":
        return 200, service.issue_code(body.get("email", ""))
    if method == "POST" and path == "/auth/register":
        result = service.register(
            body.get("email", ""), body.get("code", ""),
            body.get("password", ""), body.get("contact", ""),
        )
        if "error" in result:
            return 400, result
        return 201, result
    if method == "POST" and path == "/auth/login":
        result = service.login(body.get("email", ""), body.get("password", ""))
        if "error" in result:
            return 401, result
        return 200, result
    if method == "POST" and path == "/auth/logout":
        return 200, service.logout(actor, token or "")
    if method == "GET" and path == "/me":
        return 200, service.my_profile(actor)
    if method == "PUT" and path == "/me/contact":
        return 200, service.update_contact(actor, body.get("contact", ""), request_id)

    if method == "GET" and path == "/listings":
        return 200, service.public_listings(
            keyword=only(query, "keyword"),
            category=only(query, "category"),
            min_price=only(query, "min_price") or None,
            max_price=only(query, "max_price") or None,
            sort=only(query, "sort", "newest"),
            limit=integer(only(query, "limit", "50"), "limit"),
            offset=integer(only(query, "offset", "0"), "offset"),
        )
    if method == "POST" and path == "/listings":
        return 201, service.create_listing(actor, body.get("listing", {}), request_id)
    if method == "GET" and path == "/me/listings":
        return 200, service.my_listings(actor, only(query, "status") or None)
    if method == "GET" and path == "/admin/listings":
        return 200, service.admin_listings(actor, only(query, "status") or None)
    if len(parts) == 2 and parts[0] == "listings" and method == "GET":
        return 200, service.listing_detail(actor, parts[1])
    if len(parts) == 2 and parts[0] == "listings" and method == "PUT":
        return 200, service.edit_listing(
            actor, parts[1], body.get("changes", {}),
            body.get("expected_version"), request_id,
        )
    if len(parts) == 3 and parts[0] == "listings" and method == "POST":
        listing_id, operation = parts[1], parts[2]
        version = body.get("expected_version")
        if operation == "submit":
            return 200, service.submit_listing(actor, listing_id, version, request_id)
        if operation == "withdraw":
            return 200, service.withdraw_listing(actor, listing_id, version, request_id)
        if operation == "remove":
            return 200, service.remove_listing(actor, listing_id, version, request_id)
        if operation == "reserve":
            return 201, service.reserve(actor, listing_id, version, request_id)
        if operation == "reports":
            return 201, service.create_report(
                actor, listing_id, body.get("category", ""),
                body.get("description", ""), body.get("evidence", []), request_id,
            )
        if operation == "review":
            return 200, service.review_listing(
                actor, listing_id, body.get("approved"),
                body.get("reason", ""), version, request_id,
            )

    if method == "GET" and path == "/me/reservations":
        return 200, service.my_reservations(actor, only(query, "status") or None)
    if method == "GET" and path == "/seller/reservations":
        return 200, service.seller_reservations(actor, only(query, "status") or None)
    if len(parts) >= 2 and parts[0] == "reservations":
        reservation_id = parts[1]
        if len(parts) == 2 and method == "GET":
            return 200, service.reservation_detail(actor, reservation_id)
        if len(parts) == 3 and method == "GET" and parts[2] == "contact":
            return 200, service.other_contact(actor, reservation_id)
        if len(parts) == 3 and method == "POST":
            if parts[2] == "decide":
                return 200, service.decide_reservation(
                    actor, reservation_id, body.get("approved"),
                    body.get("reason", ""), body.get("details", ""), request_id,
                )
            if parts[2] == "cancel":
                return 200, service.cancel_reservation(
                    actor, reservation_id, body.get("reason", ""),
                    body.get("details", ""), request_id,
                )
            if parts[2] == "complete":
                return 200, service.complete_reservation(
                    actor, reservation_id, body.get("confirmed_receipt"), request_id,
                )

    if method == "GET" and path == "/me/reports":
        return 200, service.my_reports(actor)
    if method == "GET" and path == "/admin/reports":
        return 200, service.admin_reports(actor, only(query, "status") or None)
    if len(parts) == 2 and parts[0] == "reports" and method == "GET":
        return 200, service.report_detail(actor, parts[1])
    if len(parts) == 3 and parts[0] == "reports" and parts[2] == "decide":
        if method == "POST":
            return 200, service.decide_report(
                actor, parts[1], body.get("violation"),
                body.get("reason", ""), request_id,
            )

    if method == "GET" and path == "/notifications":
        return 200, service.notifications(
            actor, only(query, "unread") == "1"
        )
    if (
        len(parts) == 3 and parts[0] == "notifications"
        and parts[2] == "read" and method == "POST"
    ):
        return 200, service.mark_notification_read(actor, parts[1], request_id)
    if method == "GET" and path == "/statistics":
        return 200, service.monthly_statistics(actor, only(query, "month"))
    if method == "GET" and path == "/admin/audit":
        return 200, service.audit_search(
            actor,
            operation=only(query, "operation"),
            actor_id=only(query, "actor_id"),
            target_id=only(query, "target_id"),
            since=only(query, "since"),
            until=only(query, "until"),
            limit=integer(only(query, "limit", "100"), "limit"),
        )
    raise MarketError("not_found", "接口不存在", 404)


def make_handler(service: MarketService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CampusMarket/1.0"

        def do_GET(self):
            self.handle_json("GET")

        def do_POST(self):
            self.handle_json("POST")

        def do_PUT(self):
            self.handle_json("PUT")

        def handle_json(self, method: str) -> None:
            try:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, keep_blank_values=True)
                body = self.read_body() if method in ("POST", "PUT") else {}
                authorization = self.headers.get("Authorization", "")
                token = (
                    authorization[7:]
                    if authorization.startswith("Bearer ") else None
                )
                actor = service.authenticate(token)
                status, result = dispatch(
                    service, method, parsed.path, query, body, actor, token
                )
            except MarketError as error:
                status, result = error.status, error.as_dict()
            except (ValueError, TypeError) as error:
                status = 400
                result = {"error": "invalid_input", "message": str(error)}
            except Exception:
                self.log_exception()
                status = 500
                result = {"error": "internal_error", "message": "服务器内部错误"}
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def read_body(self) -> dict:
            length = integer(self.headers.get("Content-Length", "0"), "Content-Length")
            require(0 <= length <= 1_000_000, "body_too_large", "请求体过大", 413)
            if length == 0:
                return {}
            require(
                self.headers.get("Content-Type", "").startswith("application/json"),
                "unsupported_media_type", "请求体须为 JSON", 415,
            )
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            require(isinstance(value, dict), "invalid_input", "请求体须为 JSON 对象")
            return value

        def log_exception(self) -> None:
            import traceback

            traceback.print_exc()

    return Handler


def serve(service: MarketService, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(service))
    stopped = threading.Event()

    def scheduler() -> None:
        while not stopped.is_set():
            try:
                service.run_due_jobs()
            except Exception:
                import traceback

                traceback.print_exc()
            stopped.wait(60)

    worker = threading.Thread(target=scheduler, name="market-scheduler", daemon=True)
    worker.start()
    print(f"Campus Market API listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        worker.join(timeout=2)
