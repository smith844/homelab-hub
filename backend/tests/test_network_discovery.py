"""Web bridge, validation and reconciliation integration for network discovery."""
import pytest

from app.models import AppService, Hardware, VM, db
from app.services import network_discovery

SCAN_ID = "12345678-1234-1234-1234-123456789abc"
HEADERS = {"X-Admin-Token": "network-test-token"}


@pytest.fixture()
def inventory(app):
    betty = Hardware(name="Betty", ip_address="192.168.1.10", hostname="betty.lan")
    db.session.add(betty)
    db.session.flush()
    docker = VM(name="Docker", hardware_id=betty.id, ip_address="192.168.1.10")
    db.session.add(docker)
    db.session.flush()
    app_service = AppService(name="Admin UI", vm_id=docker.id,
                             ip_address="192.168.1.20", port=443)
    other = AppService(name="Router", hardware_id=betty.id, ip_address="192.168.1.1")
    db.session.add_all([app_service, other])
    db.session.commit()
    app.config.update(
        ADMIN_TOKEN="network-test-token",
        SCANNER_URL="http://127.0.0.1:8791",
        SCANNER_TOKEN="scanner-token",
        SCANNER_APPROVED_RANGES="192.168.1.0/24",
        SCANNER_DEFAULT_PORTS="22,80,443",
        SCANNER_MAX_HOSTS="256",
        SCANNER_MAX_PORTS="256",
    )
    return {"host": betty, "app": app_service, "other": other}


def scan_payload(status="completed", **changes):
    data = {
        "scan_id": SCAN_ID,
        "type": "portscan",
        "scan_type": "services",
        "status": status,
        "progress": 100,
        "target": "192.168.1.0/24",
        "params": {"target": "192.168.1.0/24", "ports": "443"},
        "started_at": "2026-11-02T18:00:00Z",
        "completed_at": "2026-11-02T18:00:05Z",
        "hosts_up": 1,
        "hosts_down": 254,
        "hosts": [{"ip": "192.168.1.20", "hostname": "admin.lan",
                   "mac": "AA:BB:CC:DD:EE:FF", "vendor": "Acme", "open_ports": 1}],
        "results": [{"ip": "192.168.1.20", "hostname": "admin.lan",
                     "mac": "AA:BB:CC:DD:EE:FF", "vendor": "Acme",
                     "port": 443, "protocol": "tcp", "state": "open",
                     "service_name": "https", "service_version": ""}],
        "warnings": [],
        "error": None,
        "complete": status == "completed",
    }
    data.update(changes)
    return data


def test_config_exposes_only_approved_ranges_and_bounds(inventory, client):
    response = client.get("/api/network-discovery/config")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["configured"] is True
    assert payload["approved_ranges"] == ["192.168.1.0/24"]
    assert payload["default_ports"] == "22,80,443"
    assert payload["max_hosts"] == 256
    assert payload["max_ports"] == 256
    assert [item["value"] for item in payload["scan_types"]] == ["discover", "services"]
    assert "token" not in str(payload).lower()


def test_target_validation_matches_approved_private_ranges(inventory, app):
    with app.app_context():
        assert network_discovery.validate_scan_request("192.168.1.20", "discover") == ("192.168.1.20", None)
        assert network_discovery.validate_scan_request(
            "192.168.1.0/24", "services", "443,80,80") == ("192.168.1.0/24", "80,443")
        for target in ("192.168.2.20", "8.8.8.8", "192.168.1.0/23", "not-an-ip"):
            with pytest.raises(network_discovery.NetworkDiscoveryError):
                network_discovery.validate_scan_request(target, "discover")
        with pytest.raises(network_discovery.NetworkDiscoveryError):
            network_discovery.validate_scan_request("192.168.1.20", "services", "80;rm -rf /")
        with pytest.raises(network_discovery.NetworkDiscoveryError):
            network_discovery.validate_scan_request("192.168.1.20", "unknown")


