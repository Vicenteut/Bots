from tz_helper import now_bz
from database import get_db
from datetime import datetime, timedelta


def add_task(user_id, title, due_date=None, priority="normal", category=None, description=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO tasks (user_id, title, description, category, priority, due_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, title, description, category, priority, due_date)
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def complete_task(user_id, task_id=None, title_fragment=None):
    conn = get_db()
    if task_id:
        conn.execute(
            """UPDATE tasks SET status='completed', completed_at=datetime('now')
               WHERE task_id=? AND user_id=?""",
            (task_id, user_id)
        )
    elif title_fragment:
        conn.execute(
            """UPDATE tasks SET status='completed', completed_at=datetime('now')
               WHERE user_id=? AND status='pending'
               AND lower(title) LIKE ?
               LIMIT 1""",
            (user_id, f"%{title_fragment.lower()}%")
        )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def delete_task(user_id, task_id=None, title_fragment=None):
    conn = get_db()
    if task_id:
        conn.execute("DELETE FROM tasks WHERE task_id=? AND user_id=?", (task_id, user_id))
    elif title_fragment:
        conn.execute(
            """DELETE FROM tasks WHERE user_id=? AND status='pending'
               AND lower(title) LIKE ? LIMIT 1""",
            (user_id, f"%{title_fragment.lower()}%")
        )
    conn.commit()
    conn.close()


def get_pending_tasks(user_id, limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT task_id, title, category, priority, due_date, created_at
           FROM tasks WHERE user_id=? AND status='pending'
           ORDER BY
             CASE WHEN due_date IS NOT NULL THEN 0 ELSE 1 END,
             due_date ASC,
             CASE priority WHEN 'alta' THEN 0 WHEN 'high' THEN 0
                           WHEN 'normal' THEN 1 ELSE 2 END
           LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows


def get_tasks_for_date(user_id, date_str):
    conn = get_db()
    rows = conn.execute(
        """SELECT task_id, title, category, priority, due_date
           FROM tasks WHERE user_id=? AND status='pending' AND due_date=?
           ORDER BY priority""",
        (user_id, date_str)
    ).fetchall()
    conn.close()
    return rows


def get_overdue_tasks(user_id):
    today = now_bz().strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute(
        """SELECT task_id, title, due_date, priority
           FROM tasks WHERE user_id=? AND status='pending'
           AND due_date IS NOT NULL AND due_date < ?
           ORDER BY due_date""",
        (user_id, today)
    ).fetchall()
    conn.close()
    return rows


def get_week_tasks(user_id):
    today = now_bz()
    end = today + timedelta(days=7)
    conn = get_db()
    rows = conn.execute(
        """SELECT task_id, title, category, priority, due_date
           FROM tasks WHERE user_id=? AND status='pending'
           AND due_date BETWEEN ? AND ?
           ORDER BY due_date""",
        (user_id, today.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    ).fetchall()
    conn.close()
    return rows


def get_stats(user_id):
    conn = get_db()
    pending = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='pending'", (user_id,)
    ).fetchone()[0]
    completed_today = conn.execute(
        """SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='completed'
           AND date(completed_at)=date('now')""", (user_id,)
    ).fetchone()[0]
    completed_week = conn.execute(
        """SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='completed'
           AND completed_at >= datetime('now', '-7 days')""", (user_id,)
    ).fetchone()[0]
    conn.close()
    return {"pending": pending, "completed_today": completed_today, "completed_week": completed_week}
