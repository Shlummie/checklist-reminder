"""
Tkinter-based main window UI for the Checklist Reminder application.
Features: task list with groups, add/edit/delete tasks, search, filters, settings.
"""

import logging
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict
from db import Database, Task, TaskStatus, RecurrenceType, Priority
import startup

logger = logging.getLogger(__name__)


class TaskDialog(tk.Toplevel):
    """Dialog for adding or editing a task."""

    def __init__(self, parent, task: Optional[Task] = None, on_save: Callable[[Task], None] = None):
        super().__init__(parent)
        self.task = task or Task()
        self.on_save = on_save
        self.result: Optional[Task] = None

        self.title("Edit Task" if task and task.id else "Add Task")
        self.geometry("450x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._create_widgets()
        self._populate_fields()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        # Main frame with padding
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main_frame, text="Title *").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(main_frame, textvariable=self.title_var, width=50)
        self.title_entry.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        # Notes
        ttk.Label(main_frame, text="Notes").grid(row=2, column=0, sticky=tk.W, pady=(0, 5))
        self.notes_text = tk.Text(main_frame, height=4, width=50)
        self.notes_text.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        # Due date/time frame
        due_frame = ttk.LabelFrame(main_frame, text="Due Date & Time", padding="10")
        due_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        # Date
        ttk.Label(due_frame, text="Date (YYYY-MM-DD):").grid(row=0, column=0, sticky=tk.W)
        self.date_var = tk.StringVar()
        self.date_entry = ttk.Entry(due_frame, textvariable=self.date_var, width=15)
        self.date_entry.grid(row=0, column=1, padx=(5, 20))

        # Time
        ttk.Label(due_frame, text="Time (HH:MM):").grid(row=0, column=2, sticky=tk.W)
        self.time_var = tk.StringVar()
        self.time_entry = ttk.Entry(due_frame, textvariable=self.time_var, width=10)
        self.time_entry.grid(row=0, column=3, padx=(5, 0))

        # Quick date buttons
        quick_frame = ttk.Frame(due_frame)
        quick_frame.grid(row=1, column=0, columnspan=4, pady=(10, 0))
        ttk.Button(quick_frame, text="Today", command=self._set_today).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="Tomorrow", command=self._set_tomorrow).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="+1 Hour", command=self._set_plus_hour).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="Clear", command=self._clear_date).pack(side=tk.LEFT, padx=2)

        # Recurrence frame
        rec_frame = ttk.LabelFrame(main_frame, text="Recurrence", padding="10")
        rec_frame.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        self.recurrence_var = tk.StringVar(value="none")
        ttk.Radiobutton(rec_frame, text="None", variable=self.recurrence_var, value="none").pack(side=tk.LEFT)
        ttk.Radiobutton(rec_frame, text="Daily", variable=self.recurrence_var, value="daily").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(rec_frame, text="Weekly", variable=self.recurrence_var, value="weekly").pack(side=tk.LEFT)
        ttk.Radiobutton(rec_frame, text="Custom", variable=self.recurrence_var, value="custom").pack(side=tk.LEFT, padx=10)

        ttk.Label(rec_frame, text="Interval (days):").pack(side=tk.LEFT, padx=(10, 5))
        self.interval_var = tk.StringVar(value="1")
        self.interval_entry = ttk.Entry(rec_frame, textvariable=self.interval_var, width=5)
        self.interval_entry.pack(side=tk.LEFT)

        # Priority
        priority_frame = ttk.Frame(main_frame)
        priority_frame.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(0, 15))

        ttk.Label(priority_frame, text="Priority:").pack(side=tk.LEFT)
        self.priority_var = tk.StringVar(value="medium")
        priority_combo = ttk.Combobox(
            priority_frame,
            textvariable=self.priority_var,
            values=["low", "medium", "high"],
            state="readonly",
            width=10
        )
        priority_combo.pack(side=tk.LEFT, padx=(5, 0))

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=7, column=0, columnspan=2, sticky=tk.E)

        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.LEFT)

        # Focus title
        self.title_entry.focus_set()

    def _populate_fields(self):
        """Populate fields with existing task data."""
        if self.task:
            self.title_var.set(self.task.title)
            self.notes_text.insert("1.0", self.task.notes or "")

            if self.task.due_at:
                self.date_var.set(self.task.due_at.strftime("%Y-%m-%d"))
                self.time_var.set(self.task.due_at.strftime("%H:%M"))

            self.recurrence_var.set(self.task.recurrence_type.value)
            self.interval_var.set(str(self.task.recurrence_interval))
            self.priority_var.set(self.task.priority.value)

    def _set_today(self):
        now = datetime.now()
        self.date_var.set(now.strftime("%Y-%m-%d"))
        if not self.time_var.get():
            # Default to next hour
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0)
            self.time_var.set(next_hour.strftime("%H:%M"))

    def _set_tomorrow(self):
        tomorrow = datetime.now() + timedelta(days=1)
        self.date_var.set(tomorrow.strftime("%Y-%m-%d"))
        if not self.time_var.get():
            self.time_var.set("09:00")

    def _set_plus_hour(self):
        future = datetime.now() + timedelta(hours=1)
        self.date_var.set(future.strftime("%Y-%m-%d"))
        self.time_var.set(future.strftime("%H:%M"))

    def _clear_date(self):
        self.date_var.set("")
        self.time_var.set("")

    def _save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showerror("Error", "Title is required", parent=self)
            return

        # Parse due date/time
        due_at = None
        date_str = self.date_var.get().strip()
        time_str = self.time_var.get().strip() or "09:00"

        if date_str:
            try:
                due_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showerror("Error", "Invalid date/time format", parent=self)
                return

        # Parse interval
        try:
            interval = int(self.interval_var.get())
            if interval < 1:
                interval = 1
        except ValueError:
            interval = 1

        # Update task
        self.task.title = title
        self.task.notes = self.notes_text.get("1.0", tk.END).strip()
        self.task.due_at = due_at
        self.task.recurrence_type = RecurrenceType(self.recurrence_var.get())
        self.task.recurrence_interval = interval
        self.task.priority = Priority(self.priority_var.get())

        self.result = self.task

        if self.on_save:
            self.on_save(self.task)

        self.destroy()


