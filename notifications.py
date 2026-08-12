"""
Notifications module with Windows toast notifications and Tkinter popup fallback.
Supports action buttons: Done, Snooze 10m, Snooze 1h, Open app.
"""

import logging
import tkinter as tk
from datetime import datetime, timedelta
from typing import Callable, Optional, Dict, List
import threading
import winsound

logger = logging.getLogger(__name__)

# Toast notification imports
try:
    from windows_toasts import Toast, ToastDisplayImage, ToastActivatedEventArgs, ToastDismissedEventArgs
    from windows_toasts import InteractableWindowsToaster, ToastButton, ToastInputTextBox
    from windows_toasts import ToastDuration, ToastScenario
    TOASTS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"windows-toasts not available: {e}")
    TOASTS_AVAILABLE = False


class NotificationAction:
    """Constants for notification action identifiers."""
    DONE = "done"
    SNOOZE_10M = "snooze_10m"
    SNOOZE_1H = "snooze_1h"
    OPEN_APP = "open_app"
    DISMISSED = "dismissed"


class PopupNotification(tk.Toplevel):
    """Custom popup notification window as fallback for Windows toasts."""

    # Track active popups to stack them
    _active_popups: List['PopupNotification'] = []

    def __init__(self, root: tk.Tk, task_id: int, title: str, notes: str = "",
                 due_time: Optional[datetime] = None, callbacks: Dict[str, Callable] = None):
        super().__init__(root)

        self.task_id = task_id
        self._callbacks = callbacks or {}
        self._dismissed = False

        # Window setup - no decorations, topmost
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg='#2d2d2d')

        # Calculate position (bottom-right, stacked)
        self._position_window()

        # Build UI
        self._create_widgets(title, notes, due_time)

        # Add to active popups
        PopupNotification._active_popups.append(self)

        # Play notification sound
        self._play_sound()

        # Auto-dismiss after 30 seconds if not interacted
        self._auto_dismiss_id = self.after(30000, self._on_dismissed)

        # Bind click to prevent accidental dismiss
        self.bind('<Enter>', lambda e: self._cancel_auto_dismiss())

    def _position_window(self):
        """Position window in bottom-right corner, stacked with other popups."""
        width = 350
        height = 140

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Stack offset based on number of active popups
        stack_offset = len(PopupNotification._active_popups) * (height + 10)

        x = screen_width - width - 20
        y = screen_height - height - 60 - stack_offset  # 60 for taskbar

        self.geometry(f"{width}x{height}+{x}+{y}")

    def _create_widgets(self, title: str, notes: str, due_time: Optional[datetime]):
        """Create the notification UI."""
        # Main frame with padding
        main = tk.Frame(self, bg='#2d2d2d', padx=15, pady=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Header with app name and close button
        header = tk.Frame(main, bg='#2d2d2d')
        header.pack(fill=tk.X)

        tk.Label(header, text="Checklist Reminder", font=("Segoe UI", 9),
                 fg='#888888', bg='#2d2d2d').pack(side=tk.LEFT)

        close_btn = tk.Label(header, text="×", font=("Segoe UI", 14),
                            fg='#888888', bg='#2d2d2d', cursor='hand2')
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind('<Button-1>', lambda e: self._on_dismissed())

        # Title
        tk.Label(main, text=title, font=("Segoe UI Semibold", 11),
                 fg='white', bg='#2d2d2d', anchor='w', wraplength=320).pack(fill=tk.X, pady=(8, 2))

        # Notes/due time
        info_text = ""
        if notes:
            info_text = notes[:100] + ("..." if len(notes) > 100 else "")
        if due_time:
            time_str = due_time.strftime("%I:%M %p")
            info_text = f"Due: {time_str}" + (f" - {info_text}" if info_text else "")

        if info_text:
            tk.Label(main, text=info_text, font=("Segoe UI", 9),
                     fg='#aaaaaa', bg='#2d2d2d', anchor='w', wraplength=320).pack(fill=tk.X)

        # Buttons frame
        btn_frame = tk.Frame(main, bg='#2d2d2d')
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        btn_style = {'font': ("Segoe UI", 9), 'bg': '#404040', 'fg': 'white',
                     'activebackground': '#505050', 'activeforeground': 'white',
                     'relief': 'flat', 'cursor': 'hand2', 'padx': 12, 'pady': 4}

        tk.Button(btn_frame, text="Done", command=self._on_done, **btn_style).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(btn_frame, text="10m", command=self._on_snooze_10m, **btn_style).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(btn_frame, text="1h", command=self._on_snooze_1h, **btn_style).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(btn_frame, text="Open", command=self._on_open, **btn_style).pack(side=tk.LEFT)

    def _play_sound(self):
        """Play notification sound."""
        try:
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except:
            pass

    def _cancel_auto_dismiss(self):
        """Cancel auto-dismiss when user hovers."""
        if hasattr(self, '_auto_dismiss_id'):
            self.after_cancel(self._auto_dismiss_id)

    def _close_popup(self):
        """Close the popup and reposition others."""
        if self in PopupNotification._active_popups:
            PopupNotification._active_popups.remove(self)
        self.destroy()
        # Reposition remaining popups
        for i, popup in enumerate(PopupNotification._active_popups):
            popup._reposition(i)

    def _reposition(self, index: int):
        """Reposition popup based on its index in the stack."""
        width = 350
        height = 140
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        stack_offset = index * (height + 10)
        x = screen_width - width - 20
        y = screen_height - height - 60 - stack_offset
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _trigger_callback(self, action: str):
        """Trigger a callback in a thread."""
        if action in self._callbacks:
            threading.Thread(
                target=self._callbacks[action],
                args=(self.task_id,),
                daemon=True
            ).start()

    def _on_done(self):
        self._trigger_callback(NotificationAction.DONE)
        self._close_popup()

    def _on_snooze_10m(self):
        self._trigger_callback(NotificationAction.SNOOZE_10M)
        self._close_popup()

    def _on_snooze_1h(self):
        self._trigger_callback(NotificationAction.SNOOZE_1H)
        self._close_popup()

    def _on_open(self):
        self._trigger_callback(NotificationAction.OPEN_APP)
        self._close_popup()

    def _on_dismissed(self):
        if not self._dismissed:
            self._dismissed = True
            self._trigger_callback(NotificationAction.DISMISSED)
            self._close_popup()


class NotificationManager:
    """Manages notifications with Windows toast or popup fallback."""

    APP_ID = "ChecklistReminder"

    def __init__(self, use_toast: bool = True):
        self._callbacks: Dict[str, Callable] = {}
        self._toaster = None
        self._paused_until: Optional[datetime] = None
        self._lock = threading.Lock()
        self._tk_root: Optional[tk.Tk] = None
        self._use_toast = use_toast

        if use_toast and TOASTS_AVAILABLE:
            try:
                self._toaster = InteractableWindowsToaster(self.APP_ID)
                logger.info("Toast notification manager initialized")
            except Exception as e:
                logger.error(f"Failed to initialize toaster: {e}")
                self._toaster = None

    def set_tk_root(self, root: tk.Tk):
        """Set the Tk root for popup notifications."""
        self._tk_root = root

    def set_use_toast(self, use_toast: bool):
        """Enable or disable Windows toast notifications."""
        self._use_toast = use_toast

    def set_callback(self, action: str, callback: Callable):
        """Set callback for a specific action."""
        self._callbacks[action] = callback

    def pause_notifications(self, duration_hours: Optional[float] = None, until: Optional[datetime] = None):
        """Pause notifications for a duration or until a specific time."""
        with self._lock:
            if until:
                self._paused_until = until
            elif duration_hours:
                self._paused_until = datetime.now() + timedelta(hours=duration_hours)
            logger.info(f"Notifications paused until {self._paused_until}")

    def resume_notifications(self):
        """Resume notifications."""
        with self._lock:
            self._paused_until = None
            logger.info("Notifications resumed")

    def is_paused(self) -> bool:
        """Check if notifications are currently paused."""
        with self._lock:
            if self._paused_until is None:
                return False
            if datetime.now() >= self._paused_until:
                self._paused_until = None
                return False
            return True

    def get_pause_end_time(self) -> Optional[datetime]:
        """Get when notifications will resume."""
        with self._lock:
            return self._paused_until

    def show_task_notification(self, task_id: int, title: str, notes: str = "",
                                due_time: Optional[datetime] = None) -> bool:
        """Show a task reminder notification."""
        if self.is_paused():
            logger.debug(f"Notifications paused, skipping notification for task {task_id}")
            return False

        # Try Windows toast first
        if self._use_toast and self._toaster:
            if self._show_toast_notification(task_id, title, notes, due_time):
                return True

        # Fallback to popup
        return self._show_popup_notification(task_id, title, notes, due_time)

    def _show_toast_notification(self, task_id: int, title: str, notes: str,
                                  due_time: Optional[datetime]) -> bool:
        """Show Windows toast notification."""
        try:
            toast = Toast()
            toast.text_fields = [title]

            if notes:
                toast.text_fields.append(notes[:200])

            if due_time:
                time_str = due_time.strftime("%I:%M %p")
                toast.text_fields.append(f"Due: {time_str}")

            toast.scenario = ToastScenario.Reminder
            toast.duration = ToastDuration.Long

            toast.AddAction(ToastButton("Done", f"{task_id}:{NotificationAction.DONE}"))
            toast.AddAction(ToastButton("Snooze 10m", f"{task_id}:{NotificationAction.SNOOZE_10M}"))
            toast.AddAction(ToastButton("Snooze 1h", f"{task_id}:{NotificationAction.SNOOZE_1H}"))
            toast.AddAction(ToastButton("Open", f"{task_id}:{NotificationAction.OPEN_APP}"))

            toast.on_activated = lambda args: self._handle_toast_activation(args)
            toast.on_dismissed = lambda args: self._handle_toast_dismissal(args, task_id)

            self._toaster.show_toast(toast)
            logger.info(f"Showed toast notification for task {task_id}: {title}")
            return True

        except Exception as e:
            logger.error(f"Failed to show toast notification: {e}")
            return False

    def _show_popup_notification(self, task_id: int, title: str, notes: str,
                                  due_time: Optional[datetime]) -> bool:
        """Show popup notification as fallback."""
        if not self._tk_root:
            logger.error("No Tk root set for popup notifications")
            return False

        try:
            # Must create popup on main thread
            self._tk_root.after(0, lambda: PopupNotification(
                self._tk_root, task_id, title, notes, due_time, self._callbacks
            ))
            logger.info(f"Showed popup notification for task {task_id}: {title}")
            return True
        except Exception as e:
            logger.error(f"Failed to show popup notification: {e}")
            return False

    def show_missed_tasks_summary(self, missed_count: int, task_titles: list) -> bool:
        """Show a summary notification for missed tasks."""
        if self.is_paused():
            return False

        title = f"Missed Reminders ({missed_count})"
        notes = ", ".join(task_titles[:3]) + ("..." if len(task_titles) > 3 else "")

        # Try toast first
        if self._use_toast and self._toaster:
            try:
                toast = Toast()
                toast.text_fields = [title, notes]
                toast.duration = ToastDuration.Long
                toast.AddAction(ToastButton("Open App", f"0:{NotificationAction.OPEN_APP}"))
                toast.on_activated = lambda args: self._handle_toast_activation(args)
                self._toaster.show_toast(toast)
                return True
            except:
                pass

        # Fallback to popup
        return self._show_popup_notification(0, title, notes, None)

    def show_simple_notification(self, title: str, message: str = "") -> bool:
        """Show a simple notification."""
        if self.is_paused():
            return False

        if self._use_toast and self._toaster:
            try:
                toast = Toast()
                toast.text_fields = [title]
                if message:
                    toast.text_fields.append(message)
                self._toaster.show_toast(toast)
                return True
            except:
                pass

        return self._show_popup_notification(0, title, message, None)

    def _handle_toast_activation(self, args):
        """Handle toast activation (button click)."""
        try:
            if hasattr(args, 'arguments') and args.arguments:
                parts = args.arguments.split(":", 1)
                if len(parts) == 2:
                    task_id = int(parts[0])
                    action = parts[1]
                    logger.info(f"Toast action: task_id={task_id}, action={action}")

                    if action in self._callbacks:
                        threading.Thread(
                            target=self._callbacks[action],
                            args=(task_id,),
                            daemon=True
                        ).start()
        except Exception as e:
            logger.error(f"Error handling toast activation: {e}")

    def _handle_toast_dismissal(self, args, task_id: int):
        """Handle toast dismissal."""
        try:
            if hasattr(args, 'reason'):
                logger.debug(f"Toast dismissed: task_id={task_id}, reason={args.reason}")

            if NotificationAction.DISMISSED in self._callbacks:
                threading.Thread(
                    target=self._callbacks[NotificationAction.DISMISSED],
                    args=(task_id,),
                    daemon=True
                ).start()
        except Exception as e:
            logger.error(f"Error handling toast dismissal: {e}")


def is_notification_support_available() -> bool:
    """Check if Windows toast notification support is available."""
    return TOASTS_AVAILABLE
