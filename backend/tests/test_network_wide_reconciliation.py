"""Network-wide read-only matching: evidence, relationships and safety."""
import pytest

from app.models import AppService, Hardware, Misc, Network, NetworkMember, VM, db
from app.services.network_wide_reconciliation import (
    NetworkWideError,
    compare_network_wide,
    reconcile_observations,
)


@pytest.fixture()
def inventory(app):
    betty = Hardware(name="Betty", hostname="betty.lan", ip_address="192.168.1.80",
                     mac_address="AA:BB:CC:DD:EE:01")
    blackbox = Hardware(name="Blackbox", hostname="blackbox.lan", ip_address="192.168.1.50",
                        mac_address="AA:BB:CC:DD:EE:02")
    pihole = Hardware(name="PiHole Main", hostname="pi.hole", ip_address="192.168.1.16",
                      mac_address="AA:BB:CC:DD:EE:03")
    backup = Hardware(name="PiHole Backup", hostname="pi.hole.backup", ip_address="192.168.1.18")
    vip_a = Misc(name="Pi-hole Keepalived VIP", hostname="pihole-vip", ip_address="192.168.1.19")
    vip_b = Misc(name="Shared Pi-hole VIP record", ip_address="192.168.1.19")
    camera = Misc(name="Front Door Camera")
    db.session.add_all([betty, blackbox, pihole, backup, vip_a, vip_b, camera])
    db.session.flush()
    docker = VM(name="Docker", hardware_id=betty.id, hostname="docker.lan",
                ip_address="192.168.1.80", mac_address="AA:BB:CC:DD:EE:04")
    db.session.add(docker)
    db.session.flush()
    lan = Network(name="LAN", vlan_id=1, subnet="192.168.1.0/24", gateway="192.168.1.1")
    db.session.add(lan)
    db.session.flush()
    db.session.add(NetworkMember(network_id=lan.id, member_type="misc",
                                 member_id=camera.id, ip_on_network="192.168.1.61"))
    db.session.add_all([
        AppService(name="Traefik", vm_id=docker.id, external_hostname="traefik.smitharend.com",
                   port=443),
        AppService(name="Plex", vm_id=docker.id, port=32400),
        AppService(name="Pi-hole Admin", hardware_id=pihole.id, port=80),
        AppService(name="Portainer", ip_address="192.168.1.200", port=9443),
        AppService(name="NAS UI", ip_address="192.168.1.70", port=443),
    ])
    db.session.commit()
    app.config["ADMIN_TOKEN"] = "network-test-token"
    return {"betty": betty, "blackbox": blackbox, "pihole": pihole, "backup": backup,
            "vip_a": vip_a, "vip_b": vip_b, "camera": camera, "docker": docker,
            "lan": lan}


def host(ip, hostname="", mac=""):
    return {"ip": ip, "hostname": hostname, "mac": mac, "vendor": "", "os": "",
            "open_ports": 0}


def service(ip, port, hostname="", service_name="", mac=""):
    return {"ip": ip, "port": port, "hostname": hostname, "mac": mac,
            "vendor": "", "os": "", "service_name": service_name,
            "service_version": ""}


def scan(hosts=None, services=None, status="completed", **changes):
    hosts = hosts or []
    services = services or []
    data = {
        "type": "portscan" if services else "discover",
        "status": status,
        "complete": status == "completed",
        "target": "192.168.1.0/24",
        "completed_at": "2026-11-02T18:00:00Z",
        "hosts": hosts,
        "results": services if services else hosts,
        "warnings": [],
        "params": {"target": "192.168.1.0/24"},
    }
    data.update(changes)
    return data


def host_row(result, ip):
    return next(row for row in result["hosts"] if row["ip"] == ip)


def service_row(result, ip, port):
    return next(row for row in result["services"] if row["ip"] == ip and row["port"] == port)


