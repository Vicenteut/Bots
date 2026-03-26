"""Main message router — parses intent and executes actions."""

from datetime import datetime
from intent_parser import (
    parse_intent, INTENT_ADD_TASK, INTENT_COMPLETE_TASK, INTENT_LIST_TASKS,
    INTENT_WEEK_TASKS, INTENT_ADD_REMINDER, INTENT_LIST_REMINDERS,
    INTENT_ADD_NOTE, INTENT_SEARCH_NOTES, INTENT_LIST_NOTES,
    INTENT_TODAY, INTENT_STATS, INTENT_HELP, INTENT_DELETE_TASK,
    INTENT_CREATE_FOLDER, INTENT_ADD_TO_FOLDER, INTENT_VIEW_FOLDER,
    INTENT_SEARCH_FOLDER, INTENT_LIST_FOLDERS, INTENT_DELETE_FOLDER,
    INTENT_SEND_FILES, INTENT_ANALYZE_FOLDER, INTENT_UNKNOWN
)
from task_manager import (
    add_task, complete_task, delete_task, get_pending_tasks,
    get_week_tasks, get_stats
)
from note_manager import add_note, search_notes, get_recent_notes
from reminder_engine import add_reminder, get_user_reminders
from briefing_generator import generate_morning_briefing
from ai_handler import ask_ai, analyze_folder_contents
from database import get_db


