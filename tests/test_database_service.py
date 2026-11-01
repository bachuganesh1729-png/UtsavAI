"""
tests/test_database_service.py
───────────────────────────────
Unit tests for services/database_service.py.

Uses an in-memory / temp SQLite database (patched via monkeypatch) so tests
are isolated and do not touch the production database file.

Covers:
- Database initialisation (tables created)
- events CRUD (create, get, list, update, delete)
- budget_items (upsert, get, update actual amount)
- vendors (create, get, update, delete)
- timeline_tasks (create, get, update status)
- Foreign key cascade (delete event → children removed)
- Invalid / edge-case inputs
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pytest

# We monkeypatch DB_PATH before importing database_service
import utils.config as config_module


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect the database to a temporary file for each test.
    The file is deleted automatically after the test.
    """
    db_file = str(tmp_path / "test_utsavai.db")
    monkeypatch.setattr(config_module, "DB_PATH", db_file)

    # Also patch the DB_PATH in database_service (already imported)
    import services.database_service as db_svc
    monkeypatch.setattr(db_svc, "DB_PATH", db_file)

    from services.database_service import initialize_database
    initialize_database()

    yield db_file


# ── Helpers ───────────────────────────────────────────────────────────────────

def _future_date(days: int = 90) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _create_sample_event(**overrides) -> int:
    from services.database_service import create_event
    defaults = dict(
        name="Test Wedding",
        event_type="Wedding",
        event_date=_future_date(180),
        guest_count=200,
        total_budget=500_000.0,
        location="Hyderabad",
        preferences="Traditional Telugu ceremony",
    )
    defaults.update(overrides)
    event_id = create_event(**defaults)
    assert event_id is not None, "create_event returned None"
    return event_id


# ── Initialisation ────────────────────────────────────────────────────────────

class TestInitialization:
    def test_database_initialises_successfully(self):
        from services.database_service import initialize_database
        assert initialize_database() is True

    def test_tables_exist(self, tmp_path, monkeypatch):
        import sqlite3
        import services.database_service as db_svc

        db_path = db_svc.DB_PATH
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()

        assert "events" in tables
        assert "budget_items" in tables
        assert "vendors" in tables
        assert "timeline_tasks" in tables


# ── events CRUD ───────────────────────────────────────────────────────────────

class TestEventsCRUD:
    def test_create_event_returns_id(self):
        event_id = _create_sample_event()
        assert isinstance(event_id, int)
        assert event_id > 0

    def test_get_event_returns_correct_data(self):
        from services.database_service import get_event
        event_id = _create_sample_event(name="Priya Birthday")
        event = get_event(event_id)
        assert event is not None
        assert event["name"] == "Priya Birthday"
        assert event["event_type"] == "Wedding"

    def test_get_nonexistent_event_returns_none(self):
        from services.database_service import get_event
        assert get_event(99999) is None

    def test_list_events_returns_all(self):
        from services.database_service import list_events
        _create_sample_event(name="Event A")
        _create_sample_event(name="Event B")
        events = list_events()
        names = [e["name"] for e in events]
        assert "Event A" in names
        assert "Event B" in names

    def test_list_events_ordered_by_date(self):
        from services.database_service import list_events
        _create_sample_event(name="Later Event", event_date=_future_date(200))
        _create_sample_event(name="Earlier Event", event_date=_future_date(30))
        events = list_events()
        assert events[0]["name"] == "Earlier Event"

    def test_update_event_name(self):
        from services.database_service import get_event, update_event
        event_id = _create_sample_event(name="Old Name")
        assert update_event(event_id, name="New Name") is True
        assert get_event(event_id)["name"] == "New Name"

    def test_update_event_invalid_column_ignored(self):
        from services.database_service import update_event
        event_id = _create_sample_event()
        # 'DROP TABLE events' style injection via column name should be ignored
        result = update_event(event_id, malicious_column="DROP TABLE events")
        assert result is False  # No valid fields → returns False

    def test_delete_event(self):
        from services.database_service import delete_event, get_event
        event_id = _create_sample_event()
        assert delete_event(event_id) is True
        assert get_event(event_id) is None

    def test_delete_nonexistent_event(self):
        from services.database_service import delete_event
        # Should succeed silently (no rows affected)
        assert delete_event(99999) is True


# ── budget_items ──────────────────────────────────────────────────────────────

class TestBudgetItems:
    def test_upsert_and_retrieve(self):
        from services.database_service import upsert_budget_items, get_budget_items
        event_id = _create_sample_event()
        items = [
            {"category": "Venue",    "allocated_amount": 50_000, "actual_amount": 45_000, "notes": ""},
            {"category": "Catering", "allocated_amount": 80_000, "actual_amount": 0.0,    "notes": ""},
        ]
        assert upsert_budget_items(event_id, items) is True
        result = get_budget_items(event_id)
        assert len(result) == 2
        categories = [r["category"] for r in result]
        assert "Venue" in categories
        assert "Catering" in categories

    def test_upsert_replaces_existing(self):
        from services.database_service import upsert_budget_items, get_budget_items
        event_id = _create_sample_event()
        upsert_budget_items(event_id, [{"category": "Venue", "allocated_amount": 50_000, "actual_amount": 0}])
        upsert_budget_items(event_id, [{"category": "Catering", "allocated_amount": 80_000, "actual_amount": 0}])
        result = get_budget_items(event_id)
        # Should only have Catering after the second upsert
        assert len(result) == 1
        assert result[0]["category"] == "Catering"

    def test_upsert_empty_list(self):
        from services.database_service import upsert_budget_items, get_budget_items
        event_id = _create_sample_event()
        upsert_budget_items(event_id, [{"category": "Venue", "allocated_amount": 50_000, "actual_amount": 0}])
        assert upsert_budget_items(event_id, []) is True
        assert get_budget_items(event_id) == []

    def test_update_actual_amount(self):
        from services.database_service import upsert_budget_items, get_budget_items, update_budget_item_actual
        event_id = _create_sample_event()
        upsert_budget_items(event_id, [{"category": "Venue", "allocated_amount": 50_000, "actual_amount": 0}])
        item = get_budget_items(event_id)[0]
        assert update_budget_item_actual(item["id"], 42_000.0) is True
        updated = get_budget_items(event_id)[0]
        assert updated["actual_amount"] == pytest.approx(42_000.0)

    def test_cascade_delete_removes_budget_items(self):
        from services.database_service import upsert_budget_items, get_budget_items, delete_event
        event_id = _create_sample_event()
        upsert_budget_items(event_id, [{"category": "Venue", "allocated_amount": 50_000, "actual_amount": 0}])
        delete_event(event_id)
        assert get_budget_items(event_id) == []