def test_matches_hardware_across_different_root_hosts(inventory):
    result = compare_network_wide(scan(hosts=[
        host("192.168.1.50", "blackbox.lan"),
        host("192.168.1.16", "pi.hole"),
        host("192.168.1.61"),
    ]))
    assert host_row(result, "192.168.1.50")["classification"] == "matched"
    assert host_row(result, "192.168.1.50")["candidates"][0]["id"] == inventory["blackbox"].id
    assert host_row(result, "192.168.1.16")["candidates"][0]["id"] == inventory["pihole"].id
    assert host_row(result, "192.168.1.61")["classification"] == "matched"
    assert host_row(result, "192.168.1.61")["candidates"][0]["id"] == inventory["camera"].id
    assert "network membership" in host_row(result, "192.168.1.61")["evidence"][0]


def test_host_and_runtime_sharing_ip_are_shared_not_duplicate(inventory):
    result = compare_network_wide(scan(hosts=[host("192.168.1.80", "traefik.smitharend.com")]))
    row = host_row(result, "192.168.1.80")
    assert row["classification"] == "shared"
    assert {candidate["id"] for candidate in row["candidates"]} == {
        inventory["betty"].id, inventory["docker"].id}
    assert "not duplicate physical devices" in row["reason"]
    assert any(candidate["name"] == "Traefik" for candidate in row["service_candidates"])


def test_explicit_and_inherited_service_endpoints_are_resolved_separately(inventory):
    result = compare_network_wide(scan(
        hosts=[host("192.168.1.16", "pi.hole"), host("192.168.1.80"),
               host("192.168.1.200")],
        services=[service("192.168.1.16", 80, service_name="http"),
                  service("192.168.1.80", 443, service_name="https"),
                  service("192.168.1.80", 32400, service_name="pp"),
                  service("192.168.1.200", 9443, service_name="https")],
    ))
    assert host_row(result, "192.168.1.16")["classification"] == "matched"
    assert host_row(result, "192.168.1.80")["classification"] == "shared"
    assert host_row(result, "192.168.1.200")["classification"] == "plausible"
    assert service_row(result, "192.168.1.16", 80)["classification"] == "plausible"
    assert service_row(result, "192.168.1.80", 443)["classification"] == "plausible"
    assert service_row(result, "192.168.1.80", 32400)["classification"] == "plausible"
    assert service_row(result, "192.168.1.200", 9443)["classification"] == "matched"
    assert service_row(result, "192.168.1.200", 9443)["candidates"][0]["name"] == "Portainer"


def test_multiple_devices_sharing_a_virtual_ip_are_ambiguous(inventory):
    result = compare_network_wide(scan(hosts=[host("192.168.1.19")]))
    row = host_row(result, "192.168.1.19")
    assert row["classification"] == "ambiguous"
    assert {candidate["name"] for candidate in row["candidates"]} >= {
        "Pi-hole Keepalived VIP", "Shared Pi-hole VIP record"}
    assert "virtual IP" in row["reason"]

    # Resolved DNS may point to one member of the virtual IP; it must not turn
    # the shared address into a confident physical-device match.
    result = compare_network_wide(scan(hosts=[host("192.168.1.19", "pi.hole")]))
    row = host_row(result, "192.168.1.19")
    assert row["classification"] == "ambiguous"
    assert "virtual IP" in row["reason"]
    assert {candidate["name"] for candidate in row["candidates"]} >= {
        "Pi-hole Keepalived VIP", "PiHole Main"}


def test_hostname_only_match_is_plausible_and_stale_dns_is_explained(inventory):
    result = compare_network_wide(scan(hosts=[host("192.168.1.123", "pi.hole")]))
    row = host_row(result, "192.168.1.123")
    assert row["classification"] == "plausible"
    assert row["candidates"][0]["name"] == "PiHole Main"
    assert "DNS may be stale" in row["reason"]


