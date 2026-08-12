"""
Single instance enforcement using Windows named mutex and socket for IPC.
If another instance is already running, signals it to show the window and exits.
"""

import socket
import threading
import logging
import ctypes
from ctypes import wintypes

logger = logging.getLogger(__name__)

# Windows API constants
MUTEX_ALL_ACCESS = 0x1F0001
ERROR_ALREADY_EXISTS = 183

# Windows API functions
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

CreateMutexW = kernel32.CreateMutexW
CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
CreateMutexW.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

GetLastError = kernel32.GetLastError


class SingleInstance:
    """
    Ensures only one instance of the application runs at a time.
    Uses a Windows named mutex for detection and a local socket for IPC.
    """

    MUTEX_NAME = "ChecklistReminderApp_SingleInstance_Mutex"
    IPC_PORT = 51847  # Arbitrary port for IPC
    IPC_HOST = "127.0.0.1"

    def __init__(self, on_activate_callback=None):
        """
        Args:
            on_activate_callback: Function to call when another instance tries to start
        """
        self._mutex_handle = None
        self._is_first_instance = False
        self._ipc_server = None
        self._ipc_thread = None
        self._running = False
        self._on_activate = on_activate_callback

    def acquire(self) -> bool:
        """
        Try to acquire single instance lock.
        Returns True if this is the first instance, False otherwise.
        """
        # Try to create a named mutex
        self._mutex_handle = CreateMutexW(None, False, self.MUTEX_NAME)

        if self._mutex_handle:
            error = ctypes.get_last_error()
            if error == ERROR_ALREADY_EXISTS:
                # Another instance is running
                logger.info("Another instance is already running")
                CloseHandle(self._mutex_handle)
                self._mutex_handle = None
                self._is_first_instance = False
                return False
            else:
                # We are the first instance
                logger.info("First instance - acquired mutex")
                self._is_first_instance = True
                self._start_ipc_server()
                return True
        else:
            error = ctypes.get_last_error()
            logger.error(f"Failed to create mutex, error: {error}")
            # Assume we can run anyway
            self._is_first_instance = True
            return True

    def signal_existing_instance(self) -> bool:
        """
        Signal the existing instance to show its window.
        Returns True if signal was sent successfully.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2.0)
                sock.connect((self.IPC_HOST, self.IPC_PORT))
                sock.sendall(b"SHOW_WINDOW")
                logger.info("Signaled existing instance to show window")
                return True
        except (socket.error, socket.timeout) as e:
            logger.warning(f"Could not signal existing instance: {e}")
            return False

    def _start_ipc_server(self):
        """Start the IPC server to listen for signals from other instances."""
        self._running = True
        self._ipc_thread = threading.Thread(target=self._ipc_server_loop, daemon=True)
        self._ipc_thread.start()

    def _ipc_server_loop(self):
        """IPC server loop that listens for activation signals."""
        try:
            self._ipc_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ipc_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._ipc_server.bind((self.IPC_HOST, self.IPC_PORT))
            self._ipc_server.listen(1)
            self._ipc_server.settimeout(1.0)  # Allow periodic check for shutdown

            logger.info(f"IPC server listening on {self.IPC_HOST}:{self.IPC_PORT}")

            while self._running:
                try:
                    conn, addr = self._ipc_server.accept()
                    with conn:
                        conn.settimeout(1.0)
                        data = conn.recv(1024)
                        if data == b"SHOW_WINDOW":
                            logger.info("Received SHOW_WINDOW signal")
                            if self._on_activate:
                                self._on_activate()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        logger.error(f"IPC server error: {e}")
        except Exception as e:
            logger.error(f"Failed to start IPC server: {e}")
        finally:
            if self._ipc_server:
                try:
                    self._ipc_server.close()
                except:
                    pass

    def release(self):
        """Release the single instance lock and cleanup."""
        self._running = False

        if self._ipc_server:
            try:
                self._ipc_server.close()
            except:
                pass
            self._ipc_server = None

        if self._mutex_handle:
            CloseHandle(self._mutex_handle)
            self._mutex_handle = None
            logger.info("Released single instance mutex")

    @property
    def is_first_instance(self) -> bool:
        return self._is_first_instance