def test_scan_start_requires_admin_and_forwards_only_validated_values(inventory, client, app, monkeypatch):
    assert client.post("/api/network-discovery/scan", json={
        "target": "192.168.1.0/24", "scan_type": "discover"}, headers={}).status_code == 401
    app.config["ADMIN_TOKEN"] = ""
    assert client.post("/api/network-discovery/scan", json={
        "target": "192.168.1.0/24", "scan_type": "discover"}, headers=HEADERS).status_code == 503
    app.config["ADMIN_TOKEN"] = "network-test-token"

    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return scan_payload()

    monkeypatch.setattr(network_discovery, "_request", fake_request)
    response = client.post("/api/network-discovery/scan", headers=HEADERS, json={
        "target": "192.168.1.99/24", "scan_type": "services", "ports": "443,80,80"})
    assert response.status_code == 202
    assert response.get_json()["scan"]["scan_id"] == SCAN_ID
    assert calls == [("POST", "/api/scanner/scan", {
        "target": "192.168.1.0/24", "scan_type": "services", "ports": "80,443"})]


def test_scan_start_rejects_unapproved_target_without_contacting_scanner(inventory, client, monkeypatch):
    def fail_request(*args, **kwargs):
        raise AssertionError("scanner must not be contacted")

    monkeypatch.setattr(network_discovery, "_request", fail_request)
    response = client.post("/api/network-discovery/scan", headers=HEADERS, json={
        "target": "10.0.0.0/8", "scan_type": "discover"})
    assert response.status_code == 400
    assert "approved" in response.get_json()["error"]


def test_scanner_unavailable_and_busy_are_reported_without_false_success(inventory, client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise network_discovery.NetworkDiscoveryUnavailable("scanner unreachable")

    monkeypatch.setattr(network_discovery, "_request", unavailable)
    response = client.post("/api/network-discovery/scan", headers=HEADERS, json={
        "target": "192.168.1.20", "scan_type": "discover"})
    assert response.status_code == 503
    assert "unreachable" in response.get_json()["error"]

    def busy(*args, **kwargs):
        raise network_discovery.NetworkDiscoveryBusy("scanner busy")

    monkeypatch.setattr(network_discovery, "_request", busy)
    response = client.post("/api/network-discovery/scan", headers=HEADERS, json={
        "target": "192.168.1.20", "scan_type": "discover"})
    assert response.status_code == 429


def test_scan_status_proxy_validates_ids_and_sanitises_scanner_output(inventory, client, app, monkeypatch):
    assert client.get("/api/network-discovery/scan/not-a-uuid").status_code == 400

    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path))
        return scan_payload()

    monkeypatch.setattr(network_discovery, "_request", fake_request)
    response = client.get(f"/api/network-discovery/scan/{SCAN_ID}")
    assert response.status_code == 200
    scan = response.get_json()["scan"]
    assert scan["status"] == "completed" and scan["result_count"] == 1
    assert scan["results"][0]["port"] == 443
    assert calls == [("GET", f"/api/scanner/scan/{SCAN_ID}")]

    def malformed(method, path, payload=None):
        return {"scan_id": SCAN_ID, "status": "something-else", "type": "portscan", "results": []}

    monkeypatch.setattr(network_discovery, "_request", malformed)
    assert client.get(f"/api/network-discovery/scan/{SCAN_ID}").status_code == 400


def test_network_scan_results_compare_with_inventory_without_mutation(inventory, client):
    before = [(app.id, app.name, app.ip_address, app.port)
              for app in AppService.query.order_by(AppService.id)]
    response = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": {"data": scan_payload()}})
    assert response.status_code == 200, response.get_json()
    report = response.get_json()
    assert report["network"]["status"] == "completed"
    row = report["network"]["rows"][0]
    assert row["classification"] == "matched"
    assert row["matches"][0]["id"] == inventory["app"].id
    assert report["scan"]["authoritative"] is False
    assert [(app.id, app.name, app.ip_address, app.port)
            for app in AppService.query.order_by(AppService.id)] == before


def test_partial_network_scan_is_uncertain_and_cannot_imply_absence(inventory, client):
    report = client.post("/api/reconciliation/compare", json={
        "host_key": "betty", "snapshot": {"data": scan_payload("partial", complete=False,
                                                               error="timeout")}}).get_json()
    assert report["network"]["status"] == "partial"
    assert report["network"]["rows"][0]["classification"] == "unverified"
    assert not any(row["classification"] == "confirmed_absent" for row in report["inventory"])


def test_missing_scanner_configuration_disables_start(inventory, client, app):
    app.config["SCANNER_URL"] = ""
    response = client.post("/api/network-discovery/scan", headers=HEADERS, json={
        "target": "192.168.1.20", "scan_type": "discover"})
    assert response.status_code == 503
    assert "not configured" in response.get_json()["error"]
