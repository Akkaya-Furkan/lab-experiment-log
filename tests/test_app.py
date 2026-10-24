import csv
import io
import sqlite3

import pytest
from werkzeug.security import check_password_hash

from lablog import create_app
from lablog.demo import ATTACHMENT, seed_demo
from conftest import login, post, snapshot, token


EXPERIMENT = {"title": "Synthetic kinetics", "experiment_date": "2026-10-24", "status": "planned", "notes": "Synthetic test fixture"}
MEASUREMENT = {"name": "Signal", "value": "1.25", "unit": "AU", "measured_on": "2026-10-24"}


def read_csv(response):
    assert response.status_code == 200
    return list(csv.DictReader(io.StringIO(response.data.decode())))


def test_registration_login_logout(client, app):
    response = post(client, "/register", {"username": "new-user", "password": "a-long-password"})
    assert response.status_code == 302
    with sqlite3.connect(app.config["DATABASE"]) as db:
        hashed = db.execute("SELECT password_hash FROM users WHERE username='new-user'").fetchone()[0]
        assert hashed != "a-long-password" and check_password_hash(hashed, "a-long-password")
    assert post(client, "/login", {"username": "new-user", "password": "a-long-password"}).status_code == 302
    assert b"No experiments found" in client.get("/").data
    assert post(client, "/logout").status_code == 302
    assert client.get("/").location.endswith("/login")


@pytest.mark.parametrize("username,password", [("x", "long-password"), ("bad space", "long-password"), ("valid", "short"), ("valid", "x" * 129)])
def test_invalid_registration_no_mutation(client, app, username, password):
    before = snapshot(app)
    assert post(client, "/register", {"username": username, "password": password}).status_code == 400
    assert snapshot(app) == before


def test_duplicate_registration_no_mutation(client, app):
    before = snapshot(app)
    assert post(client, "/register", {"username": "demo", "password": "long-password"}).status_code == 409
    assert snapshot(app) == before


@pytest.mark.parametrize("username,password", [("demo", "wrong"), ("missing", "wrong"), ("' OR 1=1--", "wrong")])
def test_wrong_login(client, app, username, password):
    before = snapshot(app)
    assert post(client, "/login", {"username": username, "password": password}).status_code == 401
    assert client.get("/").status_code == 302
    assert snapshot(app) == before


@pytest.mark.parametrize("path", ["/", "/experiments/1", "/export.csv", "/attachments/1/download", "/experiments/new", "/experiments/1/edit"])
def test_authentication_required(client, path):
    assert client.get(path).location.endswith("/login")


@pytest.mark.parametrize("csrf", [None, "wrong", "非ASCII"])
def test_csrf_rejected_without_mutation(owner, app, csrf):
    before = snapshot(app)
    data = dict(EXPERIMENT)
    if csrf is not None:
        data["csrf_token"] = csrf
    assert owner.post("/experiments/new", data=data).status_code == 400
    assert snapshot(app) == before


def test_experiment_crud_and_cascade(owner, app):
    response = post(owner, "/experiments/new", EXPERIMENT)
    assert response.status_code == 302
    path = response.location
    assert b"Synthetic kinetics" in owner.get(path).data
    assert b"Edit experiment" in owner.get(path + "/edit").data
    assert post(owner, path + "/edit", {**EXPERIMENT, "title": "Updated title", "status": "completed"}).status_code == 302
    assert b"Updated title" in owner.get(path).data
    assert post(owner, path + "/samples", {"label": "NEW-1"}).status_code == 302
    with sqlite3.connect(app.config["DATABASE"]) as db:
        sample_id = db.execute("SELECT id FROM samples WHERE label='NEW-1'").fetchone()[0]
    assert post(owner, f"/samples/{sample_id}/measurements", MEASUREMENT).status_code == 302
    assert post(owner, path + "/attachments", {"file": (io.BytesIO(b"fixture"), "fixture.txt")}).status_code == 302
    assert post(owner, path + "/delete").status_code == 302
    assert owner.get(path).status_code == 404
    state = snapshot(app)
    assert [len(state[t]) for t in ("experiments", "samples", "measurements", "attachments")] == [3, 6, 12, 1]


