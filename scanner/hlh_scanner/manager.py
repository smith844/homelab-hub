"""In-memory scan jobs with bounded concurrency, timestamps and TTL expiry."""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .nmap import NetworkScanner, ScanResult
from .targets import (
    DEFAULT_PORTS,
    MAX_HOSTS,
    MAX_PORTS,
    TargetError,
    parse_approved_ranges,
    validate_ports,
    validate_target,
)


class ScanBusy(RuntimeError):
    """The scanner is already running its configured maximum number of jobs."""


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass
class ScannerSettings:
    nmap_bin: str = "nmap"
    approved_ranges: list = field(default_factory=list)
    default_ports: str = DEFAULT_PORTS
    max_hosts: int = MAX_HOSTS
    max_ports: int = MAX_PORTS
    max_scan_seconds: int = 300
    max_concurrency: int = 1
    retention_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "ScannerSettings":
        approved = parse_approved_ranges(os.environ.get("HLH_SCANNER_APPROVED_RANGES", ""))
        default_ports = os.environ.get("HLH_SCANNER_DEFAULT_PORTS", DEFAULT_PORTS).strip() or DEFAULT_PORTS
        default_ports = validate_ports(default_ports, MAX_PORTS)
        return cls(
            nmap_bin=os.environ.get("HLH_SCANNER_NMAP", "nmap").strip() or "nmap",
            approved_ranges=approved,
            default_ports=default_ports,
            max_hosts=_int_setting("HLH_SCANNER_MAX_HOSTS", MAX_HOSTS, 1, 65536),
            max_ports=_int_setting("HLH_SCANNER_MAX_PORTS", MAX_PORTS, 1, 4096),
            max_scan_seconds=_int_setting("HLH_SCANNER_MAX_SCAN_SECONDS", 300, 5, 1800),
            max_concurrency=_int_setting("HLH_SCANNER_MAX_CONCURRENCY", 1, 1, 4),
            retention_seconds=_int_setting("HLH_SCANNER_RETENTION_SECONDS", 3600, 60, 86400),
        )


class ScanManager:
    """Run one or more validated scans in background daemon threads.

    Jobs are deliberately in memory: results disappear on scanner restart and
    after the retention period. This component never writes HomeLab-Hub's
    inventory database.
    """

    def __init__(self, settings: ScannerSettings | None = None,
                 scanner: NetworkScanner | None = None):
        self.settings = settings or ScannerSettings()
        self.scanner = scanner or NetworkScanner(
            nmap_bin=self.settings.nmap_bin,
            max_scan_seconds=self.settings.max_scan_seconds,
        )
        self._lock = threading.Lock()
        self._scans: dict[str, dict] = {}

    def _purge_unlocked(self) -> None:
        now = time.time()
        for scan_id in list(self._scans):
            job = self._scans[scan_id]
            if job["status"] == "running":
                continue
            completed = job.get("completed_at")
            if completed is None:
                continue
            try:
                finished = datetime.fromisoformat(completed.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if now - finished > self.settings.retention_seconds:
                self._scans.pop(scan_id, None)

    def start(self, scan_type: str, target: str, ports: str | None = None) -> dict:
        if scan_type not in ("discover", "services"):
            raise TargetError("Scan type must be discover or services")
        canonical = validate_target(target, self.settings.approved_ranges, self.settings.max_hosts)
        port_text = validate_ports(ports, self.settings.max_ports) if scan_type == "services" else ""
        with self._lock:
            self._purge_unlocked()
            running = sum(job["status"] == "running" for job in self._scans.values())
            if running >= self.settings.max_concurrency:
                raise ScanBusy(
                    "The scanner is already running its maximum number of scans; retry shortly"
                )
            scan_id = str(uuid.uuid4())
            self._scans[scan_id] = {
                "scan_id": scan_id,
                "type": "portscan" if scan_type == "services" else "discover",
                "scan_type": scan_type,
                "status": "running",
                "progress": 0,
                "target": canonical,
                "params": {"target": canonical, "ports": port_text or None},
                "started_at": utc_iso(),
                "completed_at": None,
                "hosts_up": 0,
                "hosts_down": 0,
                "result_count": 0,
                "hosts": [],
                "results": [],
                "warnings": [],
                "error": None,
                "complete": False,
            }
        thread = threading.Thread(
            target=self._run,
            args=(scan_id, scan_type, canonical, port_text),
            daemon=True,
            name=f"hlh-scan-{scan_id[:8]}",
        )
        thread.start()
        return self.get(scan_id)

    def _run(self, scan_id: str, scan_type: str, target: str, port_text: str) -> None:
        self._update(scan_id, progress=10)
        try:
            result = self.scanner.scan(
                scan_type, target, port_text or None,
                approved_ranges=self.settings.approved_ranges,
                max_hosts=self.settings.max_hosts,
                max_ports=self.settings.max_ports,
            )
        except Exception as exc:  # noqa: BLE001 - report scanner failures as job state
            result = ScanResult("failed", error=f"Scanner failure: {exc}")
        self._finish(scan_id, result)

    def _update(self, scan_id: str, **changes) -> None:
        with self._lock:
            job = self._scans.get(scan_id)
            if job is not None:
                job.update(changes)

    def _finish(self, scan_id: str, result: ScanResult) -> None:
        with self._lock:
            job = self._scans.get(scan_id)
            if job is None:
                return
            job.update({
                "status": result.status,
                "progress": 100,
                "completed_at": utc_iso(),
                "hosts_up": result.hosts_up,
                "hosts_down": result.hosts_down,
                "result_count": len(result.results),
                "hosts": copy.deepcopy(result.hosts),
                "results": copy.deepcopy(result.results),
                "warnings": list(result.warnings),
                "error": result.error,
                "complete": result.complete,
            })

    def get(self, scan_id: str) -> dict | None:
        with self._lock:
            self._purge_unlocked()
            job = self._scans.get(scan_id)
            return copy.deepcopy(job) if job is not None else None

    def active_count(self) -> int:
        with self._lock:
            self._purge_unlocked()
            return sum(job["status"] == "running" for job in self._scans.values())
