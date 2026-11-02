import pytest

from hlh_scanner.targets import TargetError, parse_approved_ranges, validate_ports, validate_target

APPROVED = ["192.168.1.0/24", "10.20.0.0/16"]


def test_targets_must_be_inside_an_approved_private_range():
    assert validate_target("192.168.1.25", APPROVED) == "192.168.1.25"
    assert validate_target("192.168.1.0/24", APPROVED) == "192.168.1.0/24"
    assert validate_target("10.20.30.40/32", APPROVED) == "10.20.30.40/32"
    assert validate_target("192.168.1.99/24", APPROVED) == "192.168.1.0/24"
    with pytest.raises(TargetError, match="outside"):
        validate_target("192.168.2.1", APPROVED)
    with pytest.raises(TargetError, match="outside"):
        validate_target("192.168.1.0/23", APPROVED)
    with pytest.raises(TargetError, match="private IPv4"):
        validate_target("8.8.8.8", ["0.0.0.0/0"])
    with pytest.raises(TargetError, match="approved"):
        validate_target("192.168.1.1", [])
    with pytest.raises(TargetError, match="IPv4"):
        validate_target("2001:db8::1", ["::/0"])
    with pytest.raises(TargetError, match="addresses"):
        validate_target("192.168.1.0/24", APPROVED, max_hosts=10)


def test_approved_ranges_reject_public_loopback_and_unusable_ranges():
    assert [str(item) for item in parse_approved_ranges("192.168.1.0/24, 10.0.0.0/8")] == [
        "192.168.1.0/24", "10.0.0.0/8"]
    for value in ("8.8.8.0/24", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "not-a-cidr"):
        with pytest.raises(TargetError):
            parse_approved_ranges(value)


def test_ports_are_canonical_and_bounded():
    assert validate_ports("443, 80,8000-8002,80") == "80,443,8000,8001,8002"
    assert validate_ports("1-3") == "1,2,3"
    for value in ("0", "65536", "80-70", "80;rm -rf /", "80,,443", "", "1-300"):
        with pytest.raises(TargetError):
            validate_ports(value, max_ports=10 if value == "1-300" else 256)
    with pytest.raises(TargetError, match="limit"):
        validate_ports("1-20", max_ports=10)