def get_or_create_user(telegram_id, name=""):
    conn = get_db()
    user = conn.execute(
        "SELECT user_id, name FROM users WHERE telegram_id=?", (telegram_id,)
    ).fetchone()
    if user:
        conn.close()
        return user["user_id"], user["name"]

    cur = conn.execute(
        "INSERT INTO users (telegram_id, name) VALUES (?, ?)",
        (telegram_id, name)
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id, name


def save_conversation(user_id, role, content):
    conn = get_db()
    conn.execute(
        "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content[:2000])
    )
    # Keep only last 50 messages per user
    conn.execute(
        """DELETE FROM conversations WHERE msg_id NOT IN (
            SELECT msg_id FROM conversations WHERE user_id=?
            ORDER BY timestamp DESC LIMIT 50
        ) AND user_id=?""",
        (user_id, user_id)
    )
    conn.commit()
    conn.close()


def get_conversation_history(user_id, limit=6):
    conn = get_db()
    rows = conn.execute(
        """SELECT role, content FROM conversations
           WHERE user_id=? ORDER BY timestamp DESC LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def handle_message(telegram_id, user_name, text):
    """Process a user message and return response text."""
    user_id, name = get_or_create_user(telegram_id, user_name)
    if not name and user_name:
        conn = get_db()
        conn.execute("UPDATE users SET name=? WHERE user_id=?", (user_name, user_id))
        conn.commit()
        conn.close()
        name = user_name

    # Save user message
    save_conversation(user_id, "user", text)

    # Parse intent
    parsed = parse_intent(text)
    intent = parsed["intent"]
    entities = parsed.get("entities", {})

    response = ""

    if intent == INTENT_HELP:
        response = HELP_TEXT

    elif intent == INTENT_ADD_TASK:
        title = entities.get("title", text)
        due = entities.get("date")
        task_id = add_task(user_id, title, due_date=due)
        due_str = f" para el {due}" if due else ""
        response = f"Tarea creada{due_str}:\n  - {title}"

    elif intent == INTENT_COMPLETE_TASK:
        fragment = entities.get("title_fragment", "")
        if complete_task(user_id, title_fragment=fragment):
            response = f"Tarea completada: {fragment}"
        else:
            response = f"No encontre tarea con '{fragment}'. Escribe 'tareas' para ver tus pendientes."

    elif intent == INTENT_DELETE_TASK:
        fragment = entities.get("title_fragment", "")
        delete_task(user_id, title_fragment=fragment)
        response = f"Tarea eliminada: {fragment}"

    elif intent == INTENT_LIST_TASKS:
        tasks = get_pending_tasks(user_id)
        if tasks:
            lines = ["Tareas pendientes:\n"]
            for i, t in enumerate(tasks, 1):
                due = f" ({t['due_date']})" if t["due_date"] else ""
                priority = " (!)" if t["priority"] in ("alta", "high") else ""
                lines.append(f"{i}. {t['title']}{due}{priority}")
            response = "\n".join(lines)
        else:
            response = "No tienes tareas pendientes."

    elif intent == INTENT_WEEK_TASKS:
        tasks = get_week_tasks(user_id)
        if tasks:
            lines = ["Tareas de la semana:\n"]
            for t in tasks:
                lines.append(f"  - [{t['due_date']}] {t['title']}")
            response = "\n".join(lines)
        else:
            response = "No tienes tareas programadas para esta semana."

    elif intent == INTENT_ADD_REMINDER:
        r_text = entities.get("text", text)
        r_date = entities.get("date") or datetime.now().strftime("%Y-%m-%d")
        r_time = entities.get("time") or "09:00"
        remind_at = f"{r_date} {r_time}"
        add_reminder(user_id, r_text, remind_at)
        response = f"Recordatorio creado:\n  {r_text}\n  {remind_at}"

    elif intent == INTENT_LIST_REMINDERS:
        reminders = get_user_reminders(user_id)
        if reminders:
            lines = ["Recordatorios activos:\n"]
            for r in reminders:
                rec = f" (se repite {r['recurrence']})" if r["recurrence"] else ""
                lines.append(f"  - {r['remind_at']} — {r['text']}{rec}")
            response = "\n".join(lines)
        else:
            response = "No tienes recordatorios activos."

    elif intent == INTENT_ADD_NOTE:
        content = entities.get("content", text)
        category = entities.get("category")
        note_id = add_note(user_id, content, category)
        cat_str = f" [{category}]" if category else ""
        response = f"Nota guardada{cat_str}:\n  {content}"

    elif intent == INTENT_SEARCH_NOTES:
        query = entities.get("query", "")
        notes = search_notes(user_id, query=query)
        if notes:
            lines = [f"Notas sobre '{query}':\n"]
            for n in notes:
                cat = f" [{n['category']}]" if n["category"] else ""
                lines.append(f"  - {n['content'][:80]}{cat}")
            response = "\n".join(lines)
        else:
            response = f"No encontre notas sobre '{query}'."

    elif intent == INTENT_LIST_NOTES:
        notes = get_recent_notes(user_id)
        if notes:
            lines = ["Notas recientes:\n"]
            for n in notes:
                cat = f" [{n['category']}]" if n["category"] else ""
                date = n["created_at"][:10]
                lines.append(f"  - {n['content'][:80]}{cat} ({date})")
            response = "\n".join(lines)
        else:
            response = "No tienes notas guardadas."

    elif intent == INTENT_TODAY:
        response = generate_morning_briefing(user_id, name)

    elif intent == INTENT_STATS:
        stats = get_stats(user_id)
        response = (
            f"Estadisticas:\n\n"
            f"  Pendientes: {stats['pending']}\n"
            f"  Completadas hoy: {stats['completed_today']}\n"
            f"  Completadas esta semana: {stats['completed_week']}"
        )

    elif intent == INTENT_CREATE_FOLDER:
        from folder_manager import create_folder
        fname = entities.get("folder_name", "")
        folder_id, is_new = create_folder(user_id, fname)
        if is_new:
            response = f"Carpeta '{fname}' creada.\n\nPara agregar info: guardar en {fname}: tu contenido"
        else:
            response = f"La carpeta '{fname}' ya existe."

    elif intent == INTENT_ADD_TO_FOLDER:
        from folder_manager import add_to_folder
        fname = entities.get("folder_name", "")
        content = entities.get("content", "")
        add_to_folder(user_id, fname, content)
        response = f"Guardado en '{fname}':\n  {content}"

    elif intent == INTENT_VIEW_FOLDER:
        from folder_manager import get_folder_items
        fname = entities.get("folder_name", "")
        items = get_folder_items(user_id, fname)
        if items:
            lines = [f"Carpeta '{fname}' ({len(items)} items):\n"]
            for i, item in enumerate(items, 1):
                date = item["created_at"][:10]
                lines.append(f"{i}. {item['content'][:100]} ({date})")
            response = "\n".join(lines)
        else:
            response = f"La carpeta '{fname}' esta vacia o no existe."

    elif intent == INTENT_SEARCH_FOLDER:
        from folder_manager import search_in_folder
        fname = entities.get("folder_name", "")
        query = entities.get("query", "")
        items = search_in_folder(user_id, fname, query)
        if items:
            lines = [f"Resultados en '{fname}' para '{query}':\n"]
            for item in items:
                lines.append(f"  - {item['content'][:100]}")
            response = "\n".join(lines)
        else:
            response = f"No encontre nada con '{query}' en '{fname}'."

    elif intent == INTENT_LIST_FOLDERS:
        from folder_manager import list_folders
        folders = list_folders(user_id)
        if folders:
            lines = ["Tus carpetas:\n"]
            for f in folders:
                lines.append(f"  - {f['name']} ({f['item_count']} items)")
            response = "\n".join(lines)
        else:
            response = "No tienes carpetas. Crea una con: crear carpeta: nombre"

    elif intent == INTENT_DELETE_FOLDER:
        from folder_manager import delete_folder
        fname = entities.get("folder_name", "")
        delete_folder(user_id, fname)
        response = f"Carpeta '{fname}' eliminada."

    elif intent == INTENT_SEND_FILES:
        from folder_manager import get_folder_file_paths, get_folder_items
        fname = entities.get("folder_name", "")
        files = get_folder_file_paths(user_id, fname)
        if files:
            save_conversation(user_id, "assistant", f"Enviando {len(files)} archivo(s) de '{fname}'")
            return {
                "type": "send_files",
                "files": files,
                "text": f"Enviando {len(files)} archivo(s) de la carpeta '{fname}'..."
            }
        else:
            # Check if folder has text-only items
            items = get_folder_items(user_id, fname)
            if items:
                response = f"La carpeta '{fname}' tiene {len(items)} items pero ninguno es un archivo descargable.\nUsa 'ver {fname}' para ver el contenido."
            else:
                response = f"La carpeta '{fname}' esta vacia o no existe."

    elif intent == INTENT_ANALYZE_FOLDER:
        from folder_manager import read_folder_file_contents
        fname = entities.get("folder_name", "")
        file_contents = read_folder_file_contents(user_id, fname)
        if file_contents:
            readable = [f for f in file_contents if f["type"] in ("text", "text_item")]
            if readable:
                response = await analyze_folder_contents(fname, file_contents)
            else:
                response = f"La carpeta '{fname}' tiene archivos pero ninguno es de texto legible."
        else:
            response = f"La carpeta '{fname}' esta vacia o no existe."



    elif intent == INTENT_UNKNOWN:
        # AI fallback
        history = get_conversation_history(user_id)
        ai_result = await ask_ai(text, history)

        if ai_result["type"] == "action":
            action_data = ai_result["content"]
            response = await execute_ai_action(user_id, action_data)
        else:
            response = ai_result["content"]

    # Save assistant response
    save_conversation(user_id, "assistant", response)
    return response


async def execute_ai_action(user_id, action_data):
    """Execute an action returned by AI."""
    action = action_data.get("action", "")
    params = action_data.get("params", {})
    reply = action_data.get("reply", "Listo.")

    try:
        if action == "add_task":
            add_task(user_id, params.get("title", ""), due_date=params.get("due_date"),
                     priority=params.get("priority", "normal"))
        elif action == "complete_task":
            complete_task(user_id, title_fragment=params.get("title_fragment", ""))
        elif action == "add_reminder":
            add_reminder(user_id, params.get("text", ""), params.get("remind_at", ""))
        elif action == "add_note":
            add_note(user_id, params.get("content", ""), params.get("category"))
        elif action == "create_event":
            from calendar_manager import create_event
            event_id = create_event(
                params.get("title", "Evento"),
                params.get("start_dt", ""),
                params.get("end_dt"),
                params.get("location")
            )
            if not event_id:
                return "Error creando el evento en Google Calendar."
        elif action == "list_events":
            from calendar_manager import get_all_events, format_events_text
            date = params.get("date")
            events = get_all_events(date)
            if events:
                reply = reply + "\n\n" + format_events_text(events)
            else:
                reply = "No tienes eventos programados para esa fecha."
        elif action == "create_folder":
            from folder_manager import create_folder
            create_folder(user_id, params.get("folder_name", ""))
        elif action == "add_to_folder":
            from folder_manager import add_to_folder
            add_to_folder(user_id, params.get("folder_name", ""), params.get("content", ""))
        elif action == "view_folder":
            from folder_manager import get_folder_items
            items = get_folder_items(user_id, params.get("folder_name", ""))
            if items:
                lines = [reply + "\n"]
                for i, item in enumerate(items, 1):
                    lines.append(f"{i}. {item['content'][:100]}")
                reply = "\n".join(lines)
            else:
                reply = "Carpeta vacia o no existe."
        elif action == "search_folder":
            from folder_manager import search_in_folder
            items = search_in_folder(user_id, params.get("folder_name", ""), params.get("query", ""))
            if items:
                lines = [reply + "\n"]
                for item in items:
                    lines.append(f"  - {item['content'][:100]}")
                reply = "\n".join(lines)
            else:
                reply = "No encontre resultados."
        elif action == "list_folders":
            from folder_manager import list_folders
            folders = list_folders(user_id)
            if folders:
                lines = [reply + "\n"]
                for f in folders:
                    lines.append(f"  - {f['name']} ({f['item_count']} items)")
                reply = "\n".join(lines)
            else:
                reply = "No tienes carpetas."
    except Exception as e:
        return f"Error ejecutando accion: {str(e)[:100]}"

    return reply


HELP_TEXT = """Soy Armandito, tu asistente personal.

Puedo ayudarte con:

Tareas:
  - "agregar tarea: comprar leche"
  - "tarea: llamar al banco manana"
  - "completado comprar leche"
  - "tareas" — ver pendientes
  - "tareas de la semana"

Recordatorios:
  - "recuerdame llamar al doctor manana a las 10"
  - "recuerdame en 2 horas revisar el correo"
  - "recordatorios" — ver activos

Notas:
  - "nota: idea para proyecto X"
  - "guardar: el codigo es 4521"
  - "notas" — ver recientes
  - "notas sobre proyecto" — buscar

Carpetas:
  - "crear carpeta: Clientes"
  - "guardar en Clientes: Juan - 555-1234"
  - "ver Clientes" — ver contenido
  - "buscar en Clientes: Juan"
  - "envíame los archivos de Clientes" — descargar
  - "analiza la carpeta Clientes" — analisis con IA
  - "resumen financiero de Invoice" — reporte
  - "carpetas" — ver todas
  - "eliminar carpeta Clientes"
  - Tambien puedes enviar fotos/documentos con caption para guardarlos

Calendario:
  - "agenda cita con doctor manana a las 3"
  - "que reuniones tengo hoy"

Resumen:
  - "que tengo hoy" — briefing del dia
  - "stats" — estadisticas

Tambien puedes escribirme de forma natural y hare lo mejor para entenderte."""