def test_conflicting_ip_and_hostname_evidence_is_ambiguous(inventory):
    result = compare_network_wide(scan(hosts=[
        host("192.168.1.16", "pi.hole.backup")]))
    # .16 matches PiHole Main by IP, while the hostname is unique to Backup.
    row = host_row(result, "192.168.1.16")
    assert row["classification"] == "ambiguous"
    assert {candidate["name"] for candidate in row["candidates"]} == {
        "PiHole Main", "PiHole Backup"}


def test_mac_address_can_match_a_device_at_a_different_ip(inventory):
    result = compare_network_wide(scan(hosts=[
        host("192.168.1.99", "new-name", "AA-BB-CC-DD-EE-02")]))
    row = host_row(result, "192.168.1.99")
    assert row["classification"] == "matched"
    assert row["candidates"][0]["id"] == inventory["blackbox"].id
    assert "MAC address" in row["evidence"]


def test_app_only_address_is_plausible_service_evidence(inventory):
    result = compare_network_wide(scan(hosts=[host("192.168.1.70")]))
    row = host_row(result, "192.168.1.70")
    assert row["classification"] == "plausible"
    assert row["candidates"][0]["name"] == "NAS UI"
    assert row["service_candidates"] == []
    assert "no physical device record" in row["reason"]


def test_hostname_case_and_trailing_dot_are_normalized(inventory):
    result = compare_network_wide(scan(hosts=[host("192.168.1.16", "PI.HOLE.")]))
    row = host_row(result, "192.168.1.16")
    assert row["classification"] == "matched"
    assert row["candidates"][0]["name"] == "PiHole Main"


def test_duplicate_application_endpoint_is_ambiguous(inventory):
    inventory["pihole"].apps.append(AppService(name="Pi-hole Duplicate", port=80))
    db.session.commit()
    result = compare_network_wide(scan(services=[service("192.168.1.16", 80)]))
    row = service_row(result, "192.168.1.16", 80)
    assert row["classification"] == "ambiguous"
    assert {candidate["name"] for candidate in row["candidates"]} == {
        "Pi-hole Admin", "Pi-hole Duplicate"}


def test_partial_scan_marks_every_observation_unverified_without_absence(inventory):
    before = (Hardware.query.count(), VM.query.count(), AppService.query.count())
    result = compare_network_wide(scan(
        hosts=[host("192.168.1.50", "blackbox.lan"), host("192.168.1.16", "pi.hole")],
        status="partial"))
    assert result["scan"]["uncertain"] is True
    assert all(row["classification"] == "unverified" for row in result["hosts"])
    assert result["summary"]["hosts_unverified"] == 2
    assert "confirmed_absent" not in result
    assert (Hardware.query.count(), VM.query.count(), AppService.query.count()) == before


def test_service_scan_does_not_double_count_host_open_ports(inventory):
    result = compare_network_wide(scan(
        hosts=[{"ip": "192.168.1.16", "hostname": "pi.hole", "open_ports": 3}],
        services=[service("192.168.1.16", 80)]))
    assert host_row(result, "192.168.1.16")["open_ports"] == 3


def test_missing_and_failed_scans_never_infer_absence(inventory):
    result = compare_network_wide(scan(hosts=[], status="failed"))
    assert result["hosts"] == [] and result["services"] == []
    assert "never" in result["reason"] and "removed" in result["reason"]
    assert result["summary"]["hosts_discovered"] == 0


def test_scan_validation_rejects_malformed_input_and_bad_ports(app):
    for value in (None, {}, {"type": "unknown", "status": "completed", "results": []},
                  {"type": "discover", "status": "weird", "results": []},
                  {"type": "discover", "status": "completed"}):
        with pytest.raises(NetworkWideError):
            compare_network_wide(value)
    # Malformed rows are skipped with warnings rather than inventing matches.
    result = compare_network_wide({"type": "portscan", "status": "completed",
                                   "hosts": [{"ip": "not-an-ip"}],
                                   "results": [{"ip": "192.168.1.16", "port": 99999},
                                               {"ip": "192.168.1.16", "port": 80}]})
    assert result["services"][0]["port"] == 80
    assert result["scan"]["warnings"]


