"""SQLite storage (stdlib only). All public methods are async and thread-offloaded.

SQLite is plenty for one community group. The schema is plain SQL in
migrations/, so moving to PostgreSQL later is straightforward.
"""
from __future__ import annotations

import asyncio
import functools
import sqlite3
import threading
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_STAT_FIELDS = {"messages", "new_members", "warnings"}


def _threaded(fn):
    @functools.wraps(fn)
    async def wrapper(self: "Database", *a: Any, **kw: Any):
        def run():
            with self._lock:
                return fn(self, *a, **kw)
        return await asyncio.to_thread(run)
    return wrapper


class Database:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle
    @_threaded
    def init(self) -> None:
        c = self._conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                continue
            c.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") + "\nCOMMIT;")
            c.execute("INSERT INTO schema_migrations(name) VALUES (?)", (f.name,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- users
    @_threaded
    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    now: int, joined: bool = False) -> None:
        self._conn.execute(
            """INSERT INTO users(user_id, username, first_name, join_date, last_seen)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name,
                 last_seen=excluded.last_seen,
                 join_date=CASE WHEN ? THEN excluded.join_date ELSE users.join_date END""",
            (user_id, username, first_name, now if joined else None, now, 1 if joined else 0),
        )

    @_threaded
    def record_message(self, user_id: int, username: str | None, first_name: str | None,
                       now: int, day: str) -> int | None:
        """Touch user + bump today's message count. Returns the user's join_date (or None)."""
        self._conn.execute(
            """INSERT INTO users(user_id, username, first_name, last_seen) VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen""",
            (user_id, username, first_name, now),
        )
        self._conn.execute(
            """INSERT INTO daily_stats(day, messages) VALUES (?,1)
               ON CONFLICT(day) DO UPDATE SET messages=messages+1""",
            (day,),
        )
        row = self._conn.execute("SELECT join_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["join_date"] if row else None

    @_threaded
    def get_user(self, user_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    @_threaded
    def find_user_by_username(self, username: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?) ORDER BY last_seen DESC LIMIT 1",
            (username.lstrip("@"),),
        ).fetchone()
        return dict(row) if row else None

    @_threaded
    def set_flags(self, user_id: int, banned: bool | None = None, muted: bool | None = None) -> None:
        self._conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        if banned is not None:
            self._conn.execute("UPDATE users SET is_banned=? WHERE user_id=?", (int(banned), user_id))
        if muted is not None:
            self._conn.execute("UPDATE users SET is_muted=? WHERE user_id=?", (int(muted), user_id))

    # ------------------------------------------------------------- warnings
    @_threaded
    def add_warning(self, user_id: int, day: str) -> int:
        self._conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        self._conn.execute("UPDATE users SET warnings=warnings+1 WHERE user_id=?", (user_id,))
        self._conn.execute(
            """INSERT INTO daily_stats(day, warnings) VALUES (?,1)
               ON CONFLICT(day) DO UPDATE SET warnings=warnings+1""",
            (day,),
        )
        return self._conn.execute("SELECT warnings FROM users WHERE user_id=?", (user_id,)).fetchone()["warnings"]

    @_threaded
    def get_warnings(self, user_id: int) -> int:
        row = self._conn.execute("SELECT warnings FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["warnings"] if row else 0

    @_threaded
    def clear_warnings(self, user_id: int) -> None:
        self._conn.execute("UPDATE users SET warnings=0 WHERE user_id=?", (user_id,))

    # ------------------------------------------------------------- settings
    @_threaded
    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    @_threaded
    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @_threaded
    def del_setting(self, key: str) -> None:
        self._conn.execute("DELETE FROM settings WHERE key=?", (key,))

    @_threaded
    def all_settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM settings")}

    # ------------------------------------------------------------ mod logs
    @_threaded
    def log_mod(self, ts: int, admin_id: int | None, target_user_id: int | None, action: str,
                reason: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO mod_logs(ts, admin_id, target_user_id, action, reason) VALUES (?,?,?,?,?)",
            (ts, admin_id, target_user_id, action, (reason or "")[:300]),
        )

    @_threaded
    def recent_logs(self, target_user_id: int, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM mod_logs WHERE target_user_id=? ORDER BY id DESC LIMIT ?", (target_user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- stats
    @_threaded
    def bump(self, day: str, field: str, n: int = 1) -> None:
        if field not in _STAT_FIELDS:
            raise ValueError("unknown stat field")
        self._conn.execute(
            f"INSERT INTO daily_stats(day, {field}) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET {field}={field}+?",
            (day, n, n),
        )

    @_threaded
    def get_stats(self, day: str) -> dict:
        row = self._conn.execute("SELECT * FROM daily_stats WHERE day=?", (day,)).fetchone()
        return dict(row) if row else {"day": day, "messages": 0, "new_members": 0, "warnings": 0}

    # --------------------------------------------------------- verification
    @_threaded
    def add_pending(self, chat_id: int, user_id: int, message_id: int | None, deadline: int) -> None:
        self._conn.execute(
            """INSERT INTO pending_verification(chat_id,user_id,message_id,deadline) VALUES (?,?,?,?)
               ON CONFLICT(chat_id,user_id) DO UPDATE SET message_id=excluded.message_id, deadline=excluded.deadline""",
            (chat_id, user_id, message_id, deadline),
        )

    @_threaded
    def pop_pending(self, chat_id: int, user_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pending_verification WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()
        if row:
            self._conn.execute("DELETE FROM pending_verification WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return dict(row) if row else None

    @_threaded
    def due_pending(self, now: int) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pending_verification WHERE deadline<=?", (now,)).fetchall()
        return [dict(r) for r in rows]
