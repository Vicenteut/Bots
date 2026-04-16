from database import get_db


def add_note(user_id, content, category=None, tags=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO notes (user_id, content, category, tags) VALUES (?, ?, ?, ?)",
        (user_id, content, category, tags)
    )
    note_id = cur.lastrowid
    conn.commit()
    conn.close()
    return note_id


def search_notes(user_id, query=None, category=None, limit=10):
    conn = get_db()
    conditions = ["user_id=?"]
    params = [user_id]

    if query:
        conditions.append("lower(content) LIKE ?")
        params.append(f"%{query.lower()}%")
    if category:
        conditions.append("lower(category) LIKE ?")
        params.append(f"%{category.lower()}%")

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"""SELECT note_id, content, category, tags, created_at
            FROM notes WHERE {where}
            ORDER BY created_at DESC LIMIT ?""",
        params + [limit]
    ).fetchall()
    conn.close()
    return rows


def get_recent_notes(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        """SELECT note_id, content, category, tags, created_at
           FROM notes WHERE user_id=?
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows


def delete_note(user_id, note_id):
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE note_id=? AND user_id=?", (note_id, user_id))
    conn.commit()
    conn.close()


def get_categories(user_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT DISTINCT category, COUNT(*) as cnt
           FROM notes WHERE user_id=? AND category IS NOT NULL
           GROUP BY category ORDER BY cnt DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows
