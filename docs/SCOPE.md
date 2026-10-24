# P19 scope and acceptance criteria

Date: 2026-10-24. Delivery budget: one working day.

## Question

Can a small multi-user web application keep experiments, samples, numerical
measurements and file attachments together, with authentication and ownership
checks, while supporting search, portable exports and durable local storage?

## Implementation boundary

Build a local Flask application with server-rendered HTML and SQLite. Provide
registration/login/logout, experiment create/read/update/delete, sample and
measurement creation/deletion, owner-only attachment upload/download/deletion,
search and CSV export. Use explicit units, finite numerical values and ISO dates.
Store records and attachment bytes in the same transactional database. The demo
uses explicitly labelled synthetic records only; its values are software fixtures,
not experimental findings. No thesis, ligand or homelab information is used.

## Acceptance criteria (targets, not measured results)

1. A fresh demo contains exactly 2 users, 3 experiments, 6 samples, 12 measurements
   and 1 attachment. A second demo invocation refuses to duplicate records.
2. Authenticated users can create, view, edit and delete experiments; add/delete
   samples and measurements; upload, download and delete an attachment. The owner
   can download the uploaded bytes unchanged. Deletion cascades to child records.
3. A search for `buffer` returns exactly 1 experiment for the demo owner and none
   for the other user. Search includes experiment titles/notes, sample labels and
   measurement names, and treats SQL wildcard characters literally.
4. The owner's CSV contains exactly 12 measurement rows and the other user's CSV
   contains 0 rows. Filtered CSV uses the same search and ownership rules. Values,
   units, dates and sample labels survive a CSV round trip.
5. Reopening the same database preserves all 3 experiments and 12 measurements.
6. At least 20 pytest cases pass, covering the live request path, ownership,
   invalid input, CSRF, export safety, persistence and attachment byte integrity.
   Rejected writes leave the relevant database counts unchanged.
7. A reproducible demo verifier writes 3 reviewable artifacts: a JSON acceptance
   report, an owner CSV and an authenticated HTML page. CI runs pytest and the
   demo verifier on Python 3.11 and 3.12 and uploads these artifacts.

## Explicit exclusions

Public/production deployment, shared editing, roles/admin tools, audit history,
password reset, rate limiting, malware scanning, regulatory validation, automated
backups and schema migrations are **not done**. This is a local portfolio app,
not an ELN certified for laboratory or clinical use. Uploaded files are downloaded
as attachments and are not rendered. Demo passwords are public fixtures.
