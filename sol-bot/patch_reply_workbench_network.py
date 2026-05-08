#!/usr/bin/env python3
"""Sprint 6 patch — add network_name column to reply_chats.

Minimal foundational change so future X-reply data can be tagged. UI badge wiring
is trivial later when there's actual X reply data (currently 100% Threads).
"""

import sys
import sqlite3
from pathlib import Path

DB = Path("/root/x-bot/sol-bot/reply_workbench.db")
PATH = "/root/x-bot/sol-bot/reply_workbench.py"

# 1) DB schema migration (idempotent)
if DB.exists():
    with sqlite3.connect(DB) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(reply_chats)").fetchall()]
        if "network_name" in cols:
            print("OK: reply_chats.network_name already exists")
        else:
            c.execute("ALTER TABLE reply_chats ADD COLUMN network_name TEXT DEFAULT 'threads'")
            c.execute("UPDATE reply_chats SET network_name='threads' WHERE network_name IS NULL")
            c.execute("CREATE INDEX IF NOT EXISTS idx_chats_network ON reply_chats(network_name)")
            print("OK: added network_name column to reply_chats + backfilled 'threads'")
else:
    print("WARN: reply_workbench.db does not exist yet — schema will gain column on first init")

# 2) Patch reply_workbench.py init_db() so fresh installs include the column
with open(PATH) as f:
    src = f.read()

if "network_name TEXT" in src:
    print("OK: reply_workbench.py init_db already has network_name")
    sys.exit(0)

OLD_SCHEMA = """          threads_reply_id TEXT,
          published_body TEXT,
          outcome TEXT,
          outcome_note TEXT
        );"""
NEW_SCHEMA = """          threads_reply_id TEXT,
          published_body TEXT,
          outcome TEXT,
          outcome_note TEXT,
          network_name TEXT DEFAULT 'threads'
        );"""

if OLD_SCHEMA not in src:
    print("ERROR: schema marker not found")
    sys.exit(1)

src = src.replace(OLD_SCHEMA, NEW_SCHEMA, 1)

# Add idempotent ALTER inside init_db so existing DBs without the column get it on import
INIT_TAIL = '        """)\n'
ALTER_BLOCK = '''        """)
        # Sprint 6 — idempotent ALTER for existing DBs
        try:
            c.execute("ALTER TABLE reply_chats ADD COLUMN network_name TEXT DEFAULT 'threads'")
        except Exception:
            pass
        try:
            c.execute("UPDATE reply_chats SET network_name='threads' WHERE network_name IS NULL")
        except Exception:
            pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_chats_network ON reply_chats(network_name)")
        except Exception:
            pass
'''
# Replace only the first occurrence inside init_db (the executescript closer)
src = src.replace(INIT_TAIL, ALTER_BLOCK, 1)

with open(PATH, "w") as f:
    f.write(src)
print("OK: reply_workbench.py init_db patched + ALTER injected")
