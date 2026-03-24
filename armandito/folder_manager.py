"""Folder system — organize information in named folders."""

from database import get_db


def create_folder(user_id, name):
    conn = get_db()
    # Check if folder already exists
    existing = conn.execute(
        "SELECT folder_id FROM folders WHERE user_id=? AND lower(name)=?",
        (user_id, name.lower())
    ).fetchone()
    if existing:
        conn.close()
        return existing["folder_id"], False  # already exists

    cur = conn.execute(
        "INSERT INTO folders (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    folder_id = cur.lastrowid
    conn.commit()
    conn.close()
    return folder_id, True  # newly created


def add_to_folder(user_id, folder_name, content, title=None):
    conn = get_db()
    folder = conn.execute(
        "SELECT folder_id FROM folders WHERE user_id=? AND lower(name)=?",
        (user_id, folder_name.lower())
    ).fetchone()

    if not folder:
        # Auto-create folder
        cur = conn.execute(
            "INSERT INTO folders (user_id, name) VALUES (?, ?)",
            (user_id, folder_name)
        )
        folder_id = cur.lastrowid
        conn.commit()
    else:
        folder_id = folder["folder_id"]

    cur = conn.execute(
        "INSERT INTO folder_items (folder_id, user_id, title, content) VALUES (?, ?, ?, ?)",
        (folder_id, user_id, title, content)
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def get_folder_items(user_id, folder_name, limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT fi.item_id, fi.title, fi.content, fi.created_at
           FROM folder_items fi
           JOIN folders f ON fi.folder_id = f.folder_id
           WHERE fi.user_id=? AND lower(f.name)=?
           ORDER BY fi.created_at DESC LIMIT ?""",
        (user_id, folder_name.lower(), limit)
    ).fetchall()
    conn.close()
    return rows


def search_in_folder(user_id, folder_name, query):
    conn = get_db()
    rows = conn.execute(
        """SELECT fi.item_id, fi.title, fi.content, fi.created_at
           FROM folder_items fi
           JOIN folders f ON fi.folder_id = f.folder_id
           WHERE fi.user_id=? AND lower(f.name)=?
           AND (lower(fi.content) LIKE ? OR lower(fi.title) LIKE ?)
           ORDER BY fi.created_at DESC""",
        (user_id, folder_name.lower(), f"%{query.lower()}%", f"%{query.lower()}%")
    ).fetchall()
    conn.close()
    return rows


def list_folders(user_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT f.name, COUNT(fi.item_id) as item_count
           FROM folders f
           LEFT JOIN folder_items fi ON f.folder_id = fi.folder_id
           WHERE f.user_id=?
           GROUP BY f.folder_id
           ORDER BY f.name""",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def delete_folder_item(user_id, folder_name, item_id=None, content_fragment=None):
    conn = get_db()
    if item_id:
        conn.execute(
            """DELETE FROM folder_items WHERE item_id=? AND user_id=?""",
            (item_id, user_id)
        )
    elif content_fragment:
        conn.execute(
            """DELETE FROM folder_items WHERE user_id=? AND folder_id IN (
                SELECT folder_id FROM folders WHERE user_id=? AND lower(name)=?
            ) AND lower(content) LIKE ? LIMIT 1""",
            (user_id, user_id, folder_name.lower(), f"%{content_fragment.lower()}%")
        )
    conn.commit()
    conn.close()


def delete_folder(user_id, folder_name):
    conn = get_db()
    folder = conn.execute(
        "SELECT folder_id FROM folders WHERE user_id=? AND lower(name)=?",
        (user_id, folder_name.lower())
    ).fetchone()
    if folder:
        conn.execute("DELETE FROM folder_items WHERE folder_id=?", (folder["folder_id"],))
        conn.execute("DELETE FROM folders WHERE folder_id=?", (folder["folder_id"],))
        conn.commit()
    conn.close()
