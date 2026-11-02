import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, '..', '..', 'data', 'homelab-hub.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Allow larger request bodies for base64 image uploads (5MB)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    # Administrative token for management writes. When empty, writes are disabled.
    ADMIN_TOKEN = (os.environ.get("HLH_ADMIN_TOKEN") or os.environ.get("ADMIN_TOKEN") or "").strip()
    # Optional read-only FolderView Plus configuration for server-side sync.
    FOLDERVIEW_CONFIG_PATH = (os.environ.get("FOLDERVIEW_CONFIG_PATH") or "").strip() or None
    # Separate, restricted Nmap scanner service. Scanning stays disabled until
    # both scanner URL/token and at least one approved private range are set.
    SCANNER_URL = (os.environ.get("HLH_SCANNER_URL") or "").strip()
    SCANNER_TOKEN = (os.environ.get("HLH_SCANNER_TOKEN") or "").strip()
    SCANNER_APPROVED_RANGES = (os.environ.get("HLH_SCANNER_APPROVED_RANGES") or "").strip()
    SCANNER_DEFAULT_PORTS = (os.environ.get("HLH_SCANNER_DEFAULT_PORTS") or "22,80,443,445,3389,8080,8443").strip()
    SCANNER_MAX_HOSTS = (os.environ.get("HLH_SCANNER_MAX_HOSTS") or "1024").strip()
    SCANNER_MAX_PORTS = (os.environ.get("HLH_SCANNER_MAX_PORTS") or "256").strip()
