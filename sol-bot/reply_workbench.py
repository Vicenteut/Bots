#!/usr/bin/env python3
"""Reply Workbench - persistent reply chats with variant generation,
iteration, publish via Threads API, outcome tracking.

Replaces the stateless /api/replies/generate flow with a chat that the
dashboard can resume, iterate, and learn from.
"""

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import anthropic

from config import load_environment

load_environment()

BOT_DIR = Path(__file__).resolve().parent
DB_PATH = BOT_DIR / "data" / "replies.db"
TTL_SECONDS = 24 * 60 * 60

REPLY_TYPES = [
    ("DATO_CONTRARIO",     "Counter-fact"),
    ("CONEXION_MACRO",     "Macro link"),
    ("PREGUNTA_RETORICA",  "Rhetorical Q"),
    ("CONTEXTO_HISTORICO", "Historical"),
    ("OPERADOR",           "Operator"),
]
TYPE_LABEL = dict(REPLY_TYPES)

WORKBENCH_SYSTEM = """Eres el analista detras de @napoleotics. Vas a redactar DOS variantes
de reply para un post que respondio a Sol. Una marcada "recommended", otra alternativa.

Las dos deben ser de tipos DISTINTOS de esta lista:
- DATO_CONTRARIO: aporta un dato que matiza o contradice
- CONEXION_MACRO: conecta con un evento macro que nadie menciono
- PREGUNTA_RETORICA: pregunta que hace pensar
- CONTEXTO_HISTORICO: paralelo historico relevante
- OPERADOR: dato de mercado/trading que complementa

REGLAS DURAS:
- Max 220 caracteres cada variante
- Sin hashtags, sin emojis (max 1 si es necesario)
- NUNCA empieces con "Interesante", "Buen punto", "Gran reflexion"
- Tono: seguro pero no arrogante, dry, contrarian
- Aporta VALOR, no halagues
- Espanol natural, contracciones permitidas
- No em-dashes

Output EXACTO en JSON valido (nada mas):
{
  "variants": [
    {"type": "TIPO_RECOMMENDED", "body": "...", "recommended": true},
    {"type": "TIPO_ALT",         "body": "...", "recommended": false}
  ]
}
"""

ITERATE_SYSTEM = """Eres el analista detras de @napoleotics. Recibes un draft de reply
y una instruccion del usuario para refinarlo. Devuelve SOLO el reply revisado,
sin comentarios, sin JSON, sin prefijos. Maximo 220 caracteres.
Aplica estas reglas: sin hashtags, sin "Interesante", tono dry, espanol natural."""

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


# DB helpers ---------------------------------------------------------

def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    """Idempotent schema init - safe to call on every import."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS reply_chats (
          id TEXT PRIMARY KEY,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('open','published','discarded','expired')),
          replier_handle TEXT NOT NULL,
          orig_post_text TEXT,
          orig_post_url TEXT,
          their_reply TEXT NOT NULL,
          context_extra TEXT,
          variants_json TEXT,
          iterations_json TEXT,
          chosen_variant INTEGER,
          published_at INTEGER,
          threads_reply_id TEXT,
          published_body TEXT,
          outcome TEXT,
          outcome_note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_chats_status ON reply_chats(status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_chats_published ON reply_chats(published_at);
        CREATE TABLE IF NOT EXISTS reply_analytics (
          threads_reply_id TEXT NOT NULL,
          bucket TEXT NOT NULL,
          snapshot_at INTEGER NOT NULL,
          likes INTEGER DEFAULT 0,
          replies INTEGER DEFAULT 0,
          views INTEGER DEFAULT 0,
          reposts INTEGER DEFAULT 0,
          PRIMARY KEY(threads_reply_id, bucket)
        );
        """)


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k in ("variants_json", "iterations_json"):
        out_key = k.replace("_json", "")
        if d.get(k):
            try:
                d[out_key] = json.loads(d[k])
            except Exception:
                d[out_key] = None
        else:
            d[out_key] = [] if k == "iterations_json" else None
        d.pop(k, None)
    return d