class SettingsDialog(tk.Toplevel):
    """Settings dialog."""

    def __init__(self, parent, db: Database, on_close: Callable = None):
        super().__init__(parent)
        self.db = db
        self.on_close = on_close

        self.title("Settings")
        self.geometry("400x200")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Run on startup
        self.startup_var = tk.BooleanVar(value=startup.is_startup_enabled())
        startup_check = ttk.Checkbutton(
            main_frame,
            text="Run on Windows startup",
            variable=self.startup_var,
            command=self._toggle_startup
        )
        startup_check.pack(anchor=tk.W, pady=10)

        ttk.Label(
            main_frame,
            text="When enabled, the app will start minimized to\nthe system tray when you log in.",
            foreground="gray"
        ).pack(anchor=tk.W, padx=20)

        # Default reminder time
        time_frame = ttk.Frame(main_frame)
        time_frame.pack(anchor=tk.W, pady=20)

        ttk.Label(time_frame, text="Default reminder time:").pack(side=tk.LEFT)
        self.default_time_var = tk.StringVar(value=self.db.get_setting("default_time", "09:00"))
        time_entry = ttk.Entry(time_frame, textvariable=self.default_time_var, width=8)
        time_entry.pack(side=tk.LEFT, padx=5)

        # Close button
        ttk.Button(main_frame, text="Close", command=self._close).pack(side=tk.BOTTOM, anchor=tk.E)

    def _toggle_startup(self):
        enabled = self.startup_var.get()
        success = startup.set_startup_enabled(enabled)
        if not success:
            messagebox.showerror("Error", "Failed to update startup setting", parent=self)
            self.startup_var.set(not enabled)
        else:
            self.db.set_setting("run_on_startup", enabled)

    def _close(self):
        # Save default time
        self.db.set_setting("default_time", self.default_time_var.get())

        if self.on_close:
            self.on_close()
        self.destroy()


