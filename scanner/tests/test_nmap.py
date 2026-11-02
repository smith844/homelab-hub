import pytest

from hlh_scanner.nmap import (
    CommandOutcome,
    NmapParseError,
    NetworkScanner,
    build_discovery_arguments,
    build_service_arguments,
    parse_nmap_xml,
)


def _xml(hosts: str, up="1", down="0", exit_value="success") -> str:
    return f"""<?xml version="1.0"?>
<nmaprun>
  {hosts}
  <runstats><hosts up="{up}" down="{down}" total="{int(up) + int(down)}"/>
    <finished exit="{exit_value}"/>
  </runstats>
</nmaprun>"""


def _host(ip="192.168.1.20", state="up", mac=None, vendor=None, hostname="nas.lan",
          ports="", os_name=None):
    addresses = f'<address addr="{ip}" addrtype="ipv4"/>'
    if mac:
        vendor_attr = f' vendor="{vendor}"' if vendor else ""
        addresses += f'<address addr="{mac}" addrtype="mac"{vendor_attr}/>'
    hostname_xml = f'<hostnames><hostname name="{hostname}" type="PTR"/></hostnames>' if hostname else ""
    os_xml = f'<os><osmatch name="{os_name}" accuracy="90"/></os>' if os_name else ""
    return (f'<host><status state="{state}" reason="arp-response"/>{addresses}'
            f"{hostname_xml}{os_xml}<ports>{ports}</ports></host>")


def test_discovery_command_is_bounded_and_has_no_aggressive_features():
    argv = build_discovery_arguments("nmap", "192.168.1.0/24")
    assert argv[0] == "nmap"
    assert argv[-1] == "192.168.1.0/24"
    assert "-sn" in argv and "-PR" in argv
    assert "--host-timeout" in argv and "60s" in argv
    assert "-T3" in argv
    for forbidden in ("-O", "--osscan-guess", "--script", "-sV", "-A"):
        assert forbidden not in argv


def test_service_command_uses_tcp_connect_and_validated_port_list():
    argv = build_service_arguments("nmap", "192.168.1.20", "22,80,443")
    assert "-sT" in argv
    assert "-O" not in argv and "--script" not in argv
    assert argv[argv.index("-p") + 1] == "22,80,443"
    assert argv[-1] == "192.168.1.20"


def test_discovers_hosts_with_mac_vendor_hostname_and_os_subset():
    xml = _xml(_host(mac="AA:BB:CC:DD:EE:FF", vendor="Acme", hostname="nas.lan",
                     os_name="Linux 5.x"))
    parsed = parse_nmap_xml(xml, "discover")
    assert parsed.finished_success is True
    assert parsed.hosts_up == 1 and parsed.hosts_down == 0
    assert parsed.results == [{
        "ip": "192.168.1.20", "hostname": "nas.lan",
        "mac": "AA:BB:CC:DD:EE:FF", "vendor": "Acme", "os": "Linux 5.x",
        "open_ports": 0,
    }]


def test_services_include_open_tcp_rows_and_ignore_closed_ports():
    ports = (
        '<port protocol="tcp" portid="22"><state state="open"/>'
        '<service name="ssh" product="OpenSSH" version="9.6"/></port>'
        '<port protocol="tcp" portid="443"><state state="closed"/>'
        '<service name="https"/></port>'
        '<port protocol="udp" portid="53"><state state="open"/>'
        '<service name="domain"/></port>'
    )
    parsed = parse_nmap_xml(_xml(_host(ports=ports, hostname=None)), "services")
    assert len(parsed.hosts) == 1
    assert parsed.hosts[0]["open_ports"] == 1
    assert parsed.results == [{
        "ip": "192.168.1.20", "hostname": "", "mac": "", "vendor": "",
        "os": "", "open_ports": 1, "port": 22, "protocol": "tcp",
        "state": "open", "service_name": "ssh", "service_version": "OpenSSH 9.6",
    }]


def test_down_hosts_are_counted_but_never_reported_as_results():
    parsed = parse_nmap_xml(_xml(_host(state="down"), up="0", down="1"), "discover")
    assert parsed.hosts == [] and parsed.results == []
    assert parsed.hosts_up == 0 and parsed.hosts_down == 1
    assert parsed.finished_success is True


def test_invalid_host_and_port_rows_are_skipped_with_warnings():
    bad_host = '<host><status state="up"/><address addr="not-an-ip" addrtype="ipv4"/></host>'
    bad_port = _host(ports='<port protocol="tcp" portid="99999"><state state="open"/></port>')
    parsed = parse_nmap_xml(_xml(bad_host + bad_port), "services")
    assert parsed.results == []
    assert any("IPv4" in warning for warning in parsed.warnings)
    assert any("port" in warning for warning in parsed.warnings)


def test_malformed_and_non_nmap_xml_fail_closed():
    for value in ("", "<html />", "not xml"):
        with pytest.raises(NmapParseError):
            parse_nmap_xml(value, "discover")
    with pytest.raises(NmapParseError):
        parse_nmap_xml(_xml(""), "unknown")


def test_scanner_reports_completed_only_for_successful_finished_runs():
    xml = _xml(_host())
    scanner = NetworkScanner(runner=lambda argv, timeout: CommandOutcome(0, xml))
    result = scanner.scan("discover", "192.168.1.20", approved_ranges=["192.168.1.0/24"])
    assert result.status == "completed" and result.complete is True
    assert result.results[0]["ip"] == "192.168.1.20"


def test_timeout_and_nonzero_exit_expose_partial_results_without_claiming_completion():
    xml = _xml(_host(), exit_value="error")
    timed_out = NetworkScanner(runner=lambda argv, timeout: CommandOutcome(-9, xml, "", True))
    result = timed_out.scan("discover", "192.168.1.20", approved_ranges=["192.168.1.0/24"])
    assert result.status == "partial" and result.complete is False
    assert result.results and "timed out" in result.error

    failed = NetworkScanner(runner=lambda argv, timeout: CommandOutcome(1, xml, "nmap: error"))
    result = failed.scan("discover", "192.168.1.20", approved_ranges=["192.168.1.0/24"])
    assert result.status == "partial" and "nmap failed" in result.error

    malformed = NetworkScanner(runner=lambda argv, timeout: CommandOutcome(1, "", "permission denied"))
    result = malformed.scan("discover", "192.168.1.20", approved_ranges=["192.168.1.0/24"])
    assert result.status == "failed" and "parse" in result.error.lower()


def test_scanner_rejects_unapproved_targets_before_running_nmap():
    called = []
    scanner = NetworkScanner(runner=lambda argv, timeout: called.append(argv))
    result = scanner.scan("discover", "8.8.8.8", approved_ranges=["192.168.1.0/24"])
    assert result.status == "failed"
    assert called == []