# Public CRUD --------------------------------------------------------

def list_chats(status: Optional[str] = None) -> list:
    init_db()
    with _conn() as c:
        if status == "open":
            rows = c.execute(
                "SELECT * FROM reply_chats WHERE status='open' ORDER BY created_at DESC"
            ).fetchall()
        elif status == "done":
            rows = c.execute(
                "SELECT * FROM reply_chats WHERE status!='open' "
                "ORDER BY COALESCE(published_at, created_at) DESC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM reply_chats ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_chat(chat_id: str) -> Optional[dict]:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM reply_chats WHERE id=?", (chat_id,)).fetchone()
    return _row_to_dict(row)


def create_chat(orig_post: str, replier: str, their_reply: str,
                context_extra: str = "", orig_url: str = "") -> dict:
    init_db()
    cid = "RC-" + uuid.uuid4().hex[:8].upper()
    now = int(time.time())
    if not replier.startswith("@"):
        replier = "@" + replier.lstrip("@")
    with _conn() as c:
        c.execute("""
            INSERT INTO reply_chats(id, created_at, expires_at, status,
              replier_handle, orig_post_text, orig_post_url, their_reply,
              context_extra, variants_json, iterations_json)
            VALUES(?, ?, ?, 'open', ?, ?, ?, ?, ?, NULL, '[]')
        """, (cid, now, now + TTL_SECONDS, replier,
              (orig_post or "").strip(), (orig_url or "").strip(),
              (their_reply or "").strip(), (context_extra or "").strip()))
    return get_chat(cid)


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"```json\s*|```\s*", "", raw).strip()
    return json.loads(cleaned)


