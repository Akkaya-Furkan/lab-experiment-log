import re
import sqlite3

import pytest

from lablog import create_app
from lablog.demo import DEMO_PASSWORD, seed_demo


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATABASE": str(tmp_path / "test.sqlite3")})
    with sqlite3.connect(app.config["DATABASE"]) as db:
        seed_demo(db)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, path="/"):
    response = client.get(path, follow_redirects=True)
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data)[1].decode()


def post(client, path, data=None):
    return client.post(path, data={"csrf_token": token(client), **(data or {})})


def login(client, username="demo"):
    return post(client, "/login", {"username": username, "password": DEMO_PASSWORD})


@pytest.fixture
def owner(client):
    assert login(client).status_code == 302
    return client


def snapshot(app):
    with sqlite3.connect(app.config["DATABASE"]) as db:
        # Full state, not only counts: detects partially changed records too.
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("users", "experiments", "samples", "measurements", "attachments")}
