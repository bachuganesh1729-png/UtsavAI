"""
services/database_service.py
─────────────────────────────
SQLite persistence layer for UtsavAI.

Responsibilities:
- Create and migrate the database schema on first run.
- Provide parameterized CRUD operations for all four tables:
    events, budget_items, vendors, timeline_tasks
- Return typed dicts; never expose raw sqlite3 objects to callers.
- Log errors without exposing internal query details to the UI.

Design decisions:
- WAL mode: better concurrent read performance for Streamlit reruns.
- Row factory: sqlite3.Row → dict conversion for clean return types.
- Foreign key enforcement: enabled per connection.
- All queries use parameterized placeholders (?), never f-strings or % formatting.

Layer contract: services/ may import from utils/ and the standard library.
                services/ must NOT import from modules/ or streamlit.

⚠️  Streamlit Community Cloud persistence warning:
    SQLite files written to the app's ephemeral filesystem will be lost on
    restart or redeploy. This service is fully functional for local use.
    For Cloud deployments, consider a persistent backend (e.g., Supabase).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from utils.config import DB_PATH

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    location     TEXT,
    event_date   TEXT    NOT NULL,
    guest_count  INTEGER NOT NULL,
    total_budget REAL    NOT NULL,
    preferences  TEXT,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    category         TEXT    NOT NULL,
    allocated_amount REAL    NOT NULL DEFAULT 0.0,
    actual_amount    REAL    NOT NULL DEFAULT 0.0,
    notes            TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vendors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   INTEGER NOT NULL,
    category   TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    contact    TEXT,
    status     TEXT    NOT NULL DEFAULT 'pending',
    notes      TEXT,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timeline_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   INTEGER NOT NULL,
    task       TEXT    NOT NULL,
    deadline   TEXT    NOT NULL,
    priority   TEXT    NOT NULL DEFAULT 'medium',
    status     TEXT    NOT NULL DEFAULT 'pending',
    notes      TEXT,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);
"""


# ── Connection helper ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that opens a WAL-mode SQLite connection and ensures
    foreign keys are enabled. Commits on clean exit; rolls back on error.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("Database error (rolled back): %s", exc)
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


# ── Initialisation ────────────────────────────────────────────────────────────

def initialize_database() -> bool:
    """
    Create all tables if they do not already exist.

    Returns:
        True on success, False on failure.
    """
    try:
        with _get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.info("Database initialised at '%s'.", DB_PATH)
        return True
    except sqlite3.Error as exc:
        logger.error("Failed to initialise database: %s", exc)
        return False


# ── events ────────────────────────────────────────────────────────────────────

def create_event(
    name: str,
    event_type: str,
    event_date: str,
    guest_count: int,
    total_budget: float,
    location: str = "",
    preferences: str = "",
) -> Optional[int]:
    """
    Insert a new event record.

    Returns:
        The new row ID on success, or None on failure.
    """
    sql = """
        INSERT INTO events
            (name, event_type, location, event_date, guest_count,
             total_budget, preferences, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                sql,
                (name, event_type, location, event_date,
                 guest_count, total_budget, preferences, _now_iso()),
            )
            return cursor.lastrowid
    except sqlite3.Error as exc:
        logger.error("create_event failed: %s", exc)
        return None


def get_event(event_id: int) -> Optional[dict[str, Any]]:
    """Fetch a single event by ID. Returns None if not found."""
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
    except sqlite3.Error as exc:
        logger.error("get_event(%d) failed: %s", event_id, exc)
        return None


def list_events() -> list[dict[str, Any]]:
    """Return all events ordered by event_date ascending."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY event_date ASC"
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("list_events failed: %s", exc)
        return []


def update_event(event_id: int, **fields: Any) -> bool:
    """
    Update one or more columns on an events row.

    Only the following columns are updatable to prevent SQL injection via
    column names:
        name, event_type, location, event_date, guest_count,
        total_budget, preferences

    Returns True on success.
    """
    allowed = {
        "name", "event_type", "location", "event_date",
        "guest_count", "total_budget", "preferences",
    }
    to_update = {k: v for k, v in fields.items() if k in allowed}
    if not to_update:
        logger.warning("update_event called with no valid fields.")
        return False

    set_clause = ", ".join(f"{col} = ?" for col in to_update)
    values = list(to_update.values()) + [event_id]

    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE events SET {set_clause} WHERE id = ?", values  # noqa: S608
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("update_event(%d) failed: %s", event_id, exc)
        return False


def delete_event(event_id: int) -> bool:
    """
    Delete an event and all its child records (CASCADE).

    Returns True on success.
    """
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return True
    except sqlite3.Error as exc:
        logger.error("delete_event(%d) failed: %s", event_id, exc)
        return False


# ── budget_items ──────────────────────────────────────────────────────────────

