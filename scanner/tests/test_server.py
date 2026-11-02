import json
import threading
import urllib.error
import urllib.request

import pytest

from hlh_scanner.manager import ScanManager, ScannerSettings
from hlh_scanner.nmap import ScanResult
from hlh_scanner.server import create_server
from hlh_scanner.targets import parse_approved_ranges


class FakeScanner:
    def scan(self, scan_type, target, ports=None, **kwargs):
        return ScanResult("completed", hosts=[{"ip": "192.168.1.20", "hostname": "nas.lan"}],
                          results=[{"ip": "192.168.1.20", "port": 443,
                                    "service_name": "https"}], hosts_up=1)


@pytest.fixture()
def scanner_server():
    settings = ScannerSettings(approved_ranges=parse_approved_ranges("192.168.1.0/24"))
    manager = ScanManager(settings, FakeScanner())
    server = create_server("127.0.0.1", 0, manager, "scanner-test-token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", manager
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(base, path, payload=None, token="scanner-test-token", method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Scanner-Token"] = token
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method=method or ("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_is_public_but_scan_endpoints_require_a_token(scanner_server):
    base, _ = scanner_server
    status, payload = request(base, "/health", token=None)
    assert status == 200 and payload["status"] == "ok"

    status, payload = request(base, "/api/scanner/scan", {"target": "192.168.1.20",
                                                           "scan_type": "discover"}, token=None)
    assert status == 401 and "token" in payload["error"]

    status, payload = request(base, "/api/scanner/scan/not-a-uuid", token=None)
    assert status == 401


def test_scan_start_and_status_round_trip(scanner_server):
    base, _ = scanner_server
    status, payload = request(base, "/api/scanner/scan", {
        "target": "192.168.1.20", "scan_type": "services", "ports": "443,80"})
    assert status == 202, payload
    scan = payload
    assert scan["scan_id"] and scan["status"] in ("running", "completed")
    assert scan["target"] == "192.168.1.20"

    for _ in range(100):
        status, polled = request(base, f"/api/scanner/scan/{scan['scan_id']}")
        assert status == 200
        if polled["status"] != "running":
            break
        threading.Event().wait(0.02)
    assert polled["status"] == "completed"
    assert polled["results"][0]["port"] == 443
    assert polled["completed_at"]


def test_invalid_target_and_unknown_scan_are_rejected_safely(scanner_server):
    base, _ = scanner_server
    status, payload = request(base, "/api/scanner/scan", {
        "target": "8.8.8.8", "scan_type": "discover"})
    assert status == 400 and "approved" in payload["error"]

    status, payload = request(base, "/api/scanner/scan", {
        "target": "192.168.1.20", "scan_type": "services", "ports": "80;rm"})
    assert status == 400

    status, payload = request(base, "/api/scanner/scan/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12)
    assert status == 404

    status, payload = request(base, "/api/scanner/scan/not-a-uuid")
    assert status == 400


def test_missing_server_token_disables_scan_api_but_health_still_works():
    settings = ScannerSettings(approved_ranges=parse_approved_ranges("192.168.1.0/24"))
    manager = ScanManager(settings, FakeScanner())
    server = create_server("127.0.0.1", 0, manager, "")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, payload = request(base, "/health", token=None)
        assert status == 200
        status, payload = request(base, "/api/scanner/scan", {
            "target": "192.168.1.20", "scan_type": "discover"}, token=None)
        assert status == 503 and "authentication" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
