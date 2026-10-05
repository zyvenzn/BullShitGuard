-- No secrets, seed phrases, keys or credentials are ever stored here.
CREATE TABLE users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    join_date   INTEGER,              -- unix seconds, NULL = joined before the bot saw them
    last_seen   INTEGER,
    warnings    INTEGER NOT NULL DEFAULT 0,
    is_banned   INTEGER NOT NULL DEFAULT 0,
    is_muted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_users_username ON users (lower(username));

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE mod_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             INTEGER NOT NULL,
    admin_id       INTEGER,           -- NULL = automatic action by the bot
    target_user_id INTEGER,
    action         TEXT NOT NULL,
    reason         TEXT
);
CREATE INDEX idx_mod_logs_target ON mod_logs (target_user_id);

CREATE TABLE daily_stats (
    day         TEXT PRIMARY KEY,     -- UTC date YYYY-MM-DD
    messages    INTEGER NOT NULL DEFAULT 0,
    new_members INTEGER NOT NULL DEFAULT 0,
    warnings    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pending_verification (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    message_id INTEGER,
    deadline   INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