def test_api_returns_network_wide_result_without_inventory_mutation(inventory, client):
    before = [(row.id, row.name, row.ip_address) for row in Hardware.query.order_by(Hardware.id)]
    response = client.post("/api/network-discovery/reconcile", headers={"X-Admin-Token": "network-test-token"},
                           json={"scan": scan(hosts=[
                               host("192.168.1.50", "blackbox.lan"), host("192.168.1.80")])})
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["source"] == "nmap"
    assert body["summary"]["hosts_discovered"] == 2
    assert body["summary"]["hosts_shared"] == 1
    assert [(row.id, row.name, row.ip_address) for row in Hardware.query.order_by(Hardware.id)] == before
    assert client.post("/api/network-discovery/reconcile", headers={"X-Admin-Token": "network-test-token"},
                       json={}).status_code == 400


def unifi_client(ip="192.168.1.50", mac="AA:BB:CC:DD:EE:02", name="Blackbox client",
                 online=True, last_seen=None, network=None, kind="client", **extra):
    data = {
        "source": "unifi", "kind": kind, "id": f"{kind}-{mac}", "name": name,
        "hostname": "", "mac": mac, "ip": ip, "online": online,
        "last_seen": last_seen, "network": network, "device_type": "wired",
        "state": "ONLINE" if online else "OFFLINE", "observed_at": "2026-11-03T10:00:00Z",
    }
    data.update(extra)
    return data


def test_unifi_enriches_a_shared_nmap_host_without_adding_device_identities(inventory):
    result = reconcile_observations(
        {"type": "discover", "status": "completed", "target": "192.168.1.0/24",
         "completed_at": "2026-11-03T10:00:00Z", "uncertain": False, "warnings": [],
         "hosts": [host("192.168.1.80", "traefik.smitharend.com")], "services": []},
        unifi_observations=[unifi_client(ip="192.168.1.80", mac="AA:BB:CC:DD:EE:01",
                                         name="Betty")],
        unifi_status={"configured": True, "has_data": True, "last_success": "2026-11-03T10:00:00Z"},
    )
    row = result["hosts"][0]
    assert row["classification"] == "shared"
    assert row["sources"] == ["nmap", "unifi"]
    assert row["unifi_matches"][0]["name"] == "Betty"
    assert "UniFi MAC" in row["evidence"]
    assert result["summary"]["nmap_hosts_with_unifi"] == 1
    assert result["summary"]["unifi_only"] == 0


def test_unifi_current_mac_can_supply_missing_nmap_identity_evidence(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.99", "new-device")]),
        unifi_observations=[unifi_client(ip="192.168.1.99", mac="AA:BB:CC:DD:EE:02",
                                         name="Blackbox")],
    )
    row = result["hosts"][0]
    assert row["classification"] == "matched"
    assert row["candidates"][0]["name"] == "Blackbox"
    assert "UniFi MAC" in row["evidence"]


def test_unifi_only_client_is_separate_from_nmap_hosts(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.16", "pi.hole")]),
        unifi_observations=[unifi_client(ip="192.168.1.77", mac="AA:BB:CC:DD:EE:77",
                                         name="Unseen phone")],
    )
    assert [row["ip"] for row in result["hosts"]] == ["192.168.1.16"]
    assert len(result["unifi_only"]) == 1
    assert result["unifi_only"][0]["source"] == "unifi"
    assert result["unifi_only"][0]["unifi_only"] is True
    assert result["summary"]["unifi_only"] == 1
    assert result["summary"]["unifi_clients"] == 1


def test_offline_unifi_client_is_historical_and_never_a_current_host(inventory):
    result = compare_network_wide(
        scan(hosts=[]),
        unifi_observations=[unifi_client(ip="192.168.1.88", mac="AA:BB:CC:DD:EE:88",
                                         name="Old phone", online=False,
                                         last_seen="2026-11-01T00:00:00Z")],
    )
    assert result["hosts"] == []
    assert result["unifi_only"][0]["online"] is False
    assert "UniFi reports it offline/historical" in result["unifi_only"][0]["reason"]
    assert result["summary"]["unifi_current_clients"] == 0
    assert result["summary"]["unifi_historical_clients"] == 1


