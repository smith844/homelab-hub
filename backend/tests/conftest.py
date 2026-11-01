import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.models import db  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "folderview"


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        TESTING = True
        MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    application = create_app(TestConfig)
    with application.app_context():
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def folder_fixture():
    def _load(name):
        with open(FIXTURE_DIR / name, encoding="utf-8") as handle:
            return json.load(handle)

    return _load
