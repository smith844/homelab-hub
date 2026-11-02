"""Deployment-script contract checks for the supervised Betty scanner test."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_SCRIPT = ROOT / "scripts" / "deploy-betty-test.sh"
SCANNER_SCRIPT = ROOT / "scripts" / "deploy-betty-test-scanner.sh"
DEPLOY_DOC = ROOT / "docs" / "scanner-betty-test-deployment.md"


def _candidate_bashes():
    if os.environ.get("HLH_TEST_BASH"):
        yield os.environ["HLH_TEST_BASH"]
    if os.name == "nt":
        yield r"C:\Program Files\Git\bin\bash.exe"
        yield r"C:\Program Files\Git\usr\bin\bash.exe"
    found = shutil.which("bash")
    if found:
        yield found
    yield "/bin/bash"


@pytest.fixture(scope="session")
def bash_bin():
    for candidate in _candidate_bashes():
        try:
            result = subprocess.run([candidate, "-c", "printf ok"], capture_output=True,
                                    text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout == "ok":
            return candidate
    pytest.skip("bash is not available for deployment-script syntax checks")


def test_scanner_script_isolated_and_minimally_privileged():
    text = SCANNER_SCRIPT.read_text(encoding="utf-8")
    assert 'CONTAINER="homelab-hub-nmap-test"' in text
    assert 'NETWORK="homelab-hub-nmap-test-net"' in text
    assert 'SCANNER_ENV="$CONFIG_DIR/scanner-test.env"' in text
    assert '--network "$NETWORK"' in text
    assert "--cap-drop ALL" in text
    assert "--cap-add NET_RAW" in text
    assert "--read-only" in text
    assert "--security-opt no-new-privileges" in text
    assert "--env-file \"$SCANNER_ENV\"" in text
    assert "--env HLH_SCANNER_BIND=0.0.0.0" in text
    assert "docker port \"$CONTAINER\"" in text
    assert "http://127.0.0.1:8791/health" in text
    for forbidden in ("--publish", "-p 8791", "--network host", "/var/run/docker.sock"):
        assert forbidden not in text
    assert "homelab-hub-scanner" not in re.sub(r"#[^\n]*", "", text)
    assert not re.search(r"docker\s+(?:rm|stop|start|restart|update)[^\n]*8791", text)
    assert "set -Eeuo pipefail" in text


def test_web_script_preserves_safeguards_and_always_joins_scanner_network():
    text = WEB_SCRIPT.read_text(encoding="utf-8")
    assert 'CONTAINER="homelab-hub-redesign"' in text
    assert 'PORT="8790"' in text
    assert 'FOLDERVIEW="/boot/config/plugins/folderview.plus/docker.json"' in text
    assert '--publish "$PORT:8000"' in text
    assert "--volume \"$DATA_DIR:/data\"" in text
    assert "--mount \"type=bind,source=$FOLDERVIEW" in text
    assert '--env-file "$CONFIG_DIR/phase3.env"' in text
    assert "HLH_ADMIN_TOKEN" in text
    assert "SQLite backup" in text or "source.backup(target)" in text
    assert "PREVIOUS=" in text and "docker rename" in text
    assert "docker update --restart=no" in text
    assert "docker network create --driver bridge" in text
    assert '--network "$NETWORK"' in text
    assert 'HLH_SCANNER_URL=$SCANNER_URL' in text
    assert '--env-file "$SCANNER_ENV"' in text
    assert 'SCANNER_ACTIVE=1' in text and "HLH_SCANNER_APPROVED_RANGES" in text
    assert "homelab-hub-nmap-test:8791/health" in text
    assert "8000:8000" not in text
    for forbidden in ("8791:8791", "--publish 8791", "/var/run/docker.sock",
                      "homelab-hub-scanner"):
        assert forbidden not in text


def test_scripts_never_print_the_scanner_token():
    for path in (WEB_SCRIPT, SCANNER_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert 'cat "$SCANNER_ENV"' not in text
        assert "echo $HLH_SCANNER_TOKEN" not in text
        assert 'printf "%s" "$HLH_SCANNER_TOKEN"' not in text
        # Only presence checks and --env-file may reference the token name.
        assert "openssl rand" not in text


def test_deployment_document_has_the_supervised_sequence():
    text = DEPLOY_DOC.read_text(encoding="utf-8")
    assert "deploy-betty-test-scanner.sh" in text
    assert "deploy-betty-test.sh" in text
    assert "scanner-test.env" in text
    assert "openssl rand -hex 32" in text
    assert "homelab-hub-nmap-test-net" in text
    assert "homelab-hub-nmap-test" in text
    assert "no published host port" in text.lower()
    assert "one explicitly approved host" in text
    assert "Do not derive" in text
    assert "Never publish port `8791`" in text


def test_shell_scripts_parse(bash_bin, tmp_path):
    for path in (WEB_SCRIPT, SCANNER_SCRIPT):
        copy = tmp_path / path.name
        shutil.copyfile(path, copy)
        result = subprocess.run([bash_bin, "-n", copy.name], cwd=tmp_path,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