class MainWindow:
    """Main application window with task list."""

    def __init__(self, db: Database):
        self.db = db
        self.root: Optional[tk.Tk] = None
        self._is_visible = False

        # Callbacks
        self._on_task_completed: Optional[Callable[[int], None]] = None
        self._on_task_added: Optional[Callable[[Task], None]] = None
        self._on_task_updated: Optional[Callable[[Task], None]] = None
        self._on_task_deleted: Optional[Callable[[int], None]] = None
        self._on_close: Optional[Callable] = None

        # Current filter
        self._current_filter = "all"
        self._search_query = ""

    def set_callbacks(
        self,
        on_task_completed: Callable[[int], None] = None,
        on_task_added: Callable[[Task], None] = None,
        on_task_updated: Callable[[Task], None] = None,
        on_task_deleted: Callable[[int], None] = None,
        on_close: Callable = None
    ):
        """Set event callbacks."""
        self._on_task_completed = on_task_completed
        self._on_task_added = on_task_added
        self._on_task_updated = on_task_updated
        self._on_task_deleted = on_task_deleted
        self._on_close = on_close

    def create(self, root: tk.Tk):
        """Create the main window widgets."""
        self.root = root
        self.root.title("Checklist Reminder")
        self.root.geometry("700x550")
        self.root.minsize(500, 400)

        # Configure styles
        self._configure_styles()

        # Create widgets
        self._create_toolbar()
        self._create_task_list()
        self._create_action_buttons()
        self._create_statusbar()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # Initial load
        self.refresh_tasks()

    def _configure_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()

        # Configure Treeview
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        # Tag colors for priorities
        style.map("Treeview",
                  background=[("selected", "#0078D4")],
                  foreground=[("selected", "white")])

    def _create_toolbar(self):
        """Create the toolbar with search and filters."""
        toolbar = ttk.Frame(self.root, padding="10")
        toolbar.pack(fill=tk.X)

        # Search
        ttk.Label(toolbar, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=25)
        search_entry.pack(side=tk.LEFT, padx=(5, 20))

        # Filter buttons
        ttk.Label(toolbar, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar(value="all")

        filters = [("All", "all"), ("Overdue", "overdue"), ("Today", "today"),
                   ("Upcoming", "upcoming"), ("Completed", "completed")]
        for text, value in filters:
            rb = ttk.Radiobutton(toolbar, text=text, variable=self.filter_var,
                                value=value, command=self._on_filter_changed)
            rb.pack(side=tk.LEFT, padx=3)

        # Add task button
        add_btn = ttk.Button(toolbar, text="+ Add Task", command=self.show_add_task)
        add_btn.pack(side=tk.RIGHT)

    def _create_task_list(self):
        """Create the task list treeview."""
        # Frame with scrollbar
        list_frame = ttk.Frame(self.root)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview
        columns = ("title", "due", "priority", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="tree headings",
                                  yscrollcommand=scrollbar.set, selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        # Column configuration
        self.tree.column("#0", width=150, minwidth=120, stretch=False)  # Group headers and checkbox
        self.tree.column("title", width=300, minwidth=150)
        self.tree.column("due", width=150, minwidth=100)
        self.tree.column("priority", width=80, minwidth=60)
        self.tree.column("status", width=100, minwidth=80)

        self.tree.heading("title", text="Task")
        self.tree.heading("due", text="Due")
        self.tree.heading("priority", text="Priority")
        self.tree.heading("status", text="Status")

        # Tags for styling
        self.tree.tag_configure("overdue", foreground="#D32F2F")
        self.tree.tag_configure("completed", foreground="#757575")
        self.tree.tag_configure("high", foreground="#D32F2F")
        self.tree.tag_configure("low", foreground="#757575")
        self.tree.tag_configure("group", font=("Segoe UI", 10, "bold"))

        # Bindings
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<space>", self._on_space_key)

        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Edit", command=self._edit_selected)
        self.context_menu.add_command(label="Mark Complete", command=self._complete_selected)
        self.context_menu.add_command(label="Mark Incomplete", command=self._uncomplete_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete", command=self._delete_selected)

    def _create_action_buttons(self):
        """Create action buttons for tasks."""
        btn_frame = ttk.Frame(self.root, padding="5 0")
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        ttk.Button(btn_frame, text="Edit", command=self._edit_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Delete", command=self._delete_selected).pack(side=tk.LEFT)

    def _create_statusbar(self):
        """Create the status bar."""
        self.statusbar = ttk.Label(self.root, text="", padding="5")
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    def _on_search_changed(self):
        """Handle search text change."""
        self._search_query = self.search_var.get().strip()
        self.refresh_tasks()

    def _on_filter_changed(self):
        """Handle filter change."""
        self._current_filter = self.filter_var.get()
        self.refresh_tasks()

    def refresh_tasks(self):
        """Refresh the task list display."""
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Get tasks based on filter and search
        if self._search_query:
            tasks = self.db.search_tasks(self._search_query)
        elif self._current_filter == "overdue":
            tasks = self.db.get_overdue_tasks()
        elif self._current_filter == "today":
            tasks = self.db.get_tasks_for_today()
        elif self._current_filter == "upcoming":
            tasks = self.db.get_upcoming_tasks()
        elif self._current_filter == "completed":
            tasks = self.db.get_completed_tasks()
        else:
            tasks = self.db.get_all_tasks()

        # Group tasks
        if self._current_filter == "all" and not self._search_query:
            self._display_grouped_tasks(tasks)
        else:
            self._display_flat_tasks(tasks)

        # Update status
        self._update_statusbar()

    def _display_grouped_tasks(self, tasks: List[Task]):
        """Display tasks grouped by status."""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        groups: Dict[str, List[Task]] = {
            "Overdue": [],
            "Today": [],
            "Upcoming": [],
            "Completed": []
        }

        for task in tasks:
            if task.status == TaskStatus.COMPLETED:
                groups["Completed"].append(task)
            elif task.is_overdue():
                groups["Overdue"].append(task)
            elif task.due_at and today_start <= task.due_at < today_end:
                groups["Today"].append(task)
            elif task.recurrence_type == RecurrenceType.DAILY:
                # Hide future daily recurring tasks - they'll appear in Today when due
                pass
            else:
                groups["Upcoming"].append(task)

        # Add groups to tree
        for group_name, group_tasks in groups.items():
            if group_tasks or group_name in ["Overdue", "Today"]:  # Always show Overdue and Today
                display_tasks = group_tasks

                if group_name == "Completed":
                    # Deduplicate recurring tasks - keep only most recent per title
                    seen_titles = set()
                    deduped = []
                    for task in group_tasks:
                        if task.recurrence_type != RecurrenceType.NONE:
                            if task.title not in seen_titles:
                                seen_titles.add(task.title)
                                deduped.append(task)
                        else:
                            deduped.append(task)
                    display_tasks = deduped[:10]

                group_id = self.tree.insert("", tk.END, text=f"{group_name} ({len(display_tasks)})",
                                            tags=("group",), open=True)
                for task in display_tasks:
                    self._add_task_item(group_id, task)

    def _display_flat_tasks(self, tasks: List[Task]):
        """Display tasks in a flat list."""
        for task in tasks:
            self._add_task_item("", task)

    def _add_task_item(self, parent: str, task: Task):
        """Add a task item to the tree."""
        # Determine checkbox symbol
        checkbox = "☑" if task.status == TaskStatus.COMPLETED else "☐"

        # Format due time
        due_str = ""
        if task.due_at:
            if task.due_at.date() == datetime.now().date():
                due_str = task.due_at.strftime("Today %I:%M %p")
            else:
                due_str = task.due_at.strftime("%Y-%m-%d %I:%M %p")

        # Determine tags
        tags = []
        if task.status == TaskStatus.COMPLETED:
            tags.append("completed")
        elif task.is_overdue():
            tags.append("overdue")
        elif task.priority == Priority.HIGH:
            tags.append("high")
        elif task.priority == Priority.LOW:
            tags.append("low")

        # Insert item
        item_id = self.tree.insert(
            parent, tk.END,
            text=checkbox,
            values=(task.title, due_str, task.priority.value.capitalize(), task.status.value.capitalize()),
            tags=tags
        )

        # Store task ID in item
        self.tree.item(item_id, tags=tags + [f"task_{task.id}"])

    def _get_selected_task_id(self) -> Optional[int]:
        """Get the task ID of the selected item."""
        selection = self.tree.selection()
        if not selection:
            return None

        item = selection[0]
        tags = self.tree.item(item, "tags")

        for tag in tags:
            if tag.startswith("task_"):
                return int(tag.split("_")[1])
        return None

    def _on_click(self, event):
        """Handle single click - toggle completion if clicking on checkbox column."""
        item = self.tree.identify_row(event.y)
        if not item:
            return

        # Check if click is within the first column (checkbox area, ~150px wide)
        if event.x > 150:
            return

        # Get task ID from item tags
        tags = self.tree.item(item, "tags")
        task_id = None
        for tag in tags:
            if tag.startswith("task_"):
                task_id = int(tag.split("_")[1])
                break

        if task_id:
            task = self.db.get_task(task_id)
            if task:
                if task.status == TaskStatus.COMPLETED:
                    self.db.uncomplete_task(task_id)
                else:
                    self.db.complete_task(task_id)
                    if self._on_task_completed:
                        self._on_task_completed(task_id)
                self.refresh_tasks()

    def _on_double_click(self, event):
        """Handle double-click on task."""
        self._edit_selected()

    def _on_right_click(self, event):
        """Handle right-click context menu."""
        # Select item under cursor
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _on_space_key(self, event):
        """Handle space key to toggle complete."""
        task_id = self._get_selected_task_id()
        if task_id:
            task = self.db.get_task(task_id)
            if task:
                if task.status == TaskStatus.COMPLETED:
                    self._uncomplete_selected()
                else:
                    self._complete_selected()

    def _edit_selected(self):
        """Edit the selected task."""
        task_id = self._get_selected_task_id()
        if task_id:
            task = self.db.get_task(task_id)
            if task:
                self._show_task_dialog(task)

    def _complete_selected(self):
        """Mark selected task as complete."""
        task_id = self._get_selected_task_id()
        if task_id:
            self.db.complete_task(task_id)
            if self._on_task_completed:
                self._on_task_completed(task_id)
            self.refresh_tasks()

    def _uncomplete_selected(self):
        """Mark selected task as incomplete."""
        task_id = self._get_selected_task_id()
        if task_id:
            self.db.uncomplete_task(task_id)
            self.refresh_tasks()

    def _delete_selected(self):
        """Delete the selected task."""
        task_id = self._get_selected_task_id()
        if task_id:
            if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this task?"):
                self.db.delete_task(task_id)
                if self._on_task_deleted:
                    self._on_task_deleted(task_id)
                self.refresh_tasks()

    def _show_task_dialog(self, task: Optional[Task] = None):
        """Show the task add/edit dialog."""
        def on_save(saved_task: Task):
            if saved_task.id:
                self.db.update_task(saved_task)
                if self._on_task_updated:
                    self._on_task_updated(saved_task)
            else:
                saved_task = self.db.add_task(saved_task)
                if self._on_task_added:
                    self._on_task_added(saved_task)
            self.refresh_tasks()

        dialog = TaskDialog(self.root, task, on_save)
        self.root.wait_window(dialog)

    def show_add_task(self):
        """Show dialog to add a new task."""
        self._show_task_dialog()

    def show_settings(self):
        """Show the settings dialog."""
        SettingsDialog(self.root, self.db, on_close=self.refresh_tasks)

    def _update_statusbar(self):
        """Update the status bar with task counts."""
        overdue = len(self.db.get_overdue_tasks())
        today = len(self.db.get_tasks_for_today())
        total = len(self.db.get_pending_tasks())

        status = f"Total: {total} tasks"
        if overdue > 0:
            status += f" | Overdue: {overdue}"
        if today > 0:
            status += f" | Today: {today}"

        self.statusbar.config(text=status)

    def _on_window_close(self):
        """Handle window close - minimize to tray instead of quitting."""
        self.hide()
        if self._on_close:
            self._on_close()

    def show(self):
        """Show the main window."""
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self._is_visible = True
            self.refresh_tasks()

    def hide(self):
        """Hide the main window to tray."""
        if self.root:
            self.root.withdraw()
            self._is_visible = False

    def toggle(self):
        """Toggle window visibility."""
        if self._is_visible:
            self.hide()
        else:
            self.show()

    def show_overdue(self):
        """Show window with overdue filter selected."""
        self.filter_var.set("overdue")
        self._current_filter = "overdue"
        self.show()
        self.refresh_tasks()

    @property
    def is_visible(self) -> bool:
        return self._is_visible