def upsert_budget_items(
    event_id: int, items: list[dict[str, Any]]
) -> bool:
    """
    Replace all budget_items for an event with the provided list.

    Each item dict must have:
        category (str), allocated_amount (float),
        actual_amount (float, optional), notes (str, optional)

    This is an all-or-nothing operation (transaction).
    Returns True on success.
    """
    now = _now_iso()
    try:
        with _get_connection() as conn:
            conn.execute(
                "DELETE FROM budget_items WHERE event_id = ?", (event_id,)
            )
            conn.executemany(
                """
                INSERT INTO budget_items
                    (event_id, category, allocated_amount, actual_amount, notes,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event_id,
                        item["category"],
                        float(item.get("allocated_amount", 0.0)),
                        float(item.get("actual_amount", 0.0)),
                        item.get("notes", ""),
                        now,
                        now,
                    )
                    for item in items
                ],
            )
        return True
    except (sqlite3.Error, KeyError, TypeError) as exc:
        logger.error("upsert_budget_items(event_id=%d) failed: %s", event_id, exc)
        return False


def get_budget_items(event_id: int) -> list[dict[str, Any]]:
    """Return all budget_items for an event, ordered by category."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM budget_items WHERE event_id = ? ORDER BY category",
                (event_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_budget_items(event_id=%d) failed: %s", event_id, exc)
        return []


def update_budget_item_actual(item_id: int, actual_amount: float) -> bool:
    """Update the actual_amount on a single budget_items row."""
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "UPDATE budget_items SET actual_amount = ?, updated_at = ? WHERE id = ?",
                (actual_amount, _now_iso(), item_id),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("update_budget_item_actual(%d) failed: %s", item_id, exc)
        return False


# ── vendors ───────────────────────────────────────────────────────────────────

def create_vendor(
    event_id: int,
    category: str,
    name: str,
    contact: str = "",
    status: str = "pending",
    notes: str = "",
) -> Optional[int]:
    """Insert a vendor record. Returns new row ID or None."""
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO vendors
                    (event_id, category, name, contact, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, category, name, contact, status, notes, _now_iso()),
            )
            return cursor.lastrowid
    except sqlite3.Error as exc:
        logger.error("create_vendor failed: %s", exc)
        return None


def get_vendors(event_id: int) -> list[dict[str, Any]]:
    """Return all vendors for an event, ordered by category."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM vendors WHERE event_id = ? ORDER BY category, name",
                (event_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_vendors(event_id=%d) failed: %s", event_id, exc)
        return []


def update_vendor(vendor_id: int, **fields: Any) -> bool:
    """Update vendor fields. Allowed columns: category, name, contact, status, notes."""
    allowed = {"category", "name", "contact", "status", "notes"}
    to_update = {k: v for k, v in fields.items() if k in allowed}
    if not to_update:
        return False
    set_clause = ", ".join(f"{col} = ?" for col in to_update)
    values = list(to_update.values()) + [vendor_id]
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE vendors SET {set_clause} WHERE id = ?", values  # noqa: S608
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("update_vendor(%d) failed: %s", vendor_id, exc)
        return False


def delete_vendor(vendor_id: int) -> bool:
    """Delete a vendor record. Returns True on success."""
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
        return True
    except sqlite3.Error as exc:
        logger.error("delete_vendor(%d) failed: %s", vendor_id, exc)
        return False


# ── timeline_tasks ────────────────────────────────────────────────────────────

def create_timeline_tasks(
    event_id: int, tasks: list[dict[str, Any]]
) -> bool:
    """
    Bulk-insert timeline tasks for an event (replaces existing tasks).

    Each task dict must have: task (str), deadline (str YYYY-MM-DD),
    priority (str), status (str), notes (str, optional)

    Returns True on success.
    """
    now = _now_iso()
    try:
        with _get_connection() as conn:
            conn.execute(
                "DELETE FROM timeline_tasks WHERE event_id = ?", (event_id,)
            )
            conn.executemany(
                """
                INSERT INTO timeline_tasks
                    (event_id, task, deadline, priority, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event_id,
                        t["task"],
                        t["deadline"],
                        t.get("priority", "medium"),
                        t.get("status", "pending"),
                        t.get("notes", ""),
                        now,
                    )
                    for t in tasks
                ],
            )
        return True
    except (sqlite3.Error, KeyError, TypeError) as exc:
        logger.error("create_timeline_tasks(event_id=%d) failed: %s", event_id, exc)
        return False


def get_timeline_tasks(event_id: int) -> list[dict[str, Any]]:
    """Return timeline tasks for an event, sorted by deadline ascending."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM timeline_tasks WHERE event_id = ? ORDER BY deadline ASC",
                (event_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_timeline_tasks(event_id=%d) failed: %s", event_id, exc)
        return []


def update_task_status(task_id: int, status: str) -> bool:
    """Update the status of a single timeline task."""
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "UPDATE timeline_tasks SET status = ? WHERE id = ?",
                (status, task_id),
            )
            return cursor.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("update_task_status(%d) failed: %s", task_id, exc)
        return False
