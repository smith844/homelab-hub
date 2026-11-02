import threading
import time

import pytest

from hlh_scanner.manager import ScanBusy, ScanManager, ScannerSettings
from hlh_scanner.nmap import ScanResult
from hlh_scanner.targets import TargetError


def _settings(**changes):
    values = {
        "approved_ranges": [],
        "max_hosts": 256,
        "max_concurrency": 1,
        "retention_seconds": 60,
        "max_scan_seconds": 30,
    }
    values.update(changes)
    from hlh_scanner.targets import parse_approved_ranges
    values["approved_ranges"] = parse_approved_ranges(values["approved_ranges"])
    return ScannerSettings(**values)


class FakeScanner:
    def __init__(self, result=None, gate=None):
        self.result = result or ScanResult("completed", hosts=[{"ip": "192.168.1.20"}],
                                           results=[{"ip": "192.168.1.20"}], hosts_up=1)
        self.gate = gate
        self.calls = []

    def scan(self, scan_type, target, ports=None, **kwargs):
        self.calls.append((scan_type, target, ports, kwargs))
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return self.result


def _wait(manager, scan_id):
    for _ in range(100):
        scan = manager.get(scan_id)
        if scan["status"] != "running":
            return scan
        time.sleep(0.02)
    raise AssertionError("scan did not finish")


def test_completed_job_has_timestamps_counts_and_validated_target():
    manager = ScanManager(_settings(approved_ranges=["192.168.1.0/24"]), FakeScanner())
    scan = manager.start("discover", "192.168.1.25")
    assert scan["status"] in ("running", "completed") and scan["started_at"].endswith("Z")
    finished = _wait(manager, scan["scan_id"])
    assert finished["status"] == "completed" and finished["complete"] is True
    assert finished["target"] == "192.168.1.25"
    assert finished["completed_at"].endswith("Z")
    assert finished["result_count"] == 1 and finished["hosts_up"] == 1
    assert manager.scanner.calls[0][1] == "192.168.1.25"


def test_invalid_target_and_ports_are_rejected_without_starting_a_thread():
    manager = ScanManager(_settings(approved_ranges=["192.168.1.0/24"]), FakeScanner())
    with pytest.raises(TargetError):
        manager.start("discover", "8.8.8.8")
    with pytest.raises(TargetError):
        manager.start("services", "192.168.1.20", "80;rm -rf /")
    with pytest.raises(TargetError):
        manager.start("unknown", "192.168.1.20")


def test_concurrency_limit_rejects_a_second_running_scan():
    gate = threading.Event()
    manager = ScanManager(_settings(approved_ranges=["192.168.1.0/24"]), FakeScanner(gate=gate))
    first = manager.start("discover", "192.168.1.0/24")
    with pytest.raises(ScanBusy):
        manager.start("discover", "192.168.1.0/24")
    gate.set()
    _wait(manager, first["scan_id"])
    second = manager.start("discover", "192.168.1.0/24")
    assert second["status"] in ("running", "completed")
    _wait(manager, second["scan_id"])


def test_manager_surfaces_failed_and_partial_statuses():
    failed = ScanManager(_settings(approved_ranges=["192.168.1.0/24"]),
                         FakeScanner(ScanResult("failed", error="nmap missing")))
    failed_scan = _wait(failed, failed.start("discover", "192.168.1.20")["scan_id"])
    assert failed_scan["status"] == "failed" and failed_scan["complete"] is False
    assert failed_scan["error"] == "nmap missing"

    partial = ScanManager(_settings(approved_ranges=["192.168.1.0/24"]),
                          FakeScanner(ScanResult("partial", hosts=[{"ip": "192.168.1.20"}],
                                                 results=[{"ip": "192.168.1.20"}],
                                                 error="timed out")))
    partial_scan = _wait(partial, partial.start("discover", "192.168.1.20")["scan_id"])
    assert partial_scan["status"] == "partial" and partial_scan["complete"] is False
    assert partial_scan["results"]


def test_scan_results_expire_after_retention():
    settings = _settings(approved_ranges=["192.168.1.0/24"], retention_seconds=60)
    manager = ScanManager(settings, FakeScanner())
    scan_id = manager.start("discover", "192.168.1.20")["scan_id"]
    _wait(manager, scan_id)
    # Make the completed timestamp old without waiting a minute.
    with manager._lock:
        manager._scans[scan_id]["completed_at"] = "2000-01-01T00:00:00Z"
    assert manager.get(scan_id) is None
