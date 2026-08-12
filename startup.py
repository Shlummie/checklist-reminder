"""
Windows startup registration using the registry.

Uses HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
This approach:
- Does NOT require admin privileges
- Applies only to the current user
- Is the standard way for user-level startup apps
"""

import logging
import sys
import winreg
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Registry key for current user startup applications
REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ChecklistReminder"


def get_app_executable_path() -> str:
    """
    Get the path to run the application.
    Handles both script execution and frozen (PyInstaller) execution.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return sys.executable
    else:
        # Running as script - use pythonw to avoid console window
        python_path = sys.executable
        # Try to use pythonw.exe if available
        pythonw_path = Path(python_path).parent / "pythonw.exe"
        if pythonw_path.exists():
            python_path = str(pythonw_path)

        script_path = Path(__file__).parent / "main.py"
        return f'"{python_path}" "{script_path}"'


def is_startup_enabled() -> bool:
    """Check if the application is set to run on startup."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return bool(value)
            except FileNotFoundError:
                return False
    except Exception as e:
        logger.error(f"Error checking startup status: {e}")
        return False


def enable_startup() -> bool:
    """Enable the application to run on Windows startup."""
    try:
        command = get_app_executable_path()

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)

        logger.info(f"Enabled startup: {command}")
        return True
    except Exception as e:
        logger.error(f"Failed to enable startup: {e}")
        return False


def disable_startup() -> bool:
    """Disable the application from running on Windows startup."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Disabled startup")
                return True
            except FileNotFoundError:
                # Already not in startup
                logger.debug("Startup entry not found (already disabled)")
                return True
    except Exception as e:
        logger.error(f"Failed to disable startup: {e}")
        return False


def set_startup_enabled(enabled: bool) -> bool:
    """Set whether the application should run on startup."""
    if enabled:
        return enable_startup()
    else:
        return disable_startup()


def get_current_startup_command() -> Optional[str]:
    """Get the current startup command if one exists."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return value
            except FileNotFoundError:
                return None
    except Exception as e:
        logger.error(f"Error getting startup command: {e}")
        return None
