# Checklist Reminder

A local Windows checklist and reminder application built with Python, Tkinter, SQLite, desktop toasts, and a system-tray controller. It is designed for recurring tasks that should remain visible until they are actually completed.

## Features

- Create, edit, complete, restore, and delete checklist items.
- Schedule one-time or recurring reminders.
- Detect reminders missed while the application was closed.
- Keep local task state in SQLite under the current user's profile.
- Run in the notification area and reopen the main window from the tray.
- Enforce a single running instance.
- Optionally register startup through the current-user Windows registry key.

## Architecture

```text
Tkinter UI -> SQLite data layer -> scheduler -> Windows toast notifications
     |                                  |
     +-> tray controller                +-> missed/recurring calculation
```

Important modules:

- `main.py` — application bootstrap and lifecycle.
- `ui.py` — checklist and reminder interface.
- `db.py` — schema and persistence.
- `scheduler.py` — due-time and recurrence processing.
- `notifications.py` — Windows toast adapter.
- `tray.py`, `single_instance.py`, `startup.py` — Windows integration.

## Install and run

Requirements: Windows 10/11 and Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`launch.bat` starts the same application without requiring a terminal command.

## Data and privacy

The database is local and is not synced by this project. It can contain task names, notes, and schedules, so treat it as personal data and include it in backups according to your own retention policy. Database files, virtual environments, and caches are excluded from this repository.

Startup registration is per-user and reversible from the application. Toast delivery can be affected by Windows Focus Assist and notification settings.

## Limitations

- Windows-only notification and startup integration.
- No account, cloud sync, team sharing, or mobile client.
- The scheduler runs only while the application is active; overdue items are reconciled on the next launch.

## License

MIT. Python packages named in `requirements.txt` retain their upstream licenses.
