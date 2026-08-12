"""
SQLite database layer for task and settings persistence.
Includes schema management and migrations.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import threading
import json

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    MISSED = "missed"


class RecurrenceType(Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Task:
    """Represents a task/reminder."""
    id: Optional[int] = None
    title: str = ""
    notes: str = ""
    due_at: Optional[datetime] = None
    recurrence_type: RecurrenceType = RecurrenceType.NONE
    recurrence_interval: int = 1  # Days for custom, ignored for daily/weekly
    recurrence_byweekday: str = ""  # JSON list of weekday indices (0=Mon) for weekly
    snoozed_until: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.MEDIUM
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'notes': self.notes,
            'due_at': self.due_at.isoformat() if self.due_at else None,
            'recurrence_type': self.recurrence_type.value,
            'recurrence_interval': self.recurrence_interval,
            'recurrence_byweekday': self.recurrence_byweekday,
            'snoozed_until': self.snoozed_until.isoformat() if self.snoozed_until else None,
            'status': self.status.value,
            'priority': self.priority.value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Task':
        """Create Task from database row."""
        return cls(
            id=row['id'],
            title=row['title'],
            notes=row['notes'] or "",
            due_at=datetime.fromisoformat(row['due_at']) if row['due_at'] else None,
            recurrence_type=RecurrenceType(row['recurrence_type']),
            recurrence_interval=row['recurrence_interval'],
            recurrence_byweekday=row['recurrence_byweekday'] or "",
            snoozed_until=datetime.fromisoformat(row['snoozed_until']) if row['snoozed_until'] else None,
            status=TaskStatus(row['status']),
            priority=Priority(row['priority']),
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
        )

    def get_effective_due_time(self) -> Optional[datetime]:
        """Get the effective due time, considering snooze."""
        if self.snoozed_until and self.snoozed_until > datetime.now():
            return self.snoozed_until
        return self.due_at

    def is_overdue(self) -> bool:
        """Check if task is overdue."""
        if self.status == TaskStatus.COMPLETED:
            return False
        effective_due = self.get_effective_due_time()
        if effective_due:
            return effective_due < datetime.now()
        return False


# Schema version for migrations
SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            notes TEXT,
            due_at TEXT,
            recurrence_type TEXT NOT NULL DEFAULT 'none',
            recurrence_interval INTEGER DEFAULT 1,
            recurrence_byweekday TEXT,
            snoozed_until TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_snoozed_until ON tasks(snoozed_until);
    """
}


