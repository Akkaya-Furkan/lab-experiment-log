PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    experiment_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('planned', 'in progress', 'completed')),
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS experiments_owner ON experiments(owner_id);
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(experiment_id, label)
);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    measured_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content BLOB NOT NULL
);
