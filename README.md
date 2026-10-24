# Lab experiment log

A local web notebook for owner-isolated experiments, samples, measurements and
file attachments. Built with Python, Flask and SQLite.

## Question

Can a small multi-user application record experiments with authentication and
attachments, while keeping sample-level measurements searchable, exportable and
persistent? The one-day implementation boundary and numerical acceptance targets
are in [docs/SCOPE.md](docs/SCOPE.md).

## Approach

Each account owns its experiments. An experiment contains labelled samples;
each sample contains named numerical measurements with explicit units and dates.
Attachments belong to an experiment. Every detail, mutation, download, search and
export checks the authenticated owner. Experiments support create/read/edit/delete;
samples, measurements and attachments support add/read/delete.

SQLite stores both records and attachment bytes. Foreign keys cascade deletions
and transactions keep rejected writes from leaving partial records. Passwords use
Werkzeug's salted password hashes, forms use session-bound CSRF tokens, and HTML
is escaped. SQL values are parameterized. No external services are needed.

### Run locally

Use Python 3.11 or 3.12 and a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m flask --app lablog seed-demo
python -m flask --app lablog run --host 127.0.0.1 --port 5000
```

Open <http://127.0.0.1:5000>. Demo accounts are `demo` and `observer`; both use
`synthetic-demo-only`. Alternatively, skip `seed-demo` and register an account in
the browser. Seeding refuses a non-empty database without changing its contents.

1. Sign in and open an experiment, or choose **New experiment**.
2. Add a sample with a label unique within that experiment.
3. Enter a measurement name, a finite number, a unit and a `YYYY-MM-DD` date.
4. Upload a non-empty file or download an existing attachment.
5. Search the experiment list and choose **Export CSV** for the current results.

The default database is `instance/lablog.sqlite3`. The local session signing key
is generated once in `instance/secret.key`. Both are ignored by Git. Restarting
the app preserves the database and login key. To use a separate database, set
`LABLOG_DATABASE` to an absolute path in an existing directory. Set
`LABLOG_SECRET_KEY` to provide a signing key explicitly.

### Search and export semantics

Search matches experiment titles/notes, sample labels/descriptions and measurement
names. `%` and `_` are literal search characters. SQLite's default `LIKE` handles
ASCII case-insensitive matching; full Unicode case folding is not implemented.
Search selects whole experiments, so a matching sample returns all measurements
from its experiment in the CSV. Empty experiments and samples without measurements
produce no CSV data rows. The export includes experiment ID/title/date/status/notes,
sample label/description, measurement name/value/unit/date.

Formula-like text is prefixed with an apostrophe in CSV to reduce spreadsheet
formula execution risk; this deliberately changes those text fields. Numerical
measurement values remain numeric. CSV is a measurement export, not a complete
backup of users, empty records or attachment bytes.

## Results

The reproducible demo uses **synthetic software fixtures only**. Its arbitrary
values are defined by a formula in [lablog/demo.py](lablog/demo.py); they are not
laboratory observations, scientific conclusions or performance benchmarks.
No thesis, ligand or homelab data is included.

Local verification on Python 3.11.15 produced:

| Check | Target | Observed |
|---|---:|---:|
| Users | 2 | 2 |
| Experiments | 3 | 3 |
| Samples | 6 | 6 |
| Measurements | 12 | 12 |
| Attachments | 1 | 1 |
| Owner search results for `buffer` | 1 | 1 |
| Other user's search results for `buffer` | 0 | 0 |
| Owner CSV measurement rows | 12 | 12 |
| Other user's CSV measurement rows | 0 | 0 |
| Filtered owner CSV rows (`buffer`) | 6 | 6 |
| Measurements after HTTP server restart | 12 | 12 |
| Reviewable demo artifacts | 3 | 3 |
| Passing pytest cases | ≥20 | 79 |

The demo verifier starts a loopback HTTP server, logs into both accounts, exercises
search/export/download, stops the server and starts a fresh app against the same
SQLite file. CSV labels, values, units and dates match the database. The downloaded
attachment matches all **76 bytes**, with SHA-256
`2dc211949646a98eef6ac24b0d88d44075d004306df01b8362af6c6f6d727fdc`.
Duplicate seeding is refused and the stored record counts remain unchanged.

Review the generated outputs:

- [Acceptance report](examples/acceptance.json): expected/actual counts and checks.
- [Measurement CSV](examples/owner-measurements.csv): synthetic owner export.
- [Experiment page](examples/experiment.html): self-contained authenticated HTML
  snapshot; download and open locally for the styled view. Its forms are offline
  examples and its CSRF token has been replaced.

Reproduce the checks:

```bash
source .venv/bin/activate
python -m pytest -q
python scripts/verify_demo.py --output examples
```

The pytest suite covers experiment CRUD and cascading deletions, authentication,
owner isolation, CSV values and formula escaping, search, persistent records,
attachment byte integrity, HTML escaping, CSRF and invalid/oversized inputs.
Rejected mutations are compared against full database snapshots.
[GitHub Actions CI](https://github.com/Akkaya-Furkan/lab-experiment-log/actions/workflows/ci.yml)
runs pytest and the HTTP demo verifier on Python 3.11 and 3.12; each job uploads
its JUnit report and demo artifacts.

## Limitations

- Public/production deployment: **not done**. Run locally using the instructions
  above; no deployed service is claimed.
- Shared editing, roles/admin tools and audit/version history: **not done**.
  Accounts have separate notebooks. Samples and measurements can be deleted and
  re-added; in-place editing of these child records is **not done**.
- Password reset, login rate limiting and a production HTTPS/authentication review:
  **not done**. Demo credentials are intentionally public. The development server
  is bound to loopback in the documented command.
- Malware scanning and attachment preview: **not done**. Uploads are downloaded as
  binary attachments. The complete upload request is limited to 2 MiB, including
  multipart form overhead; attachment storage is inside SQLite.
- Automated backups, complete notebook import/export and schema migrations:
  **not done**. With the app stopped, preserve the database file for a local backup.
- Unit conversion, uncertainty modelling, scientific validation, regulatory
  certification and laboratory/clinical use validation: **not done**. Units are
  free text, dates have day precision, and values are finite floating-point numbers.