@pytest.mark.parametrize("changed", [
    {"title": " "}, {"title": "x" * 201}, {"experiment_date": "2026-02-30"},
    {"experiment_date": "20261024"}, {"status": "unknown"}, {"notes": "x" * 10001},
])
def test_invalid_experiment_create_and_edit_are_atomic(owner, app, changed):
    before = snapshot(app)
    for path in ("/experiments/new", "/experiments/1/edit"):
        assert post(owner, path, {**EXPERIMENT, **changed}).status_code == 400
        assert snapshot(app) == before


@pytest.mark.parametrize("path", ["/experiments/3", "/experiments/3/edit", "/attachments/999/download"])
def test_foreign_or_missing_get_is_hidden(owner, path):
    assert owner.get(path).status_code == 404


@pytest.mark.parametrize("path,data", [
    ("/experiments/3/edit", EXPERIMENT),
    ("/experiments/3/delete", {}),
    ("/experiments/3/samples", {"label": "intrusion"}),
    ("/samples/5/measurements", MEASUREMENT),
    ("/samples/5/delete", {}),
    ("/experiments/3/attachments", {"file": None}),
])
def test_cross_user_writes_rejected_without_mutation(owner, app, path, data):
    before = snapshot(app)
    assert post(owner, path, data).status_code == 404
    assert snapshot(app) == before


@pytest.mark.parametrize("path", ["/experiments/1", "/attachments/1/download"])
def test_observer_cannot_read_owner_objects(client, path):
    login(client, "observer")
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/attachments/1/delete", "/measurements/1/delete", "/samples/1/delete"])
def test_observer_cannot_delete_owner_children(client, app, path):
    login(client, "observer")
    before = snapshot(app)
    assert post(client, path).status_code == 404
    assert snapshot(app) == before


@pytest.mark.parametrize("query,expected", [("buffer", 1), ("SYN-A1", 1), ("absorbance", 2), ("temperature labels", 1), ("%", 0), ("_", 0), ("' OR 1=1--", 0)])
def test_search(owner, query, expected):
    response = owner.get("/", query_string={"q": query})
    assert response.status_code == 200
    assert f"{expected} experiment(s)".encode() in response.data


def test_search_overlong_is_rejected(owner):
    assert owner.get("/", query_string={"q": "x" * 201}).status_code == 400


def test_csv_values_filtering_and_isolation(owner, client, app):
    response = owner.get("/export.csv")
    rows = read_csv(response)
    assert "attachment" in response.headers["Content-Disposition"]
    assert len(rows) == 12
    assert len(read_csv(owner.get("/export.csv?q=buffer"))) == 6
    assert {row["unit"] for row in rows} == {"AU"}
    assert {row["measured_on"] for row in rows} == {"2026-10-24"}
    with sqlite3.connect(app.config["DATABASE"]) as db:
        expected = db.execute("""SELECT s.label,m.name,m.value,m.unit,m.measured_on FROM measurements m
            JOIN samples s ON s.id=m.sample_id ORDER BY s.experiment_id DESC,s.id,m.id""").fetchall()
    assert [(r["sample"], r["measurement"], float(r["value"]), r["unit"], r["measured_on"]) for r in rows] == expected
    post(client, "/logout")
    login(client, "observer")
    assert read_csv(client.get("/export.csv")) == []
    assert b"0 experiment(s)" in client.get("/?q=buffer").data


@pytest.mark.parametrize("title", ["=1+1", "+cmd", "-formula", "@SUM(1)", "\t=1+1", "  =1+1"])
def test_csv_formula_text_is_neutralized(owner, title):
    assert post(owner, "/experiments/1/edit", {**EXPERIMENT, "title": title}).status_code == 302
    rows = read_csv(owner.get("/export.csv"))
    assert all(r["title"].startswith("'") for r in rows if r["experiment_id"] == "1")


