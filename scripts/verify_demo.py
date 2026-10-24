"""Exercise a real HTTP server, restart it, and save reproducible evidence."""

import argparse
import csv
import hashlib
import http.cookiejar
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import urllib.parse
import urllib.request

from werkzeug.serving import make_server
from lablog import create_app
from lablog.demo import ATTACHMENT, DEMO_PASSWORD, counts, seed_demo


def serve(app):
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def stop(server, thread):
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    assert not thread.is_alive()


def client(base, username):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    html = opener.open(base + "/login").read().decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
    data = urllib.parse.urlencode({"username": username, "password": DEMO_PASSWORD, "csrf_token": token}).encode()
    response = opener.open(base + "/login", data=data)
    assert response.status == 200
    return opener


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lablog-demo-") as temp:
        db_path = str(Path(temp) / "demo.sqlite3")
        config = {"DATABASE": db_path, "SECRET_KEY": "demo-verifier-only"}
        app = create_app(config)
        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA foreign_keys = ON")
            actual = seed_demo(db)
            expected = dict(users=2, experiments=3, samples=6, measurements=12, attachments=1)
            assert actual == expected
            try:
                seed_demo(db)
            except ValueError:
                pass
            else:
                raise AssertionError("Duplicate demo invocation was accepted")
            assert counts(db) == actual
        server, thread, base = serve(app)
        try:
            owner = client(base, "demo")
            observer = client(base, "observer")
            html = owner.open(base + "/").read().decode()
            assert "2 experiment(s)" in html
            search = owner.open(base + "/?q=buffer").read().decode()
            observer_search = observer.open(base + "/?q=buffer").read().decode()
            assert "1 experiment(s)" in search and "0 experiment(s)" in observer_search
            exported = owner.open(base + "/export.csv").read()
            rows = list(csv.DictReader(io.StringIO(exported.decode())))
            other_rows = list(csv.DictReader(io.StringIO(observer.open(base + "/export.csv").read().decode())))
            filtered = list(csv.DictReader(io.StringIO(owner.open(base + "/export.csv?q=buffer").read().decode())))
            assert len(rows) == 12 and len(other_rows) == 0 and len(filtered) == 6
            with sqlite3.connect(db_path) as db:
                db.row_factory = sqlite3.Row
                expected_rows = db.execute("""SELECT s.label, m.name, m.value, m.unit, m.measured_on
                    FROM measurements m JOIN samples s ON m.sample_id=s.id
                    JOIN experiments e ON e.id=s.experiment_id WHERE e.owner_id=1
                    ORDER BY e.experiment_date DESC, e.id DESC, s.id, m.id""").fetchall()
                for row, saved in zip(rows, expected_rows, strict=True):
                    assert (row["sample"], row["measurement"], float(row["value"]), row["unit"], row["measured_on"]) == tuple(saved)
            downloaded = owner.open(base + "/attachments/1/download").read()
            assert downloaded == ATTACHMENT
            page = owner.open(base + "/experiments/1").read().decode()
            # Make the saved page self-contained and omit the ephemeral CSRF value.
            page = re.sub(r'name="csrf_token" value="[^"]+"', 'name="csrf_token" value="OFFLINE-SNAPSHOT"', page)
            css = (Path(__file__).parents[1] / "lablog/static/style.css").read_text()
            page = page.replace('<link rel="stylesheet" href="/static/style.css">', f"<style>{css}</style>")
        finally:
            stop(server, thread)
        # Fresh factory + fresh HTTP server against the same file, not an open connection.
        restarted = create_app(config)
        server, thread, base = serve(restarted)
        try:
            owner = client(base, "demo")
            persisted_rows = list(csv.DictReader(io.StringIO(owner.open(base + "/export.csv").read().decode())))
            assert len(persisted_rows) == 12
            with sqlite3.connect(db_path) as db:
                reopened_counts = counts(db)
                assert reopened_counts == expected
        finally:
            stop(server, thread)
        (output / "owner-measurements.csv").write_bytes(exported)
        (output / "experiment.html").write_text(page)
        report = {
            "data_kind": "synthetic software fixtures; not experimental findings",
            "transport": "HTTP over loopback; server restarted against same SQLite file",
            "counts_expected": expected,
            "counts_actual": actual,
            "duplicate_seed_refused_without_mutation": True,
            "owner_buffer_search_experiments": 1,
            "observer_buffer_search_experiments": 0,
            "owner_csv_rows": len(rows),
            "observer_csv_rows": len(other_rows),
            "filtered_csv_rows": len(filtered),
            "csv_values_units_dates_labels_match_database": True,
            "attachment_download_bytes": len(downloaded),
            "attachment_sha256": hashlib.sha256(downloaded).hexdigest(),
            "counts_after_restart": reopened_counts,
            "measurement_rows_after_restart": len(persisted_rows),
            "artifacts_expected": 3,
            "artifacts": ["acceptance.json", "owner-measurements.csv", "experiment.html"],
        }
        (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        assert all((output / name).is_file() for name in report["artifacts"])
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("examples"))
    verify(parser.parse_args().output)
