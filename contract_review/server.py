import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from contract_review.auth import AuthResolver
from contract_review.scheduler import ReminderScheduler
from contract_review.service import AppService, RequestContext

logger = logging.getLogger(__name__)

MAX_REQUEST_BODY = 10 * 1024 * 1024  # 10 MB

service = AppService(storage_root=os.environ.get("CONTRACT_REVIEW_STORAGE", "storage"))
auth_resolver = AuthResolver()
scheduler = ReminderScheduler(service)
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


class ApiHandler(BaseHTTPRequestHandler):
    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        if length > MAX_REQUEST_BODY:
            raise ValueError(f"Request body too large (max {MAX_REQUEST_BODY} bytes)")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _ctx(self) -> RequestContext:
        ident = auth_resolver.resolve(self.headers)
        return RequestContext(user=ident.user, roles=ident.roles)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def _send(self, status: int, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path, content_type: str):
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _check_csrf(self) -> bool:
        """Validate Origin header for state-changing requests."""
        origin = self.headers.get("Origin", "")
        if not origin:
            return True  # non-browser clients (curl, etc.) don't send Origin
        parsed_origin = urlparse(origin)
        host_header = self.headers.get("Host", "")
        if parsed_origin.netloc == host_header:
            return True
        logger.warning("CSRF check failed: Origin=%s Host=%s", origin, host_header)
        return False

    def _handle(self, fn):
        try:
            payload = fn()
            self._send(HTTPStatus.OK, payload)
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except PermissionError as exc:
            self._send(HTTPStatus.FORBIDDEN, {"error": str(exc)})
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:  # noqa: BLE001
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send_file(WEB_ROOT / "app.js", "text/javascript; charset=utf-8")
        if path == "/styles.css":
            return self._send_file(WEB_ROOT / "styles.css", "text/css; charset=utf-8")

        def run():
            if path == "/api/workflows":
                return service.list_workflows()
            if path.startswith("/api/workflows/"):
                workflow_id = int(path.split("/")[3])
                return service.get_workflow(workflow_id)
            if path == "/api/dashboard/summary":
                return service.dashboard_summary()
            if path == "/api/dashboard/aging":
                return service.dashboard_aging()
            if path == "/api/dashboard/pending":
                return service.dashboard_pending()
            if path == "/api/dashboard/correction-queue":
                return service.correction_queue()
            if path == "/api/admin/settings":
                return service.get_settings()
            if path == "/api/admin/roles":
                return service.list_roles()
            if path == "/api/admin/user-roles":
                user = query.get("user", [None])[0]
                return service.get_user_roles(user)
            if path == "/api/notifications":
                workflow_id = query.get("workflowId", [None])[0]
                return service.get_notifications(int(workflow_id)) if workflow_id else service.get_notifications()
            raise KeyError("Route not found")

        self._handle(run)

    def do_POST(self):  # noqa: N802
        if not self._check_csrf():
            return self._send(HTTPStatus.FORBIDDEN, {"error": "Origin not allowed"})
        path = urlparse(self.path).path

        def run():
            data = self._read_json()
            ctx = self._ctx()
            if path == "/api/workflows":
                return service.create_workflow(data, ctx)
            if path.startswith("/api/workflows/") and path.endswith("/documents"):
                workflow_id = int(path.split("/")[3])
                return service.add_document(workflow_id, data, ctx)
            if path.startswith("/api/approvals/") and path.endswith("/decide"):
                step_id = int(path.split("/")[3])
                return service.decide_step(step_id, data, ctx)
            if path == "/api/admin/roles":
                return service.create_role(data, ctx)
            if path == "/api/system/run-reminders":
                return service.run_aging_reminders(ctx)
            raise KeyError("Route not found")

        self._handle(run)

    def do_PUT(self):  # noqa: N802
        if not self._check_csrf():
            return self._send(HTTPStatus.FORBIDDEN, {"error": "Origin not allowed"})
        path = urlparse(self.path).path

        def run():
            data = self._read_json()
            ctx = self._ctx()
            if path.startswith("/api/workflows/") and path.endswith("/status"):
                workflow_id = int(path.split("/")[3])
                return service.update_status(workflow_id, data["status"], data.get("reason", ""), ctx)
            if path.startswith("/api/workflows/") and path.endswith("/hold"):
                workflow_id = int(path.split("/")[3])
                return service.set_hold(workflow_id, bool(data["isHold"]), data.get("reason", ""), ctx)
            if path == "/api/admin/settings":
                return service.update_settings(data, ctx)
            if path == "/api/admin/user-roles":
                return service.update_user_roles(data, ctx)
            raise KeyError("Route not found")

        self._handle(run)


def run_server(port: int = 8000):
    server = ThreadingHTTPServer(("0.0.0.0", port), ApiHandler)
    scheduler.start()
    print(f"Contract Review API listening on {port}")
    try:
        server.serve_forever()
    finally:
        scheduler.stop()


if __name__ == "__main__":
    run_server(int(os.environ.get("PORT", "8000")))
