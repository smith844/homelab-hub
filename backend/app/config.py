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
