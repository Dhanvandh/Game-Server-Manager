import os

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-min-32-chars!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-refresh-secret-key-min-32!!")
os.environ.setdefault("FLASK_SECRET_KEY", "test-flask")
os.environ.setdefault("SOCKETIO_ASYNC_MODE", "threading")


@pytest.fixture()
def app(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'gsm.db'}"
    from app import create_app

    return create_app()


@pytest.fixture()
def client(app):
    return app.test_client()