class Database:
    """Thread-safe SQLite database manager."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            # Default to app data directory
            app_data = Path.home() / ".checklist_reminder"
            app_data.mkdir(exist_ok=True)
            db_path = app_data / "checklist.db"

        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()

        # Initialize database
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES
            )
            self._local.conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.conn.execute("PRAGMA foreign_keys = ON")
        return self._local.conn

    def _init_db(self):
        """Initialize database and run migrations."""
        conn = self._get_connection()

        # Check current schema version
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            current_version = 0
        else:
            cursor = conn.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row and row[0] else 0

        # Run migrations
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            if version in MIGRATIONS:
                logger.info(f"Running migration to version {version}")
                conn.executescript(MIGRATIONS[version])
                conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))
                conn.commit()

        logger.info(f"Database initialized at {self.db_path}, schema version {SCHEMA_VERSION}")

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ==================== TASK OPERATIONS ====================

    def add_task(self, task: Task) -> Task:
        """Add a new task to the database."""
        now = datetime.now()
        task.created_at = now
        task.updated_at = now

        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    title, notes, due_at, recurrence_type, recurrence_interval,
                    recurrence_byweekday, snoozed_until, status, priority,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.title,
                    task.notes,
                    task.due_at.isoformat() if task.due_at else None,
                    task.recurrence_type.value,
                    task.recurrence_interval,
                    task.recurrence_byweekday,
                    task.snoozed_until.isoformat() if task.snoozed_until else None,
                    task.status.value,
                    task.priority.value,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.completed_at.isoformat() if task.completed_at else None,
                )
            )
            conn.commit()
            task.id = cursor.lastrowid

        logger.info(f"Added task: {task.id} - {task.title}")
        return task

    def update_task(self, task: Task) -> Task:
        """Update an existing task."""
        task.updated_at = datetime.now()

        conn = self._get_connection()
        with self._lock:
            conn.execute(
                """
                UPDATE tasks SET
                    title = ?, notes = ?, due_at = ?, recurrence_type = ?,
                    recurrence_interval = ?, recurrence_byweekday = ?,
                    snoozed_until = ?, status = ?, priority = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    task.title,
                    task.notes,
                    task.due_at.isoformat() if task.due_at else None,
                    task.recurrence_type.value,
                    task.recurrence_interval,
                    task.recurrence_byweekday,
                    task.snoozed_until.isoformat() if task.snoozed_until else None,
                    task.status.value,
                    task.priority.value,
                    task.updated_at.isoformat(),
                    task.completed_at.isoformat() if task.completed_at else None,
                    task.id,
                )
            )
            conn.commit()

        logger.info(f"Updated task: {task.id} - {task.title}")
        return task

    def delete_task(self, task_id: int):
        """Delete a task by ID."""
        conn = self._get_connection()
        with self._lock:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        logger.info(f"Deleted task: {task_id}")

    def get_task(self, task_id: int) -> Optional[Task]:
        """Get a single task by ID."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            return Task.from_row(row)
        return None

    def get_all_tasks(self) -> List[Task]:
        """Get all tasks."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM tasks ORDER BY due_at ASC NULLS LAST")
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_pending_tasks(self) -> List[Task]:
        """Get all pending (non-completed) tasks."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM tasks WHERE status != ? ORDER BY due_at ASC NULLS LAST",
            (TaskStatus.COMPLETED.value,)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_tasks_due_before(self, before: datetime) -> List[Task]:
        """Get pending tasks due before a given time."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            AND due_at IS NOT NULL
            AND (
                (snoozed_until IS NULL AND due_at <= ?)
                OR (snoozed_until IS NOT NULL AND snoozed_until <= ?)
            )
            ORDER BY due_at ASC
            """,
            (TaskStatus.PENDING.value, before.isoformat(), before.isoformat())
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_overdue_tasks(self) -> List[Task]:
        """Get all overdue tasks."""
        now = datetime.now()
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN (?, ?)
            AND due_at IS NOT NULL
            AND (
                (snoozed_until IS NULL AND due_at < ?)
                OR (snoozed_until IS NOT NULL AND snoozed_until < ?)
            )
            ORDER BY due_at ASC
            """,
            (TaskStatus.PENDING.value, TaskStatus.MISSED.value, now.isoformat(), now.isoformat())
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_tasks_for_today(self) -> List[Task]:
        """Get tasks due today."""
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            AND due_at IS NOT NULL
            AND due_at >= ? AND due_at < ?
            ORDER BY due_at ASC
            """,
            (TaskStatus.PENDING.value, start_of_day.isoformat(), end_of_day.isoformat())
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_upcoming_tasks(self) -> List[Task]:
        """Get tasks due after today."""
        now = datetime.now()
        end_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            AND due_at IS NOT NULL
            AND due_at >= ?
            ORDER BY due_at ASC
            """,
            (TaskStatus.PENDING.value, end_of_day.isoformat())
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def get_completed_tasks(self, limit: int = 50) -> List[Task]:
        """Get completed tasks, most recent first."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (TaskStatus.COMPLETED.value, limit)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def complete_task(self, task_id: int) -> Optional[Task]:
        """Mark a task as completed."""
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.snoozed_until = None
            return self.update_task(task)
        return None

    def uncomplete_task(self, task_id: int) -> Optional[Task]:
        """Mark a completed task as pending again.

        For recurring tasks, also deletes the future occurrence that was created.
        """
        task = self.get_task(task_id)
        if task:
            # For recurring tasks, delete the future pending occurrence
            if task.recurrence_type != RecurrenceType.NONE and task.due_at:
                self._delete_future_recurrence(task)

            task.status = TaskStatus.PENDING
            task.completed_at = None
            return self.update_task(task)
        return None

    def _delete_future_recurrence(self, task: Task):
        """Delete pending future occurrence of a recurring task."""
        conn = self._get_connection()
        with self._lock:
            # Delete pending tasks with same title and recurrence that are due after this task
            conn.execute(
                """
                DELETE FROM tasks
                WHERE title = ?
                AND recurrence_type = ?
                AND status = ?
                AND due_at > ?
                """,
                (task.title, task.recurrence_type.value, TaskStatus.PENDING.value,
                 task.due_at.isoformat() if task.due_at else None)
            )
            conn.commit()
        logger.info(f"Deleted future recurrence for task: {task.title}")

    def snooze_task(self, task_id: int, until: datetime) -> Optional[Task]:
        """Snooze a task until a specific time."""
        task = self.get_task(task_id)
        if task:
            task.snoozed_until = until
            task.status = TaskStatus.PENDING
            return self.update_task(task)
        return None

    def mark_task_missed(self, task_id: int) -> Optional[Task]:
        """Mark a task as missed."""
        task = self.get_task(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.MISSED
            return self.update_task(task)
        return None

    def search_tasks(self, query: str) -> List[Task]:
        """Search tasks by title or notes."""
        conn = self._get_connection()
        search_pattern = f"%{query}%"
        cursor = conn.execute(
            """
            SELECT * FROM tasks
            WHERE title LIKE ? OR notes LIKE ?
            ORDER BY due_at ASC NULLS LAST
            """,
            (search_pattern, search_pattern)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def create_next_recurrence(self, task: Task) -> Optional[Task]:
        """Create the next occurrence of a recurring task."""
        if task.recurrence_type == RecurrenceType.NONE or not task.due_at:
            return None

        new_due = None
        if task.recurrence_type == RecurrenceType.DAILY:
            # Schedule for tomorrow at the same time
            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            new_due = tomorrow.replace(
                hour=task.due_at.hour,
                minute=task.due_at.minute,
                second=task.due_at.second,
                microsecond=0
            )
        elif task.recurrence_type == RecurrenceType.WEEKLY:
            new_due = task.due_at + timedelta(weeks=1)
        elif task.recurrence_type == RecurrenceType.CUSTOM:
            new_due = task.due_at + timedelta(days=task.recurrence_interval)

        if new_due:
            new_task = Task(
                title=task.title,
                notes=task.notes,
                due_at=new_due,
                recurrence_type=task.recurrence_type,
                recurrence_interval=task.recurrence_interval,
                recurrence_byweekday=task.recurrence_byweekday,
                priority=task.priority,
            )
            return self.add_task(new_task)
        return None

    # ==================== SETTINGS OPERATIONS ====================

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row['value'])
            except json.JSONDecodeError:
                return row['value']
        return default

    def set_setting(self, key: str, value: Any):
        """Set a setting value."""
        conn = self._get_connection()
        json_value = json.dumps(value)
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, json_value)
            )
            conn.commit()
        logger.debug(f"Set setting: {key} = {value}")

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings as a dictionary."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT key, value FROM settings")
        settings = {}
        for row in cursor.fetchall():
            try:
                settings[row['key']] = json.loads(row['value'])
            except json.JSONDecodeError:
                settings[row['key']] = row['value']
        return settings

    def delete_completed_tasks(self) -> int:
        """Delete all completed tasks. Returns the count of deleted tasks."""
        conn = self._get_connection()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status = ?",
                (TaskStatus.COMPLETED.value,)
            )
            conn.commit()
            count = cursor.rowcount
        if count > 0:
            logger.info(f"Midnight wipe: deleted {count} completed tasks")
        return count
