"""Local experiment notebook. Run with flask --app lablog run."""

import csv
from datetime import date
from functools import wraps
import hmac
import io
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3

import click
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, send_file,
    session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(g.app_database, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("LABLOG_DATABASE", str(Path(app.instance_path) / "lablog.sqlite3")),
        SECRET_KEY=os.environ.get("LABLOG_SECRET_KEY"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        key_path = Path(app.instance_path) / "secret.key"
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_hex(32))
        app.config["SECRET_KEY"] = key_path.read_text()

    @app.before_request
    def prepare_request():
        g.app_database = app.config["DATABASE"]
        g.user = None
        if session.get("user_id"):
            g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if request.method == "POST":
            expected = session.get("csrf_token", "")
            supplied = request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
                abort(400, "Invalid CSRF token. Reload the form and retry.")

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop("db", None)
        if db:
            db.close()

    @app.context_processor
    def csrf_context():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf_token"]}

    with app.app_context():
        g.app_database = app.config["DATABASE"]
        get_db().executescript(Path(__file__).with_name("schema.sql").read_text())

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def owned_experiment(experiment_id):
        experiment = get_db().execute(
            "SELECT * FROM experiments WHERE id = ? AND owner_id = ?",
            (experiment_id, g.user["id"]),
        ).fetchone()
        if experiment is None:
            abort(404)
        return experiment

    def owned_child(table, item_id):
        # Table names are internal constants, never request data.
        join = ("JOIN samples s ON c.sample_id = s.id JOIN experiments e ON s.experiment_id = e.id"
                if table == "measurements" else "JOIN experiments e ON c.experiment_id = e.id")
        row = get_db().execute(
            f"SELECT c.*, e.id AS parent_id FROM {table} c {join} WHERE c.id = ? AND e.owner_id = ?",
            (item_id, g.user["id"]),
        ).fetchone()
        if row is None:
            abort(404)
        return row

    def field(name, max_length=200, required=True):
        value = request.form.get(name, "").strip()
        if (required and not value) or len(value) > max_length:
            abort(400, f"{name}: required, at most {max_length} characters." if required
                  else f"{name}: at most {max_length} characters.")
        return value

    def iso_date(name):
        value = field(name, 10)
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
        except ValueError:
            abort(400, f"{name}: use a valid YYYY-MM-DD date.")
        return value

    def experiment_fields():
        title = field("title")
        day = iso_date("experiment_date")
        status = field("status", 20)
        if status not in ("planned", "in progress", "completed"):
            abort(400, "Unknown status.")
        return title, day, status, field("notes", 10000, required=False)

    def experiment_list():
        query = request.args.get("q", "").strip()
        if len(query) > 200:
            abort(400, "Search is limited to 200 characters.")
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = get_db().execute(r"""
            SELECT e.*,
              (SELECT COUNT(*) FROM samples s WHERE s.experiment_id=e.id) sample_count,
              (SELECT COUNT(*) FROM measurements m JOIN samples s ON m.sample_id=s.id
                WHERE s.experiment_id=e.id) measurement_count
            FROM experiments e WHERE e.owner_id = ? AND (
              e.title LIKE ? ESCAPE '\' OR e.notes LIKE ? ESCAPE '\' OR
              EXISTS (SELECT 1 FROM samples s WHERE s.experiment_id=e.id AND
                (s.label LIKE ? ESCAPE '\' OR s.description LIKE ? ESCAPE '\')) OR
              EXISTS (SELECT 1 FROM measurements m JOIN samples s ON m.sample_id=s.id
                WHERE s.experiment_id=e.id AND m.name LIKE ? ESCAPE '\'))
            ORDER BY e.experiment_date DESC, e.id DESC
        """, (g.user["id"], pattern, pattern, pattern, pattern, pattern)).fetchall()
        return query, rows

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = field("username", 40)
            password = request.form.get("password", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username) or not 10 <= len(password) <= 128:
                abort(400, "Use a 3–40 character username (letters, digits, _, ., -) and a 10–128 character password.")
            try:
                with get_db() as db:
                    db.execute("INSERT INTO users(username, password_hash) VALUES (?, ?)",
                               (username, generate_password_hash(password)))
            except sqlite3.IntegrityError:
                abort(409, "Username already exists.")
            flash("Account created. Please sign in.")
            return redirect(url_for("login"))
        return render_template("auth.html", registering=True)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = get_db().execute("SELECT * FROM users WHERE username = ?", (request.form.get("username", ""),)).fetchone()
            if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
                abort(401, "Invalid username or password.")
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        return render_template("auth.html", registering=False)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        query, experiments = experiment_list()
        return render_template("index.html", experiments=experiments, query=query)

    @app.route("/experiments/new", methods=["GET", "POST"])
    @login_required
    def new_experiment():
        if request.method == "POST":
            values = experiment_fields()
            with get_db() as db:
                cur = db.execute("INSERT INTO experiments(owner_id, title, experiment_date, status, notes) VALUES (?, ?, ?, ?, ?)",
                                 (g.user["id"], *values))
            return redirect(url_for("detail", experiment_id=cur.lastrowid))
        return render_template("experiment_form.html", experiment=None)

    @app.get("/experiments/<int:experiment_id>")
    @login_required
    def detail(experiment_id):
        experiment = owned_experiment(experiment_id)
        samples = get_db().execute("SELECT * FROM samples WHERE experiment_id = ? ORDER BY id", (experiment_id,)).fetchall()
        measurements = get_db().execute("""SELECT m.*, s.label FROM measurements m
            JOIN samples s ON m.sample_id = s.id WHERE s.experiment_id = ? ORDER BY m.id""", (experiment_id,)).fetchall()
        attachments = get_db().execute("SELECT id, filename, length(content) AS size FROM attachments WHERE experiment_id = ? ORDER BY id", (experiment_id,)).fetchall()
        return render_template("detail.html", experiment=experiment, samples=samples,
                               measurements=measurements, attachments=attachments)

    @app.route("/experiments/<int:experiment_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_experiment(experiment_id):
        experiment = owned_experiment(experiment_id)
        if request.method == "POST":
            values = experiment_fields()
            with get_db() as db:
                db.execute("UPDATE experiments SET title=?, experiment_date=?, status=?, notes=? WHERE id=?", (*values, experiment_id))
            return redirect(url_for("detail", experiment_id=experiment_id))
        return render_template("experiment_form.html", experiment=experiment)

    @app.post("/experiments/<int:experiment_id>/delete")
    @login_required
    def delete_experiment(experiment_id):
        owned_experiment(experiment_id)
        with get_db() as db:
            db.execute("DELETE FROM experiments WHERE id=?", (experiment_id,))
        flash("Experiment and its child records deleted.")
        return redirect(url_for("index"))

    @app.post("/experiments/<int:experiment_id>/samples")
    @login_required
    def add_sample(experiment_id):
        owned_experiment(experiment_id)
        label, description = field("label"), field("description", 2000, required=False)
        try:
            with get_db() as db:
                db.execute("INSERT INTO samples(experiment_id, label, description) VALUES (?, ?, ?)", (experiment_id, label, description))
        except sqlite3.IntegrityError:
            abort(409, "Sample labels must be unique within an experiment.")
        return redirect(url_for("detail", experiment_id=experiment_id))

    @app.post("/samples/<int:sample_id>/measurements")
    @login_required
    def add_measurement(sample_id):
        sample = owned_child("samples", sample_id)
        name, unit, day = field("name"), field("unit", 40), iso_date("measured_on")
        try:
            value = float(request.form.get("value", ""))
            if not math.isfinite(value):
                raise ValueError
        except (ValueError, OverflowError):
            abort(400, "value: enter a finite number.")
        with get_db() as db:
            db.execute("INSERT INTO measurements(sample_id, name, value, unit, measured_on) VALUES (?, ?, ?, ?, ?)",
                       (sample_id, name, value, unit, day))
        return redirect(url_for("detail", experiment_id=sample["parent_id"]))

    @app.post("/experiments/<int:experiment_id>/attachments")
    @login_required
    def add_attachment(experiment_id):
        owned_experiment(experiment_id)
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            abort(400, "Choose a non-empty file.")
        filename = secure_filename(uploaded.filename)
        content = uploaded.read()
        if not filename or len(filename) > 200 or not content:
            abort(400, "A non-empty file with a valid filename (up to 200 characters) is required.")
        with get_db() as db:
            db.execute("INSERT INTO attachments(experiment_id, filename, content) VALUES (?, ?, ?)", (experiment_id, filename, content))
        return redirect(url_for("detail", experiment_id=experiment_id))

    @app.get("/attachments/<int:item_id>/download")
    @login_required
    def download_attachment(item_id):
        item = owned_child("attachments", item_id)
        return send_file(io.BytesIO(item["content"]), mimetype="application/octet-stream",
                         as_attachment=True, download_name=item["filename"])

    @app.post("/<table>/<int:item_id>/delete")
    @login_required
    def delete_child(table, item_id):
        if table not in ("samples", "measurements", "attachments"):
            abort(404)
        item = owned_child(table, item_id)
        with get_db() as db:
            db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        return redirect(url_for("detail", experiment_id=item["parent_id"]))

    @app.get("/export.csv")
    @login_required
    def export_csv():
        _, experiments = experiment_list()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["experiment_id", "title", "experiment_date", "status", "notes", "sample", "sample_description", "measurement", "value", "unit", "measured_on"])
        for experiment in experiments:
            rows = get_db().execute("""SELECT s.label, s.description, m.name, m.value, m.unit, m.measured_on
                FROM measurements m JOIN samples s ON m.sample_id=s.id WHERE s.experiment_id=? ORDER BY s.id, m.id""",
                                    (experiment["id"],)).fetchall()
            for row in rows:
                writer.writerow([experiment["id"], *[csv_safe(experiment[k]) for k in ("title", "experiment_date", "status", "notes")],
                                 csv_safe(row["label"]), csv_safe(row["description"]), csv_safe(row["name"]), row["value"], csv_safe(row["unit"]), row["measured_on"]])
        return app.response_class(output.getvalue(), mimetype="text/csv",
                                  headers={"Content-Disposition": 'attachment; filename="measurements.csv"'})

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    def error_page(error):
        return render_template("error.html", error=error), error.code

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Insert labelled synthetic data into an empty database."""
        from .demo import seed_demo
        g.app_database = app.config["DATABASE"]
        try:
            counts = seed_demo(get_db())
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(str(counts))

    return app


def csv_safe(value):
    """Neutralize formula-like text when opened in spreadsheet software."""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text
