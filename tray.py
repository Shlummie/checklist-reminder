"""
System tray icon and menu using pystray.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional
from PIL import Image, ImageDraw

try:
    import pystray
    from pystray import MenuItem as item, Menu
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    logging.warning("pystray not available")

logger = logging.getLogger(__name__)


def create_checklist_icon(size: int = 64, color: str = "#4CAF50") -> Image.Image:
    """Create a simple checklist icon programmatically."""
    # Create a new image with transparency
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Parse color
    if color.startswith('#'):
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        fill_color = (r, g, b, 255)
    else:
        fill_color = (76, 175, 80, 255)  # Default green

    # Draw a rounded rectangle background
    margin = size // 8
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 8,
        fill=fill_color
    )

    # Draw checklist lines (white)
    line_color = (255, 255, 255, 255)
    line_width = max(2, size // 16)
    start_x = size // 4
    end_x = size - size // 4

    # Three horizontal lines representing tasks
    for i, y_offset in enumerate([0.35, 0.5, 0.65]):
        y = int(size * y_offset)
        # Small checkbox
        box_size = size // 10
        box_x = start_x
        draw.rectangle(
            [box_x, y - box_size//2, box_x + box_size, y + box_size//2],
            outline=line_color,
            width=1
        )
        # Checkmark in first box
        if i == 0:
            draw.line(
                [box_x + 2, y, box_x + box_size//2, y + box_size//2 - 2],
                fill=line_color,
                width=1
            )
            draw.line(
                [box_x + box_size//2, y + box_size//2 - 2, box_x + box_size - 2, y - box_size//2 + 2],
                fill=line_color,
                width=1
            )
        # Line after checkbox
        draw.line(
            [box_x + box_size + 4, y, end_x, y],
            fill=line_color,
            width=line_width
        )

    return image


class SystemTray:
    """System tray icon manager."""

    def __init__(self):
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_show_window: Optional[Callable] = None
        self._on_add_task: Optional[Callable] = None
        self._on_view_overdue: Optional[Callable] = None
        self._on_settings: Optional[Callable] = None
        self._on_quit: Optional[Callable] = None
        self._on_pause_notifications: Optional[Callable[[Optional[float], Optional[datetime]], None]] = None
        self._on_resume_notifications: Optional[Callable] = None

        # State
        self._is_paused = False
        self._pause_end: Optional[datetime] = None

    def set_callbacks(
        self,
        on_show_window: Callable = None,
        on_add_task: Callable = None,
        on_view_overdue: Callable = None,
        on_settings: Callable = None,
        on_quit: Callable = None,
        on_pause_notifications: Callable = None,
        on_resume_notifications: Callable = None
    ):
        """Set all callbacks at once."""
        self._on_show_window = on_show_window
        self._on_add_task = on_add_task
        self._on_view_overdue = on_view_overdue
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_pause_notifications = on_pause_notifications
        self._on_resume_notifications = on_resume_notifications

    def _create_menu(self) -> Menu:
        """Create the tray context menu."""

        def pause_1h():
            if self._on_pause_notifications:
                self._on_pause_notifications(1.0, None)
            self._is_paused = True
            self._pause_end = datetime.now() + timedelta(hours=1)

        def pause_8h():
            if self._on_pause_notifications:
                self._on_pause_notifications(8.0, None)
            self._is_paused = True
            self._pause_end = datetime.now() + timedelta(hours=8)

        def pause_until_tomorrow():
            # Tomorrow at 9 AM
            tomorrow = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
            tomorrow += timedelta(days=1)
            if self._on_pause_notifications:
                self._on_pause_notifications(None, tomorrow)
            self._is_paused = True
            self._pause_end = tomorrow

        def resume():
            if self._on_resume_notifications:
                self._on_resume_notifications()
            self._is_paused = False
            self._pause_end = None

        # Build pause submenu
        pause_menu = Menu(
            item('1 hour', lambda: pause_1h()),
            item('8 hours', lambda: pause_8h()),
            item('Until tomorrow 9 AM', lambda: pause_until_tomorrow()),
            Menu.SEPARATOR,
            item('Resume', lambda: resume(), enabled=lambda i: self._is_paused),
        )

        # Main menu - "Open Window" is default (bold) and triggers on double-click
        menu = Menu(
            item('Open Window', self._activate_window, default=True),
            Menu.SEPARATOR,
            item('Add Task...', lambda: self._on_add_task() if self._on_add_task else None),
            item('View Overdue', lambda: self._on_view_overdue() if self._on_view_overdue else None),
            Menu.SEPARATOR,
            item('Pause Notifications', pause_menu),
            item('Settings', lambda: self._on_settings() if self._on_settings else None),
            Menu.SEPARATOR,
            item('Quit', lambda: self._on_quit() if self._on_quit else None),
        )

        return menu

    def _activate_window(self, icon=None, item=None):
        """Activate/show the main window."""
        if self._on_show_window:
            self._on_show_window()

    def start(self):
        """Start the system tray icon."""
        if not PYSTRAY_AVAILABLE:
            logger.error("pystray not available, cannot start tray")
            return

        # Create icon image
        icon_image = create_checklist_icon()

        # Create the tray icon
        self._icon = pystray.Icon(
            name="ChecklistReminder",
            icon=icon_image,
            title="Checklist Reminder",
            menu=self._create_menu()
        )

        # Run in background thread
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

        logger.info("System tray started")

    def stop(self):
        """Stop the system tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                logger.error(f"Error stopping tray: {e}")
            self._icon = None
        logger.info("System tray stopped")

    def update_icon(self, has_overdue: bool = False):
        """Update the icon to indicate overdue tasks."""
        if self._icon:
            color = "#F44336" if has_overdue else "#4CAF50"  # Red if overdue, green otherwise
            self._icon.icon = create_checklist_icon(color=color)

    def update_pause_state(self, is_paused: bool, pause_end: Optional[datetime] = None):
        """Update the pause state for menu display."""
        self._is_paused = is_paused
        self._pause_end = pause_end

    def show_notification(self, title: str, message: str = ""):
        """Show a notification via the tray icon (fallback method)."""
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception as e:
                logger.error(f"Error showing tray notification: {e}")