# ── vendors ───────────────────────────────────────────────────────────────────

class TestVendors:
    def test_create_and_get_vendor(self):
        from services.database_service import create_vendor, get_vendors
        event_id = _create_sample_event()
        vendor_id = create_vendor(event_id, "Photography", "Studio Lens", contact="9876543210")
        assert vendor_id is not None
        vendors = get_vendors(event_id)
        assert len(vendors) == 1
        assert vendors[0]["name"] == "Studio Lens"

    def test_update_vendor_status(self):
        from services.database_service import create_vendor, get_vendors, update_vendor
        event_id = _create_sample_event()
        vid = create_vendor(event_id, "Catering", "Delhi Caterers")
        update_vendor(vid, status="confirmed")
        vendors = get_vendors(event_id)
        assert vendors[0]["status"] == "confirmed"

    def test_delete_vendor(self):
        from services.database_service import create_vendor, get_vendors, delete_vendor
        event_id = _create_sample_event()
        vid = create_vendor(event_id, "Decoration", "Floral Designs")
        delete_vendor(vid)
        assert get_vendors(event_id) == []

    def test_cascade_delete_removes_vendors(self):
        from services.database_service import create_vendor, get_vendors, delete_event
        event_id = _create_sample_event()
        create_vendor(event_id, "Music", "DJ Beats")
        delete_event(event_id)
        assert get_vendors(event_id) == []

    def test_multiple_vendors_ordered_by_category(self):
        from services.database_service import create_vendor, get_vendors
        event_id = _create_sample_event()
        create_vendor(event_id, "Venue", "Grand Hall")
        create_vendor(event_id, "Catering", "Royal Caterers")
        vendors = get_vendors(event_id)
        assert vendors[0]["category"] == "Catering"  # Alphabetical
        assert vendors[1]["category"] == "Venue"


# ── timeline_tasks ────────────────────────────────────────────────────────────

class TestTimelineTasks:
    def _sample_tasks(self, event_date: str) -> list:
        return [
            {"task": "Book venue", "deadline": _future_date(60), "priority": "high", "status": "pending"},
            {"task": "Send invitations", "deadline": _future_date(30), "priority": "medium", "status": "pending"},
        ]

    def test_create_and_get_tasks(self):
        from services.database_service import create_timeline_tasks, get_timeline_tasks
        event_id = _create_sample_event()
        tasks = self._sample_tasks(_future_date(90))
        assert create_timeline_tasks(event_id, tasks) is True
        result = get_timeline_tasks(event_id)
        assert len(result) == 2

    def test_tasks_ordered_by_deadline(self):
        from services.database_service import create_timeline_tasks, get_timeline_tasks
        event_id = _create_sample_event()
        tasks = [
            {"task": "Later task", "deadline": _future_date(60), "priority": "low", "status": "pending"},
            {"task": "Earlier task", "deadline": _future_date(10), "priority": "high", "status": "pending"},
        ]
        create_timeline_tasks(event_id, tasks)
        result = get_timeline_tasks(event_id)
        assert result[0]["task"] == "Earlier task"

    def test_update_task_status(self):
        from services.database_service import create_timeline_tasks, get_timeline_tasks, update_task_status
        event_id = _create_sample_event()
        create_timeline_tasks(event_id, [{"task": "Book venue", "deadline": _future_date(30), "priority": "high", "status": "pending"}])
        task = get_timeline_tasks(event_id)[0]
        update_task_status(task["id"], "completed")
        updated = get_timeline_tasks(event_id)[0]
        assert updated["status"] == "completed"

    def test_cascade_delete_removes_tasks(self):
        from services.database_service import create_timeline_tasks, get_timeline_tasks, delete_event
        event_id = _create_sample_event()
        create_timeline_tasks(event_id, [{"task": "Venue", "deadline": _future_date(30), "priority": "high", "status": "pending"}])
        delete_event(event_id)
        assert get_timeline_tasks(event_id) == []

    def test_create_tasks_replaces_existing(self):
        from services.database_service import create_timeline_tasks, get_timeline_tasks
        event_id = _create_sample_event()
        create_timeline_tasks(event_id, [{"task": "Old task", "deadline": _future_date(30), "priority": "high", "status": "pending"}])
        create_timeline_tasks(event_id, [{"task": "New task", "deadline": _future_date(20), "priority": "medium", "status": "pending"}])
        result = get_timeline_tasks(event_id)
        assert len(result) == 1
        assert result[0]["task"] == "New task"