def generate_variants(chat_id: str, model_override: str = "") -> dict:
    """Call Claude, persist 2 variants on the chat row."""
    chat = get_chat(chat_id)
    if not chat:
        raise ValueError("chat not found: " + chat_id)
    if chat["status"] != "open":
        raise ValueError("chat is " + chat["status"] + ", cannot regenerate")

    user_msg = (
        "Sol post original:\n" + (chat["orig_post_text"] or "") + "\n\n"
        "Replier: " + chat["replier_handle"] + "\n"
        "Su reply:\n" + chat["their_reply"] + "\n\n"
    )
    if chat.get("context_extra"):
        user_msg += "Contexto extra:\n" + chat["context_extra"] + "\n\n"
    user_msg += "Genera las 2 variantes ahora."

    model = model_override or DEFAULT_MODEL
    response = _get_client().messages.create(
        model=model,
        max_tokens=600,
        system=WORKBENCH_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text
    parsed = _extract_json(raw)
    variants = parsed.get("variants", [])[:2]
    for v in variants:
        v["typeLabel"] = TYPE_LABEL.get(v.get("type", ""), v.get("type", ""))
    with _conn() as c:
        c.execute("UPDATE reply_chats SET variants_json=? WHERE id=?",
                  (json.dumps(variants, ensure_ascii=False), chat_id))
    return {"variants": variants, "model_used": model}


def iterate(chat_id: str, user_msg: str, model_override: str = "") -> dict:
    """Append a user message + Sol-refined reply to the iteration history."""
    chat = get_chat(chat_id)
    if not chat:
        raise ValueError("chat not found: " + chat_id)
    if chat["status"] != "open":
        raise ValueError("chat is " + chat["status"] + ", cannot iterate")

    iters = chat.get("iterations") or []
    last_sol = next((i["body"] for i in reversed(iters) if i.get("role") == "sol"), None)
    if last_sol is None:
        idx = chat.get("chosen_variant")
        if idx is None and chat.get("variants"):
            idx = 0
        if chat.get("variants") and idx is not None:
            last_sol = chat["variants"][idx].get("body", "")
        else:
            last_sol = ""

    iters.append({"role": "me", "body": user_msg.strip(), "ts": int(time.time())})

    prompt = (
        "Draft actual:\n" + last_sol + "\n\n"
        "Instruccion del usuario: " + user_msg.strip() + "\n\n"
        "Devuelve solo el reply revisado."
    )
    model = model_override or DEFAULT_MODEL
    response = _get_client().messages.create(
        model=model,
        max_tokens=300,
        system=ITERATE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    refined = response.content[0].text.strip().strip('"').strip()
    iters.append({"role": "sol", "body": refined, "ts": int(time.time())})

    with _conn() as c:
        c.execute("UPDATE reply_chats SET iterations_json=? WHERE id=?",
                  (json.dumps(iters, ensure_ascii=False), chat_id))
    return {"refined": refined, "iterations": iters, "model_used": model}


def set_chosen_variant(chat_id: str, idx: int) -> dict:
    init_db()
    with _conn() as c:
        c.execute("UPDATE reply_chats SET chosen_variant=? WHERE id=?",
                  (int(idx), chat_id))
    return get_chat(chat_id)


def publish(chat_id: str) -> dict:
    """Publish the current chosen reply via threads_publisher.publish_reply."""
    from threads_publisher import publish_reply  # late import: avoids loading on dashboard boot

    chat = get_chat(chat_id)
    if not chat:
        raise ValueError("chat not found: " + chat_id)
    if chat["status"] != "open":
        raise ValueError("chat is " + chat["status"] + ", cannot publish")

    iters = chat.get("iterations") or []
    last_sol = next((i["body"] for i in reversed(iters) if i.get("role") == "sol"), None)
    if last_sol:
        body = last_sol
    else:
        idx = chat.get("chosen_variant")
        if idx is None:
            raise ValueError("no variant chosen and no iteration to publish")
        body = chat["variants"][idx]["body"]

    reply_to = _extract_post_id(chat.get("orig_post_url") or "")
    if not reply_to:
        raise ValueError("orig_post_url with a Threads post ID is required to publish a reply")

    threads_reply_id = publish_reply(body, reply_to_id=reply_to)
    if not threads_reply_id:
        raise RuntimeError("threads_publisher.publish_reply returned no ID")

    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE reply_chats SET status='published', published_at=?, "
            "threads_reply_id=?, published_body=? WHERE id=?",
            (now, threads_reply_id, body, chat_id)
        )
    return get_chat(chat_id)


def _extract_post_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if not s:
        return ""
    if s.isdigit():
        return s
    m = re.search(r"/post/([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    return ""


def close_chat(chat_id: str, reason: str = "discarded") -> dict:
    if reason not in ("discarded", "expired"):
        reason = "discarded"
    with _conn() as c:
        c.execute("UPDATE reply_chats SET status=? WHERE id=? AND status='open'",
                  (reason, chat_id))
    return get_chat(chat_id)


def mark_outcome(chat_id: str, useful: bool, note: str = "") -> dict:
    val = "useful" if useful else "failed"
    with _conn() as c:
        c.execute("UPDATE reply_chats SET outcome=?, outcome_note=? WHERE id=?",
                  (val, (note or "").strip(), chat_id))
    return get_chat(chat_id)


def get_analytics(chat_id: str) -> dict:
    chat = get_chat(chat_id)
    if not chat or not chat.get("threads_reply_id"):
        return {"buckets": {}}
    with _conn() as c:
        rows = c.execute(
            "SELECT bucket, snapshot_at, likes, replies, views, reposts "
            "FROM reply_analytics WHERE threads_reply_id=?",
            (chat["threads_reply_id"],)
        ).fetchall()
    return {"buckets": {r["bucket"]: dict(r) for r in rows}}


def auto_expire() -> int:
    init_db()
    now = int(time.time())
    with _conn() as c:
        cur = c.execute(
            "UPDATE reply_chats SET status='expired' WHERE status='open' AND expires_at < ?",
            (now,)
        )
        return cur.rowcount


# CLI ----------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        print("[OK] DB initialized at " + str(DB_PATH))
    elif cmd == "auto_expire":
        n = auto_expire()
        print("[OK] expired " + str(n) + " chat(s)")
    elif cmd == "list":
        print(json.dumps(list_chats(), indent=2, ensure_ascii=False))
    else:
        print("unknown command: " + cmd)
        sys.exit(1)
