"""
Background scheduler for task reminders.
Uses a non-busy-wait approach with calculated sleep times.
Handles system sleep/hibernate/reboot recovery.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional, List, Set
from db import Database, Task, TaskStatus

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Background scheduler that fires notifications for due tasks.

    Design:
    - Calculates next due event and sleeps until then (or max 30 seconds)
    - On wake, fires all due tasks
    - Handles missed tasks from sleep/hibernate/reboot
    """

    MAX_SLEEP_SECONDS = 30  # Maximum sleep interval for periodic checks
    MIN_SLEEP_SECONDS = 1   # Minimum sleep to prevent busy-wait

    def __init__(self, db: Database):
        self.db = db
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()
        self._fired_task_ids: Set[int] = set()  # Track fired tasks to avoid duplicates
        self._last_check_time: Optional[datetime] = None
        self._last_wipe_date: Optional[datetime] = None  # Track last midnight wipe date

        # Callbacks
        self._on_task_due: Optional[Callable[[Task], None]] = None
        self._on_missed_tasks: Optional[Callable[[List[Task]], None]] = None
        self._on_tasks_changed: Optional[Callable[[], None]] = None

    def set_on_task_due(self, callback: Callable[[Task], None]):
        """Set callback when a task becomes due."""
        self._on_task_due = callback

    def set_on_missed_tasks(self, callback: Callable[[List[Task]], None]):
        """Set callback when missed tasks are detected."""
        self._on_missed_tasks = callback

    def set_on_tasks_changed(self, callback: Callable[[], None]):
        """Set callback when tasks are changed (for UI refresh)."""
        self._on_tasks_changed = callback

    def start(self):
        """Start the scheduler background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        self._wake_event.set()  # Wake up the thread to exit

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        logger.info("Scheduler stopped")

    def wake(self):
        """Wake the scheduler to recheck tasks immediately."""
        self._wake_event.set()

    def check_missed_tasks(self):
        """
        Check for tasks that should have fired but were missed.
        Called on app launch to handle sleep/hibernate/reboot scenarios.
        """
        now = datetime.now()
        missed_tasks = []

        pending_tasks = self.db.get_pending_tasks()
        for task in pending_tasks:
            if task.status == TaskStatus.COMPLETED:
                continue

            effective_due = task.get_effective_due_time()
            if effective_due and effective_due < now:
                # Task is overdue and not yet completed
                if task.id not in self._fired_task_ids:
                    missed_tasks.append(task)
                    # Mark as missed
                    self.db.mark_task_missed(task.id)

        if missed_tasks:
            logger.info(f"Found {len(missed_tasks)} missed tasks")
            if self._on_missed_tasks:
                self._on_missed_tasks(missed_tasks)

        return missed_tasks

    def _check_midnight_wipe(self):
        """
        Check if midnight has passed since last wipe and delete completed tasks.
        This prevents duplicate completions from stacking up.
        """
        now = datetime.now()
        today = now.date()

        # If we haven't wiped today, do it now
        if self._last_wipe_date is None or self._last_wipe_date < today:
            count = self.db.delete_completed_tasks()
            self._last_wipe_date = today
            if count > 0 and self._on_tasks_changed:
                self._on_tasks_changed()

    def _scheduler_loop(self):
        """Main scheduler loop."""
        logger.info("Scheduler loop started")

        while self._running:
            try:
                self._check_midnight_wipe()
                self._process_due_tasks()

                # Calculate sleep time
                sleep_seconds = self._calculate_sleep_time()
                logger.debug(f"Scheduler sleeping for {sleep_seconds:.1f} seconds")

                # Wait for wake event or timeout
                self._wake_event.wait(timeout=sleep_seconds)
                self._wake_event.clear()

            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                # Sleep a bit before retrying
                self._wake_event.wait(timeout=5.0)
                self._wake_event.clear()

        logger.info("Scheduler loop exited")

    def _process_due_tasks(self):
        """Process all currently due tasks."""
        now = datetime.now()

        # Detect if we might have slept (gap > MAX_SLEEP_SECONDS + buffer)
        if self._last_check_time:
            gap = (now - self._last_check_time).total_seconds()
            if gap > self.MAX_SLEEP_SECONDS * 2:
                logger.info(f"Detected potential sleep/hibernate (gap: {gap:.0f}s)")
                self.check_missed_tasks()

        self._last_check_time = now

        # Get tasks due now
        due_tasks = self.db.get_tasks_due_before(now)

        for task in due_tasks:
            if task.id in self._fired_task_ids:
                continue

            # Check effective due time
            effective_due = task.get_effective_due_time()
            if effective_due and effective_due <= now:
                logger.info(f"Task due: {task.id} - {task.title}")
                self._fired_task_ids.add(task.id)

                if self._on_task_due:
                    try:
                        self._on_task_due(task)
                    except Exception as e:
                        logger.error(f"Error in on_task_due callback: {e}")

    def _calculate_sleep_time(self) -> float:
        """Calculate how long to sleep until next due task."""
        now = datetime.now()

        # Get all pending tasks
        pending_tasks = self.db.get_pending_tasks()

        next_due: Optional[datetime] = None

        for task in pending_tasks:
            if task.id in self._fired_task_ids:
                continue

            effective_due = task.get_effective_due_time()
            if effective_due and effective_due > now:
                if next_due is None or effective_due < next_due:
                    next_due = effective_due

        if next_due:
            seconds_until_due = (next_due - now).total_seconds()
            # Add a small buffer
            sleep_time = max(self.MIN_SLEEP_SECONDS, min(seconds_until_due + 0.5, self.MAX_SLEEP_SECONDS))
        else:
            sleep_time = self.MAX_SLEEP_SECONDS

        return sleep_time

    def clear_fired_cache(self, task_id: Optional[int] = None):
        """Clear the fired task cache to allow re-notification."""
        if task_id:
            self._fired_task_ids.discard(task_id)
        else:
            self._fired_task_ids.clear()

    def task_completed(self, task_id: int):
        """Called when a task is completed to clean up state."""
        self._fired_task_ids.discard(task_id)

        # Handle recurrence
        task = self.db.get_task(task_id)
        if task and task.recurrence_type.value != "none":
            # Create next occurrence
            new_task = self.db.create_next_recurrence(task)
            if new_task:
                logger.info(f"Created recurring task: {new_task.id} - {new_task.title}")

        if self._on_tasks_changed:
            self._on_tasks_changed()

    def task_snoozed(self, task_id: int, until: datetime):
        """Called when a task is snoozed."""
        self._fired_task_ids.discard(task_id)
        self.db.snooze_task(task_id, until)
        self.wake()  # Recalculate next due time

        if self._on_tasks_changed:
            self._on_tasks_changed()

    def task_added(self, task: Task):
        """Called when a new task is added."""
        self.wake()  # Recalculate next due time

        if self._on_tasks_changed:
            self._on_tasks_changed()

    def task_updated(self, task: Task):
        """Called when a task is updated."""
        # If due time changed, clear fired cache for this task
        self._fired_task_ids.discard(task.id)
        self.wake()

        if self._on_tasks_changed:
            self._on_tasks_changed()

    def task_deleted(self, task_id: int):
        """Called when a task is deleted."""
        self._fired_task_ids.discard(task_id)

        if self._on_tasks_changed:
            self._on_tasks_changed()