def test_html_is_escaped(owner):
    assert post(owner, "/experiments/1/edit", {**EXPERIMENT, "title": "<script>alert(1)</script>"}).status_code == 302
    response = owner.get("/experiments/1")
    assert b"<script>" not in response.data and b"&lt;script&gt;" in response.data
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("changed", [{"value": "nan"}, {"value": "inf"}, {"value": "-inf"}, {"value": "1e9999"}, {"value": "bad"}, {"value": ""}, {"unit": ""}, {"name": ""}, {"measured_on": "2026-13-01"}])
def test_invalid_measurement_no_mutation(owner, app, changed):
    before = snapshot(app)
    assert post(owner, "/samples/1/measurements", {**MEASUREMENT, **changed}).status_code == 400
    assert snapshot(app) == before


def test_sample_and_measurement_deletion(owner, app):
    assert post(owner, "/samples/1/measurements", MEASUREMENT).status_code == 302
    with sqlite3.connect(app.config["DATABASE"]) as db:
        item_id = db.execute("SELECT max(id) FROM measurements").fetchone()[0]
    assert post(owner, f"/measurements/{item_id}/delete").status_code == 302
    assert len(snapshot(app)["measurements"]) == 12
    assert post(owner, "/samples/1/delete").status_code == 302
    assert len(snapshot(app)["samples"]) == 5
    assert len(snapshot(app)["measurements"]) == 9


@pytest.mark.parametrize("label,code", [("SYN-A1", 409), ("", 400), ("x" * 201, 400)])
def test_invalid_or_duplicate_sample_no_mutation(owner, app, label, code):
    before = snapshot(app)
    assert post(owner, "/experiments/1/samples", {"label": label}).status_code == code
    assert snapshot(app) == before


def test_attachment_roundtrip_and_delete(owner, app):
    payload = b"\x00\xffSynthetic byte fixture\r\n"
    assert post(owner, "/experiments/1/attachments", {"file": (io.BytesIO(payload), "../../fixture.bin")}).status_code == 302
    with sqlite3.connect(app.config["DATABASE"]) as db:
        item_id = db.execute("SELECT max(id) FROM attachments").fetchone()[0]
    response = owner.get(f"/attachments/{item_id}/download")
    assert response.data == payload
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert 'filename=fixture.bin' in response.headers["Content-Disposition"]
    assert post(owner, f"/attachments/{item_id}/delete").status_code == 302
    assert owner.get(f"/attachments/{item_id}/download").status_code == 404
    assert len(snapshot(app)["attachments"]) == 1
    assert owner.get("/attachments/1/download").data == ATTACHMENT


@pytest.mark.parametrize("filename,content", [("", b"abc"), ("empty.txt", b""), ("...", b"abc"), ("x" * 201, b"abc")])
def test_invalid_attachment_no_mutation(owner, app, filename, content):
    before = snapshot(app)
    assert post(owner, "/experiments/1/attachments", {"file": (io.BytesIO(content), filename)}).status_code == 400
    assert snapshot(app) == before


def test_oversized_request_no_mutation(owner, app):
    before = snapshot(app)
    assert post(owner, "/experiments/1/attachments", {"file": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "large.bin")}).status_code == 413
    assert snapshot(app) == before


def test_restart_persists_records_and_attachment(app):
    before = snapshot(app)
    restarted = create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATABASE": app.config["DATABASE"]})
    client = restarted.test_client()
    login(client)
    assert len(read_csv(client.get("/export.csv"))) == 12
    assert client.get("/attachments/1/download").data == ATTACHMENT
    assert snapshot(restarted) == before


def test_duplicate_demo_seed_is_atomic(app):
    before = snapshot(app)
    with sqlite3.connect(app.config["DATABASE"]) as db:
        with pytest.raises(ValueError, match="empty database"):
            seed_demo(db)
    assert snapshot(app) == before


def test_cli_seed_refuses_existing_database(app):
    before = snapshot(app)
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code == 1 and "existing data was not changed" in result.output
    assert snapshot(app) == before


def test_unknown_child_table_is_rejected(owner, app):
    before = snapshot(app)
    assert post(owner, "/users/1/delete").status_code == 404
    assert snapshot(app) == before


def test_login_rotates_csrf(owner):
    old_token = token(owner)
    assert post(owner, "/login", {"username": "demo", "password": "synthetic-demo-only"}).status_code == 302
    assert token(owner) != old_token
    assert owner.post("/experiments/new", data={**EXPERIMENT, "csrf_token": old_token}).status_code == 400