def test_unifi_ip_conflict_with_nmap_is_ambiguous_and_explained(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.16", "pi.hole")]),
        unifi_observations=[unifi_client(ip="192.168.1.16", mac="AA:BB:CC:DD:EE:02",
                                         name="Blackbox stale client")],
    )
    row = result["hosts"][0]
    assert row["classification"] == "ambiguous"
    assert row["source_conflict"] is True
    assert {candidate["name"] for candidate in row["candidates"]} == {
        "PiHole Main", "Blackbox"}
    assert "Nmap IP and UniFi MAC evidence identify different" in row["reason"]


def test_unifi_offline_identity_does_not_override_nmap_match(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.16", "pi.hole")]),
        unifi_observations=[unifi_client(ip="192.168.1.16", mac="AA:BB:CC:DD:EE:02",
                                         name="Blackbox historical", online=False)],
    )
    row = result["hosts"][0]
    assert row["classification"] == "matched"
    assert row["candidates"][0]["name"] == "PiHole Main"
    assert "UniFi historical record (not current)" in row["evidence"]


def test_unifi_status_and_network_metadata_are_exposed_without_secrets(inventory):
    result = compare_network_wide(
        scan(hosts=[]),
        unifi_observations=[unifi_client(ip="192.168.1.90", network={"name": "IoT", "vlan_id": 20},
                                         name="IoT device")],
        unifi_status={"configured": True, "has_data": True, "last_success": "2026-11-03T10:00:00Z",
                      "stale": False, "error": None},
    )
    assert result["unifi"]["configured"] is True
    assert result["unifi"]["clients"] == 1
    assert result["unifi_only"][0]["network"] == {"name": "IoT", "vlan_id": 20}
    assert "api_key" not in str(result).lower()


def test_unifi_multiple_ips_and_duplicate_macs_are_kept_as_observations(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.99", "multi-interface")]),
        unifi_observations=[
            unifi_client(ip="192.168.1.99", mac="AA:BB:CC:DD:EE:02",
                         name="Blackbox", ips=["192.168.1.99", "192.168.1.98"]),
            unifi_client(ip="192.168.1.77", mac="AA:BB:CC:DD:EE:02",
                         name="Old duplicate MAC", id="client-old"),
        ],
    )
    row = result["hosts"][0]
    assert row["classification"] == "matched"
    assert row["unifi_matches"][0]["ips"] == ["192.168.1.99", "192.168.1.98"]
    assert len(result["unifi_only"]) == 1
    assert result["unifi_only"][0]["unifi_matches"][0]["ip"] == "192.168.1.77"


def test_unifi_network_metadata_is_context_not_identity(inventory):
    result = compare_network_wide(
        scan(hosts=[host("192.168.1.16", "pi.hole")]),
        unifi_observations=[unifi_client(ip="192.168.1.16", mac="AA:BB:CC:DD:EE:03",
                                         name="PiHole Main",
                                         network={"name": "Guest", "vlan_id": 10})],
    )
    row = result["hosts"][0]
    assert row["classification"] == "matched"
    assert row["unifi_matches"][0]["network"] == {"name": "Guest", "vlan_id": 10}
    assert row["network"] == {"id": 1, "name": "LAN", "vlan_id": 1}


def test_unifi_observations_do_not_change_inventory(inventory):
    before = (Hardware.query.count(), VM.query.count(), AppService.query.count())
    compare_network_wide(
        scan(hosts=[host("192.168.1.99")]),
        unifi_observations=[unifi_client(ip="192.168.1.99", mac="AA:BB:CC:DD:EE:02")],
    )
    assert (Hardware.query.count(), VM.query.count(), AppService.query.count()) == before
