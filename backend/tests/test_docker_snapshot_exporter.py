"""End-to-end checks for the read-only Docker snapshot exporter.

The scripts/docker-snapshot.sh exporter is exercised through a fake Docker CLI,
so no Docker daemon runs and no live host is touched. Every accepted snapshot is
also fed through the real Phase 4 adapter to prove contract compatibility.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.discovery_adapters import ReconciliationError, normalise_snapshot

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "docker-snapshot.sh"

CONTAINER_A = "a" * 64
CONTAINER_B = "b" * 64
IMAGE_A = "sha256:" + "1" * 64
IMAGE_B = "sha256:" + "2" * 64

FAKE_DOCKER = r"""#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case "${FAKE_DOCKER_FAIL:-}" in
    ps) echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock" >&2; exit 1 ;;
    inspect) echo "Error: No such object: deadbeef" >&2; exit 1 ;;
esac
case "${1:-}" in
    ps)
        if [[ -n "${FAKE_DOCKER_IDS:-}" ]]; then
            printf '%s\n' ${FAKE_DOCKER_IDS}
        fi
        exit 0
        ;;
    inspect)
        cat "$FAKE_DOCKER_INSPECT"
        exit 0
        ;;
esac
echo "unexpected fake docker invocation: $*" >&2
exit 64
"""


def _candidate_bashes():
    env_bash = os.environ.get("HLH_TEST_BASH")
    if env_bash:
        yield env_bash
    if os.name == "nt":
        for value in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            yield value
    system_bash = shutil.which("bash")
    if system_bash:
        yield system_bash
    yield "/bin/bash"


@pytest.fixture(scope="session")
def bash_bin():
    for candidate in _candidate_bashes():
        try:
            result = subprocess.run([candidate, "-c", "printf ok"], capture_output=True,
                                    text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout == "ok":
            return candidate
    pytest.skip("bash is required to exercise scripts/docker-snapshot.sh")


@pytest.fixture(scope="session")
def jq_bin():
    candidates = [os.environ.get("HLH_TEST_JQ"), shutil.which("jq")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("jq is required to exercise scripts/docker-snapshot.sh")


def _write(path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="\n")


class Exporter:
    def __init__(self, tmp_path: Path, bash_bin: str, jq_bin: str):
        self.dir = tmp_path
        self.bash = bash_bin
        self.script = tmp_path / "docker-snapshot.sh"
        shutil.copyfile(SCRIPT, self.script)
        self.shim = tmp_path / "docker"
        _write(self.shim, FAKE_DOCKER)
        subprocess.run([bash_bin, "-c", 'chmod +x "$1"', "--", self.shim.name],
                       cwd=tmp_path, check=True, capture_output=True, text=True, timeout=30)
        self.log = tmp_path / "docker-calls.log"
        self.env = os.environ.copy()
        self.env["PATH"] = os.pathsep.join([str(tmp_path), str(Path(jq_bin).parent), self.env.get("PATH", "")])
        self.env["FAKE_DOCKER_LOG"] = str(self.log)
        self.env.pop("HLH_HOST_KEY", None)
        self.env.pop("HLH_SNAPSHOT_OUTPUT", None)
        self.env.pop("HLH_DOCKER_BIN", None)
        self.env.pop("HLH_JQ_BIN", None)

    def inspect(self, containers):
        path = self.dir / "inspect.json"
        _write(path, json.dumps(containers))
        return path

    def run(self, *, ids=(), inspect=None, fail=None, output="snapshot.json",
            host_key="betty", extra_args=(), extra_env=None):
        env = dict(self.env)
        env["FAKE_DOCKER_IDS"] = " ".join(ids)
        env["FAKE_DOCKER_LOG"] = str(self.log)
        if inspect is not None:
            env["FAKE_DOCKER_INSPECT"] = str(inspect)
        if fail:
            env["FAKE_DOCKER_FAIL"] = fail
        if extra_env:
            env.update(extra_env)
        args = [self.bash, self.script.name]
        if host_key is not None:
            args += ["--host-key", host_key]
        args += ["--output", output, *extra_args]
        result = subprocess.run(args, cwd=self.dir, env=env, capture_output=True,
                                text=True, timeout=120)
        path = self.dir / output
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return result, payload

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


@pytest.fixture()
def exporter(tmp_path, bash_bin, jq_bin):
    return Exporter(tmp_path, bash_bin, jq_bin)


def docker_container(name, container_id, image_id, image, **extra):
    data = {"Name": f"/{name}", "Id": container_id, "Image": image_id,
            "Config": {"Image": image}}
    data.update(extra)
    return data


def test_complete_snapshot_includes_running_and_stopped_containers(exporter):
    inspect = exporter.inspect([
        docker_container("plex", CONTAINER_A, IMAGE_A, "plex:1.0",
                         State={"Status": "running"}, Config={"Image": "plex:1.0", "Env": ["PLEX_TOKEN=do-not-export"]},
                         Mounts=[{"Source": "/mnt/private/media"}], Labels={"private": "do-not-export"}),
        docker_container("old-backup", CONTAINER_B, IMAGE_B, "backup:old",
                         State={"Status": "exited"}),
    ])
    result, payload = exporter.run(ids=[CONTAINER_A, CONTAINER_B], inspect=inspect)

    assert result.returncode == 0, result.stderr
    assert payload["schema_version"] == 1
    assert payload["host_key"] == "betty"
    assert payload["status"] == "success"
    assert payload["complete"] is True
    assert payload["coverage"] == "all_containers"
    assert payload["completed_at"].endswith("Z") and len(payload["completed_at"]) == 20
    assert [row["container_name"] for row in payload["containers"]] == ["plex", "old-backup"]
    assert payload["containers"][0] == {
        "container_name": "plex",
        "container_id": CONTAINER_A,
        "image_id": IMAGE_A,
        "image": "plex:1.0",
    }
    serialised = json.dumps(payload)
    for private in ("do-not-export", "PLEX_TOKEN", "/mnt/private/media", "private"):
        assert private not in serialised

    calls = exporter.calls()
    assert calls and calls[0].startswith("ps --all --quiet --no-trunc")
    assert calls[1].startswith("inspect --type container")

    scan = normalise_snapshot(payload, "betty")
    assert scan["status"] == "success" and scan["complete"] is True
    assert scan["coverage"] == "all_containers" and scan["authoritative"] is True
    assert [row["container_key"] for row in scan["containers"]] == ["plex", "old-backup"]
    assert scan["containers"][0]["image_id"] == IMAGE_A
    assert scan["containers"][0]["observed_at"].startswith(payload["completed_at"][:-1])


def test_empty_host_is_a_complete_authoritative_snapshot(exporter):
    result, payload = exporter.run(ids=[])

    assert result.returncode == 0, result.stderr
    assert payload["status"] == "success" and payload["complete"] is True
    assert payload["coverage"] == "all_containers" and payload["containers"] == []
    assert exporter.calls() == ["ps --all --quiet --no-trunc"]
    assert normalise_snapshot(payload, "betty")["authoritative"] is True


def test_host_key_round_trips_and_mismatch_is_rejected(exporter):
    result, payload = exporter.run(ids=[], host_key="Blackbox")

    assert result.returncode == 0, result.stderr
    assert normalise_snapshot(payload, "blackbox")["status"] == "success"
    with pytest.raises(ReconciliationError):
        normalise_snapshot(payload, "betty")


@pytest.mark.parametrize("failure, inspect_factory", [
    ("ps", None),
    ("inspect", lambda exporter: exporter.inspect([
        docker_container("plex", CONTAINER_A, IMAGE_A, "plex:1.0")])),
])
def test_docker_command_failures_emit_failed_non_authoritative_evidence(exporter, failure, inspect_factory):
    inspect = inspect_factory(exporter) if inspect_factory else None
    ids = [CONTAINER_A] if failure == "inspect" else []
    result, payload = exporter.run(ids=ids, inspect=inspect, fail=failure)

    assert result.returncode == 3
    assert result.stderr.strip()
    assert payload["status"] == "failed"
    assert payload["complete"] is False
    assert payload["coverage"] == "unknown"
    assert payload["containers"] == []
    assert payload["error"]
    assert payload["completed_at"].endswith("Z")
    scan = normalise_snapshot(payload, "betty")
    assert scan["authoritative"] is False
    assert scan["containers"] == []


def test_malformed_and_incomplete_inspect_results_are_not_published(exporter):
    malformed = exporter.dir / "malformed.json"
    _write(malformed, "[{not json")

    result, payload = exporter.run(ids=[CONTAINER_A], inspect=malformed)
    assert result.returncode == 3
    assert payload["status"] == "failed" and payload["containers"] == []

    partial = exporter.inspect([docker_container("plex", CONTAINER_A, IMAGE_A, "plex:1.0")])
    result, payload = exporter.run(ids=[CONTAINER_A, CONTAINER_B], inspect=partial)
    assert result.returncode == 3
    assert "incomplete collection" in payload["error"].lower()
    assert payload["status"] == "failed"


@pytest.mark.parametrize("containers", [
    [docker_container("bad name", CONTAINER_A, IMAGE_A, "plex:1.0")],
    [docker_container("plex", "", IMAGE_A, "plex:1.0")],
    [docker_container("plex", CONTAINER_A, "", "plex:1.0")],
    [docker_container("plex", CONTAINER_A, IMAGE_A, "plex:1.0"),
     docker_container("plex", CONTAINER_B, IMAGE_B, "plex:2.0")],
])
def test_invalid_container_metadata_is_rejected(exporter, containers):
    inspect = exporter.inspect(containers)
    result, payload = exporter.run(ids=[CONTAINER_A, CONTAINER_B][:len(containers)], inspect=inspect)

    assert result.returncode == 3
    assert payload["status"] == "failed" and payload["complete"] is False
    assert payload["containers"] == []


def test_unexpected_container_ids_from_ps_are_treated_as_failure(exporter):
    result, payload = exporter.run(ids=["not-a-container-id"])

    assert result.returncode == 3
    assert payload["status"] == "failed"
    assert "unexpected container id" in payload["error"].lower()


def test_failed_collection_replaces_output_atomically_without_stale_fragments(exporter):
    stale = exporter.dir / "snapshot.json"
    _write(stale, '{"note": "previous output"}')

    result, payload = exporter.run(ids=[], fail="ps")

    assert result.returncode == 3
    assert payload["status"] == "failed"
    assert sorted(path.name for path in exporter.dir.glob("snapshot.json*")) == ["snapshot.json"]


def test_missing_host_key_writes_nothing(exporter):
    result, payload = exporter.run(ids=[], host_key=None)

    assert result.returncode == 2
    assert payload is None
    assert "--host-key" in result.stderr


def test_help_documents_the_contract_without_collecting(exporter):
    result = subprocess.run([exporter.bash, exporter.script.name, "--help"], cwd=exporter.dir,
                            env=exporter.env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0
    assert "schema_version 1" in result.stdout
    assert exporter.calls() == []
