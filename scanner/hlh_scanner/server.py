"""Small token-authenticated HTTP service around the restricted Nmap scanner."""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .manager import ScanBusy, ScanManager, ScannerSettings
from .targets import TargetError

logger = logging.getLogger("hlh_scanner")
MAX_BODY = 64 * 1024


class ScannerHandler(BaseHTTPRequestHandler):
    server_version = "HLHNetworkScanner/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        # Never log request headers (the token) or response bodies.
        logger.info("%s %s", self.command, urlparse(self.path).path)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = self.server.scanner_token
        if not expected:
            self._send(503, {"error": "Scanner authentication is not configured"})
            return False
        provided = self.headers.get("X-Scanner-Token", "")
        if not provided or not hmac.compare_digest(provided, expected):
            self._send(401, {"error": "A valid scanner token is required"})
            return False
        return True

    def do_GET(self):  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        if path == "/health":
            manager = self.server.scanner_manager
            self._send(200, {
                "status": "ok",
                "service": "hlh-network-scanner",
                "scans_running": manager.active_count(),
                "approved_targets_configured": bool(manager.settings.approved_ranges),
            })
            return
        prefix = "/api/scanner/scan/"
        if path.startswith(prefix):
            if not self._authorized():
                return
            scan_id = path[len(prefix):]
            try:
                uuid.UUID(scan_id)
            except (ValueError, TypeError):
                self._send(400, {"error": "Invalid scan id"})
                return
            scan = self.server.scanner_manager.get(scan_id)
            if scan is None:
                self._send(404, {"error": "Scan not found or expired"})
            else:
                self._send(200, scan)
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802 - stdlib signature
        if urlparse(self.path).path != "/api/scanner/scan":
            self._send(404, {"error": "Not found"})
            return
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "Invalid Content-Length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._send(413 if length > MAX_BODY else 400,
                       {"error": "A small JSON request body is required"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "Invalid JSON body"})
            return
        if not isinstance(data, dict):
            self._send(400, {"error": "JSON object required"})
            return
        try:
            scan = self.server.scanner_manager.start(
                data.get("scan_type"),
                data.get("target"),
                data.get("ports"),
            )
        except TargetError as exc:
            self._send(400, {"error": str(exc)})
        except ScanBusy as exc:
            self._send(429, {"error": str(exc)})
        except Exception:  # noqa: BLE001 - do not leak internals
            logger.exception("Unexpected scanner failure")
            self._send(500, {"error": "Scanner failed to start the job"})
        else:
            self._send(202, scan)


class ScannerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, manager: ScanManager, token: str):
        super().__init__(address, handler)
        self.scanner_manager = manager
        self.scanner_token = token


def create_server(bind: str, port: int, manager: ScanManager, token: str) -> ScannerHTTPServer:
    return ScannerHTTPServer((bind, port), ScannerHandler, manager, token)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="HomeLab-Hub restricted network scanner")
    parser.add_argument("--bind", default=os.environ.get("HLH_SCANNER_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HLH_SCANNER_PORT", "8791")))
    args = parser.parse_args()
    try:
        settings = ScannerSettings.from_env()
    except (ValueError, TargetError) as exc:
        raise SystemExit(f"Invalid scanner configuration: {exc}")
    token = (os.environ.get("HLH_SCANNER_TOKEN") or "").strip()
    if not token:
        raise SystemExit("HLH_SCANNER_TOKEN is required; refusing to run an unauthenticated scanner")
    if not settings.approved_ranges:
        logger.warning("No approved ranges configured; scans will be rejected until configured")
    manager = ScanManager(settings)
    server = create_server(args.bind, args.port, manager, token)
    logger.info("Scanner listening on http://%s:%s (approved ranges: %s)",
                args.bind, args.port,
                ", ".join(str(item) for item in settings.approved_ranges) or "none")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Scanner stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
