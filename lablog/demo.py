"""Deterministic software fixtures, not laboratory observations."""

from werkzeug.security import generate_password_hash

DEMO_PASSWORD = "synthetic-demo-only"
ATTACHMENT = b"SYNTHETIC DEMO ONLY\nThese are software fixtures, not experimental findings.\n"
TABLES = ("users", "experiments", "samples", "measurements", "attachments")


def counts(db):
    return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def seed_demo(db):
    # The empty check and all inserts share one write transaction.
    try:
        db.execute("BEGIN IMMEDIATE")
        if any(counts(db).values()):
            raise ValueError("Demo requires an empty database; existing data was not changed.")
        owner = db.execute("INSERT INTO users(username, password_hash) VALUES (?, ?)",
                           ("demo", generate_password_hash(DEMO_PASSWORD))).lastrowid
        other = db.execute("INSERT INTO users(username, password_hash) VALUES (?, ?)",
                           ("observer", generate_password_hash(DEMO_PASSWORD))).lastrowid
        fixtures = [
            (owner, "Synthetic buffer screen", "completed", "SYNTHETIC: deterministic buffer fixtures for app demonstration."),
            (owner, "Synthetic temperature series", "in progress", "SYNTHETIC: temperature labels exercise sample tracking."),
            (other, "Synthetic observer notebook", "planned", "SYNTHETIC: separate account used to demonstrate owner isolation."),
        ]
        first_id = None
        for index, (user, title, status, notes) in enumerate(fixtures):
            experiment_id = db.execute("INSERT INTO experiments(owner_id, title, experiment_date, status, notes) VALUES (?, ?, ?, ?, ?)",
                                       (user, title, "2026-10-24", status, notes)).lastrowid
            if first_id is None:
                first_id = experiment_id
            for sample_index in range(2):
                label = f"SYN-{'ABC'[index]}{sample_index + 1}"
                sample_id = db.execute("INSERT INTO samples(experiment_id, label, description) VALUES (?, ?, ?)",
                                       (experiment_id, label, "Synthetic software fixture; no real specimen.")).lastrowid
                if index < 2:
                    for measurement_index in range(3):
                        # Formula defines arbitrary test inputs, not measured data.
                        value = round((index + 1) * 0.1 + sample_index * 0.02 + measurement_index * 0.01, 2)
                        db.execute("INSERT INTO measurements(sample_id, name, value, unit, measured_on) VALUES (?, ?, ?, ?, ?)",
                                   (sample_id, f"Synthetic absorbance replicate {measurement_index + 1}", value, "AU", "2026-10-24"))
        db.execute("INSERT INTO attachments(experiment_id, filename, content) VALUES (?, ?, ?)",
                   (first_id, "synthetic-protocol.txt", ATTACHMENT))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts(db)
