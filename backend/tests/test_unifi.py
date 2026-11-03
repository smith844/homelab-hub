"""Read-only UniFi adapter, normalization, pagination and cache tests."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest

from app.services import unifi


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self, limit=-1):
        return self._body[:limit] if limit >= 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def client_for(pages, app, **settings):
    app.config.update({
        "UNIFI_URL": "https://unifi.test",
        "UNIFI_API_KEY": "test-api-key-not-secret",
        "UNIFI_SITE": "",
        "UNIFI_TIMEOUT": "5",
        "UNIFI_MAX_PAGES": "5",
        "UNIFI_MAX_OBSERVATIONS": "5000",
    })
    app.config.update(settings)
    calls = []

    def opener(request, timeout=None, context=None):
        calls.append(request)
        assert request.get_method() == "GET"
        assert request.get_header("X-api-key") == "test-api-key-not-secret"
        parsed = urllib.parse.urlparse(request.full_url)
        params = urllib.parse.parse_qs(parsed.query)
        key = (parsed.path, params.get("offset", ["0"])[0])
        if key not in pages:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, io.BytesIO(b"{}"))
        value = pages[key]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, bytes):
            class Raw(FakeResponse):
                def __init__(self):
                    self._body = value
            return Raw()
        return FakeResponse(value)

    return unifi.UnifiClient(opener=opener), calls


def device(device_id="dev-1", name="USW Lite", mac="aa:bb:cc:dd:ee:ff",
           ip="192.168.1.2", state="ONLINE", features=None, **extra):
    row = {"id": device_id, "name": name, "macAddress": mac, "ipAddress": ip,
           "state": state, "features": features or ["switching"], "model": "USWL16",
           "interfaces": ["ports"]}
    row.update(extra)
    return row


def client(client_id="client-1", name="Laptop", mac="11:22:33:44:55:66",
           ip="192.168.1.30", kind="WIRELESS", **extra):
    row = {"id": client_id, "name": name, "macAddress": mac, "ipAddress": ip,
           "type": kind, "connectedAt": "2026-11-03T09:00:00Z",
           "access": {"type": "DEFAULT"}}
    row.update(extra)
    return row


def test_official_api_url_auth_and_normalization(app):
    pages = {
        ("/proxy/network/integration/v1/info", "0"): {"applicationVersion": "9.1.120"},
        ("/proxy/network/integration/v1/sites", "0"): {
            "data": [{"id": "site-1", "internalReference": "default", "name": "Default"}],
            "offset": 0, "limit": 25, "count": 1, "totalCount": 1},
        ("/proxy/network/integration/v1/sites/site-1/devices", "0"): {
            "data": [device()], "offset": 0, "limit": 200, "count": 1, "totalCount": 1},
        ("/proxy/network/integration/v1/sites/site-1/clients", "0"): {
            "data": [client(lastSeen="2026-11-03T09:59:00Z")],
            "offset": 0, "limit": 200, "count": 1, "totalCount": 1},
    }
    api, calls = client_for(pages, app)
    result = api.info()
    site = api.select_site(api.sites()["sites"])
    devices, _ = api.devices(site["id"])
    clients, _ = api.clients(site["id"])
    assert result["application_version"] == "9.1.120"
    assert site["name"] == "Default"
    assert all(call.get_method() == "GET" for call in calls)
    assert len(calls) == 4

    normalized_device, warning = unifi._normalise_device(devices[0], site, "2026-11-03T10:00:00Z")
    assert warning is None
    assert normalized_device["mac"] == "aa:bb:cc:dd:ee:ff"
    assert normalized_device["ip"] == "192.168.1.2"
    assert normalized_device["device_type"] == "switch"
    assert normalized_device["online"] is True
    normalized_client, warning = unifi._normalise_client(clients[0], site, "2026-11-03T10:00:00Z")
    assert warning is None
    assert normalized_client["mac"] == "11:22:33:44:55:66"
    assert normalized_client["device_type"] == "wireless"
    assert normalized_client["last_seen"] == "2026-11-03T09:59:00Z"
    assert normalized_client["online"] is True
    assert normalized_client["ips"] == ["192.168.1.30"]


def test_multiple_ips_are_preserved_for_identity_matching(app):
    api, _ = client_for({}, app)
    site = {"id": "site-1", "name": "Default"}
    row, warning = unifi._normalise_client(
        client(ip="192.168.1.30", ipAddresses=["192.168.1.31", "192.168.1.30"]),
        site, "2026-11-03T10:00:00Z")
    assert warning is None
    assert row["ip"] == "192.168.1.30"
    assert row["ips"] == ["192.168.1.30", "192.168.1.31"]


def test_unifi_fetch_uses_pagination_and_optional_fields(app):
    def page(rows, offset, total):
        return {"data": rows, "offset": offset, "limit": 200, "count": len(rows),
                "totalCount": total}

    first = [device(device_id=f"d-{index}", mac=f"aa:bb:cc:dd:ee:{index:02x}")
             for index in range(200)]
    second = [device(device_id="d-200", mac="aa:bb:cc:dd:ee:ff")]
    pages = {
        ("/proxy/network/integration/v1/info", "0"): {"applicationVersion": "9.1.120"},
        ("/proxy/network/integration/v1/sites", "0"): {
            "data": [{"id": "site-1", "internalReference": "default", "name": "Default"}],
            "totalCount": 1, "data": [{"id": "site-1", "internalReference": "default", "name": "Default"}]},
        ("/proxy/network/integration/v1/sites/site-1/devices", "0"): page(first, 0, 201),
        ("/proxy/network/integration/v1/sites/site-1/devices", "200"): page(second, 200, 201),
        ("/proxy/network/integration/v1/sites/site-1/clients", "0"): page([], 0, 0),
    }
    api, calls = client_for(pages, app)
    site = api.select_site(api.sites()["sites"])
    rows, meta = api.devices(site["id"])
    assert len(rows) == 201 and meta["pages"] == 2
    assert len(calls) == 3


def test_auth_failure_timeout_and_malformed_responses(app):
    pages = {
        ("/proxy/network/integration/v1/info", "0"):
            urllib.error.HTTPError("https://unifi.test", 401, "unauthorized", {}, io.BytesIO(b"{}")),
    }
    api, _ = client_for(pages, app)
    with pytest.raises(unifi.UnifiAuthError):
        api.info()

    pages[("/proxy/network/integration/v1/info", "0")] = urllib.error.URLError("timed out")
    api, _ = client_for(pages, app, UNIFI_TIMEOUT="2")
    with pytest.raises(unifi.UnifiUnavailable):
        api.info()

    pages[("/proxy/network/integration/v1/info", "0")] = b"{not json"
    api, _ = client_for(pages, app)
    with pytest.raises(unifi.UnifiResponseError):
        api.info()

    pages[("/proxy/network/integration/v1/info", "0")] = {"data": []}
    api, _ = client_for(pages, app)
    with pytest.raises(unifi.UnifiResponseError):
        api.sites()


def test_client_detail_optional_network_offline_and_vendor(app):
    api, _ = client_for({}, app)
    site = {"id": "site-1", "name": "Default"}
    offline, warning = unifi._normalise_client(
        client(online=False, networkName="IoT", vlan=20, manufacturer="Acme",
               lastSeen="2026-11-02T00:00:00Z"), site, "2026-11-03T10:00:00Z")
    assert warning is None
    assert offline["online"] is False
    assert offline["network"] == {"name": "IoT", "vlan_id": 20}
    assert offline["vendor"] == "Acme"
    assert offline["last_seen"] == "2026-11-02T00:00:00Z"


def test_configured_site_can_be_selected_by_name_and_missing_site_is_rejected(app):
    api, _ = client_for({}, app, UNIFI_SITE="Default")
    assert api.select_site([{"id": "site-1", "internal_reference": "default",
                             "name": "Default"}])["id"] == "site-1"
    missing, _ = client_for({}, app, UNIFI_SITE="Other")
    with pytest.raises(unifi.UnifiResponseError):
        missing.select_site([{"id": "site-1", "internal_reference": "default",
                              "name": "Default"}])


def test_missing_identity_fields_are_skipped_not_invented():
    site = {"id": "site-1", "name": "Default"}
    assert unifi._normalise_device({}, site, "2026-11-03T10:00:00Z")[0] is None
    assert unifi._normalise_client({}, site, "2026-11-03T10:00:00Z")[0] is None
    assert unifi._normalise_client({"name": "only-a-name"}, site,
                                   "2026-11-03T10:00:00Z")[0]["name"] == "only-a-name"


def test_store_keeps_previous_cache_on_failure_and_never_exposes_key(app, monkeypatch):
    app.config.update({"UNIFI_URL": "https://unifi.test", "UNIFI_API_KEY": "test-api-key-not-secret"})
    store = unifi.UnifiStore()
    assert store.status()["configured"] is True
    monkeypatch.setattr(unifi, "fetch_observations", lambda: {
        "observations": [{"source": "unifi", "kind": "client", "id": "c1",
                          "name": "Phone", "hostname": "", "mac": "aa:bb:cc:dd:ee:ff",
                          "ip": "192.168.1.40", "online": True, "last_seen": None,
                          "network": None, "device_type": "wireless", "state": "ONLINE",
                          "connected_at": None, "vendor": "", "model": "",
                          "uplink_device_id": None, "observed_at": "2026-11-03T10:00:00Z"}],
        "version": "9.1.120", "site": {"id": "site-1", "name": "Default"},
        "pagination": {}, "warnings": [], "observed_at": "2026-11-03T10:00:00Z",
    })
    status = store.refresh()
    assert status["clients"] == 1 and status["last_success"]
    assert "test-api-key" not in json.dumps(status)

    def fail():
        raise unifi.UnifiUnavailable("controller unreachable")

    monkeypatch.setattr(unifi, "fetch_observations", fail)
    with pytest.raises(unifi.UnifiUnavailable):
        store.refresh()
    stopped = store.status()
    assert stopped["clients"] == 1 and stopped["has_data"] is True
    assert stopped["error"] == "controller unreachable"
    assert store.observations()[0]["name"] == "Phone"


def test_unconfigured_and_invalid_controller_url_are_rejected(app):
    app.config["UNIFI_URL"] = ""
    assert unifi.configured() is False
    with pytest.raises(unifi.UnifiUnavailable):
        unifi.fetch_observations()
    app.config["UNIFI_URL"] = "http://unifi.test"
    app.config["UNIFI_API_KEY"] = "key"
    with pytest.raises(unifi.UnifiUnavailable):
        unifi.UnifiClient()
