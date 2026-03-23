"""
Shared SQLite database layer for tasks and reminders.
Used by both Claude and OpenAI agents.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "assistant.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT DEFAULT NULL,
            priority TEXT DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high')),
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            message TEXT DEFAULT '',
            triggered INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ─── Task operations ────────────────────────────────────────────────────────

def add_task(title: str, description: str = "", due_date: str = None, priority: str = "medium") -> dict:
    conn = get_connection()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO tasks (title, description, due_date, priority, status, created_at) VALUES (?,?,?,?,?,?)",
        (title, description, due_date, priority, "pending", now)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": task_id, "title": title, "description": description,
            "due_date": due_date, "priority": priority, "status": "pending"}


def list_tasks(status: str = None, priority: str = None) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task_status(task_id: int, status: str) -> dict:
    conn = get_connection()
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": f"Task {task_id} not found"}
    return dict(row)


def delete_task(task_id: int) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Task {task_id} not found"}
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"deleted": task_id, "title": row["title"]}


# ─── Reminder operations ─────────────────────────────────────────────────────

def set_reminder(title: str, remind_at: str, message: str = "") -> dict:
    conn = get_connection()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO reminders (title, remind_at, message, triggered, created_at) VALUES (?,?,?,0,?)",
        (title, remind_at, message, now)
    )
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": reminder_id, "title": title, "remind_at": remind_at, "message": message}


def list_reminders(include_triggered: bool = False) -> list[dict]:
    conn = get_connection()
    if include_triggered:
        rows = conn.execute("SELECT * FROM reminders ORDER BY remind_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE triggered = 0 ORDER BY remind_at"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_reminder(reminder_id: int) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT title FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Reminder {reminder_id} not found"}
    conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    return {"deleted": reminder_id, "title": row["title"]}


def check_due_reminders() -> list[dict]:
    """Return reminders that are due now and haven't been triggered yet."""
    conn = get_connection()
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE triggered = 0 AND remind_at <= ?", (now,)
    ).fetchall()
    if rows:
        ids = [r["id"] for r in rows]
        conn.execute(f"UPDATE reminders SET triggered = 1 WHERE id IN ({','.join('?'*len(ids))})", ids)
        conn.commit()
    conn.close()
    return [dict(r) for r in rows]


# Initialize on import
init_db()
