"""
Checklist Reminder - Windows Desktop Application
Main entry point that orchestrates all components.
"""

import logging
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from single_instance import SingleInstance
from db import Database, Task, TaskStatus
from notifications import NotificationManager, NotificationAction, is_notification_support_available
from scheduler import TaskScheduler
from tray import SystemTray
from ui import MainWindow

# Configure logging
def setup_logging():
    """Set up logging to file and console."""
    log_dir = Path.home() / ".checklist_reminder"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "app.log"

    # Rotate log if too large (> 5MB)
    if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:
        backup = log_dir / "app.log.old"
        if backup.exists():
            backup.unlink()
        log_file.rename(backup)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger(__name__)


class ChecklistApp:
    """
    Main application class that coordinates all components:
    - Database for persistence
    - Scheduler for background task monitoring
    - Notification manager for Windows toast notifications
    - System tray for background operation
    - Main window for UI
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing Checklist Reminder application")

        # Core components
        self.db: Optional[Database] = None
        self.scheduler: Optional[TaskScheduler] = None
        self.notifier: Optional[NotificationManager] = None
        self.tray: Optional[SystemTray] = None
        self.window: Optional[MainWindow] = None
        self.root: Optional[tk.Tk] = None

        # Single instance controller
        self.single_instance: Optional[SingleInstance] = None

        # State
        self._running = False

    def initialize(self) -> bool:
        """Initialize all application components. Returns True on success."""
        try:
            # Initialize database
            self.db = Database()
            self.logger.info("Database initialized")

            # Get notification preference (default to popup/no toast)
            use_toast = self.db.get_setting("use_toast_notifications", False)

            # Initialize notification manager
            self.notifier = NotificationManager(use_toast=use_toast)
            self._setup_notification_callbacks()
            self.logger.info(f"Notifications: toast={use_toast}, available={is_notification_support_available()}")

            # Initialize scheduler
            self.scheduler = TaskScheduler(self.db)
            self._setup_scheduler_callbacks()
            self.logger.info("Scheduler initialized")

            # Initialize system tray
            self.tray = SystemTray()
            self._setup_tray_callbacks()
            self.logger.info("System tray initialized")

            # Initialize Tkinter root (hidden initially)
            self.root = tk.Tk()
            self.root.withdraw()  # Start hidden

            # Set Tk root for popup notifications
            self.notifier.set_tk_root(self.root)

            # Initialize main window
            self.window = MainWindow(self.db)
            self._setup_window_callbacks()
            self.window.create(self.root)
            self.window.hide()  # Ensure it's hidden at start
            self.logger.info("Main window initialized")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize application: {e}", exc_info=True)
            return False

    def _setup_notification_callbacks(self):
        """Set up notification action callbacks."""
        self.notifier.set_callback(NotificationAction.DONE, self._on_notification_done)
        self.notifier.set_callback(NotificationAction.SNOOZE_10M, self._on_notification_snooze_10m)
        self.notifier.set_callback(NotificationAction.SNOOZE_1H, self._on_notification_snooze_1h)
        self.notifier.set_callback(NotificationAction.OPEN_APP, self._on_notification_open)
        self.notifier.set_callback(NotificationAction.DISMISSED, self._on_notification_dismissed)

    def _setup_scheduler_callbacks(self):
        """Set up scheduler callbacks."""
        self.scheduler.set_on_task_due(self._on_task_due)
        self.scheduler.set_on_missed_tasks(self._on_missed_tasks)
        self.scheduler.set_on_tasks_changed(self._on_tasks_changed)

    def _setup_tray_callbacks(self):
        """Set up system tray callbacks."""
        self.tray.set_callbacks(
            on_show_window=self._show_window,
            on_add_task=self._add_task_from_tray,
            on_view_overdue=self._view_overdue,
            on_settings=self._show_settings,
            on_quit=self._quit,
            on_pause_notifications=self._pause_notifications,
            on_resume_notifications=self._resume_notifications
        )

    def _setup_window_callbacks(self):
        """Set up main window callbacks."""
        self.window.set_callbacks(
            on_task_completed=self._on_task_completed,
            on_task_added=self._on_task_added,
            on_task_updated=self._on_task_updated,
            on_task_deleted=self._on_task_deleted,
            on_close=self._on_window_closed
        )

    # ==================== NOTIFICATION CALLBACKS ====================

    def _on_notification_done(self, task_id: int):
        """Handle 'Done' button click on notification."""
        self.logger.info(f"Notification Done clicked for task {task_id}")
        self.db.complete_task(task_id)
        self.scheduler.task_completed(task_id)
        self._schedule_ui_refresh()

    def _on_notification_snooze_10m(self, task_id: int):
        """Handle 'Snooze 10m' button click on notification."""
        self.logger.info(f"Notification Snooze 10m clicked for task {task_id}")
        until = datetime.now() + timedelta(minutes=10)
        self.scheduler.task_snoozed(task_id, until)
        self._schedule_ui_refresh()

    def _on_notification_snooze_1h(self, task_id: int):
        """Handle 'Snooze 1h' button click on notification."""
        self.logger.info(f"Notification Snooze 1h clicked for task {task_id}")
        until = datetime.now() + timedelta(hours=1)
        self.scheduler.task_snoozed(task_id, until)
        self._schedule_ui_refresh()

    def _on_notification_open(self, task_id: int):
        """Handle 'Open' button click on notification."""
        self.logger.info(f"Notification Open clicked for task {task_id}")
        self._show_window()

    def _on_notification_dismissed(self, task_id: int):
        """Handle notification dismissed (ignored)."""
        self.logger.info(f"Notification dismissed for task {task_id}")
        # Mark task as missed if it was pending
        task = self.db.get_task(task_id)
        if task and task.status == TaskStatus.PENDING:
            self.db.mark_task_missed(task_id)
            self._update_tray_icon()

    # ==================== SCHEDULER CALLBACKS ====================

    def _on_task_due(self, task: Task):
        """Handle task becoming due - show notification."""
        self.logger.info(f"Task due: {task.id} - {task.title}")
        self.notifier.show_task_notification(
            task_id=task.id,
            title=task.title,
            notes=task.notes,
            due_time=task.due_at
        )
        self._update_tray_icon()

    def _on_missed_tasks(self, tasks: List[Task]):
        """Handle missed tasks detected on startup."""
        self.logger.info(f"Detected {len(tasks)} missed tasks")
        if tasks:
            titles = [t.title for t in tasks]
            self.notifier.show_missed_tasks_summary(len(tasks), titles)
            self._update_tray_icon()

    def _on_tasks_changed(self):
        """Handle tasks changed - refresh UI."""
        self._schedule_ui_refresh()

    # ==================== TRAY CALLBACKS ====================

    def _show_window(self):
        """Show the main window."""
        if self.root and self.window:
            # Schedule on main thread
            self.root.after(0, self.window.show)

    def _add_task_from_tray(self):
        """Show add task dialog from tray."""
        if self.root and self.window:
            self.root.after(0, lambda: (self.window.show(), self.window.show_add_task()))

    def _view_overdue(self):
        """Show overdue tasks from tray."""
        if self.root and self.window:
            self.root.after(0, self.window.show_overdue)

    def _show_settings(self):
        """Show settings dialog from tray."""
        if self.root and self.window:
            self.root.after(0, lambda: (self.window.show(), self.window.show_settings()))

    def _pause_notifications(self, hours: Optional[float], until: Optional[datetime]):
        """Pause notifications."""
        self.notifier.pause_notifications(hours, until)
        self.tray.update_pause_state(True, self.notifier.get_pause_end_time())

    def _resume_notifications(self):
        """Resume notifications."""
        self.notifier.resume_notifications()
        self.tray.update_pause_state(False)

    def _quit(self):
        """Quit the application."""
        self.logger.info("Quit requested from tray")
        self._running = False
        if self.root:
            self.root.after(0, self._shutdown)

    # ==================== WINDOW CALLBACKS ====================

    def _on_task_completed(self, task_id: int):
        """Handle task completed from UI."""
        self.scheduler.task_completed(task_id)
        self._update_tray_icon()

    def _on_task_added(self, task: Task):
        """Handle task added from UI."""
        self.scheduler.task_added(task)

    def _on_task_updated(self, task: Task):
        """Handle task updated from UI."""
        self.scheduler.task_updated(task)

    def _on_task_deleted(self, task_id: int):
        """Handle task deleted from UI."""
        self.scheduler.task_deleted(task_id)
        self._update_tray_icon()

    def _on_window_closed(self):
        """Handle window close - just hide, don't quit."""
        pass  # Window handles hiding itself

    # ==================== HELPERS ====================

    def _schedule_ui_refresh(self):
        """Schedule a UI refresh on the main thread."""
        if self.root and self.window:
            try:
                self.root.after(0, self.window.refresh_tasks)
            except tk.TclError:
                pass  # Window may be destroyed

    def _update_tray_icon(self):
        """Update tray icon based on overdue status."""
        if self.tray:
            overdue = self.db.get_overdue_tasks()
            self.tray.update_icon(has_overdue=len(overdue) > 0)

    def _on_activate_from_other_instance(self):
        """Called when another instance tries to start."""
        self.logger.info("Activation signal from another instance")
        self._show_window()

    # ==================== LIFECYCLE ====================

    def run(self):
        """Start the application main loop."""
        self._running = True

        # Start system tray
        self.tray.start()

        # Start scheduler
        self.scheduler.start()

        # Check for missed tasks from previous session
        self.scheduler.check_missed_tasks()

        # Update tray icon
        self._update_tray_icon()

        self.logger.info("Application started, entering main loop")

        # Run Tkinter main loop
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        finally:
            self._shutdown()

    def _shutdown(self):
        """Shutdown all components."""
        self.logger.info("Shutting down application")
        self._running = False

        # Stop scheduler
        if self.scheduler:
            self.scheduler.stop()

        # Stop tray
        if self.tray:
            self.tray.stop()

        # Close database
        if self.db:
            self.db.close()

        # Destroy Tk root
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except tk.TclError:
                pass

        self.logger.info("Application shutdown complete")


def main():
    """Main entry point."""
    # Set up logging first
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("Checklist Reminder starting")
    logger.info("=" * 50)

    # Single instance check
    single_instance = SingleInstance()

    if not single_instance.acquire():
        # Another instance is running, signal it and exit
        logger.info("Another instance is running, signaling it to show window")
        single_instance.signal_existing_instance()
        sys.exit(0)

    try:
        # Create and run application
        app = ChecklistApp()

        # Set callback for activation from other instances
        single_instance._on_activate = app._on_activate_from_other_instance

        if not app.initialize():
            logger.error("Failed to initialize application")
            sys.exit(1)

        app.run()

    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
    finally:
        single_instance.release()
        logger.info("Application exited")


if __name__ == "__main__":
    main()
