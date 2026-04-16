from database import get_db
from datetime import datetime, timedelta
import re


def add_reminder(user_id, text, remind_at, task_id=None, recurrence=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO reminders (user_id, task_id, text, remind_at, recurrence)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, task_id, text, remind_at, recurrence)
    )
    reminder_id = cur.lastrowid
    conn.commit()
    conn.close()
    return reminder_id


def get_pending_reminders():
    """Get all reminders that should fire now (within the last 2 minutes)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_db()
    rows = conn.execute(
        """SELECT r.reminder_id, r.user_id, r.text, r.remind_at, r.recurrence,
                  u.telegram_id, u.name
           FROM reminders r
           JOIN users u ON r.user_id = u.user_id
           WHERE r.sent=0 AND r.remind_at <= ?
           ORDER BY r.remind_at""",
        (now,)
    ).fetchall()
    conn.close()
    return rows


def mark_sent(reminder_id):
    conn = get_db()
    conn.execute("UPDATE reminders SET sent=1 WHERE reminder_id=?", (reminder_id,))
    conn.commit()
    conn.close()


def handle_recurrence(reminder):
    """If reminder is recurring, create the next one."""
    if not reminder["recurrence"]:
        return

    recurrence = reminder["recurrence"]
    current = datetime.strptime(reminder["remind_at"], "%Y-%m-%d %H:%M")

    if recurrence == "daily":
        next_at = current + timedelta(days=1)
    elif recurrence == "weekly":
        next_at = current + timedelta(weeks=1)
    elif recurrence == "monthly":
        next_at = current.replace(month=current.month + 1) if current.month < 12 else current.replace(year=current.year + 1, month=1)
    else:
        return

    add_reminder(
        reminder["user_id"], reminder["text"],
        next_at.strftime("%Y-%m-%d %H:%M"),
        reminder["task_id"] if "task_id" in reminder.keys() else None,
        recurrence
    )


def get_user_reminders(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        """SELECT reminder_id, text, remind_at, recurrence
           FROM reminders WHERE user_id=? AND sent=0
           ORDER BY remind_at LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows


def cancel_reminder(user_id, reminder_id=None, text_fragment=None):
    conn = get_db()
    if reminder_id:
        conn.execute(
            "DELETE FROM reminders WHERE reminder_id=? AND user_id=?",
            (reminder_id, user_id)
        )
    elif text_fragment:
        conn.execute(
            """DELETE FROM reminders WHERE user_id=? AND sent=0
               AND lower(text) LIKE ? LIMIT 1""",
            (user_id, f"%{text_fragment.lower()}%")
        )
    conn.commit()
    conn.close()
