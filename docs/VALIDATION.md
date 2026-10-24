# Validation record

Executed locally on 2026-10-24 with Python 3.11.15 in `.venv`.

- `python -m pytest -q --junitxml=/tmp/lablog-test-results.xml`:
  **79 passed**, **0 failures**, **0 errors**, reported duration **19.18 seconds**.
- `python scripts/verify_demo.py --output examples`: exited successfully after
  exercising real loopback HTTP requests and restarting the server against the
  same file-backed SQLite database. See `examples/acceptance.json` for numerical
  evidence. It verifies the existence of **3 expected / 3 actual** artifacts.
- Expected/actual database counts: **2/2 users, 3/3 experiments, 6/6 samples,
  12/12 measurements, 1/1 attachments**. Restart preserves these counts.
- Rejected writes in the pytest suite are checked against full before/after
  snapshots, including rejected cross-user writes and invalid uploads. Demo
  re-seeding is also checked for no partial changes.

The source of truth for remote CI is the GitHub Actions run for the pushed commit,
not this local record. CI uploads JUnit XML and regenerated HTTP demo artifacts for
each Python matrix entry. No claim about remote CI is inferred from local tests.
