import re
from datetime import datetime, timedelta

# Intent types
INTENT_ADD_TASK = "add_task"
INTENT_COMPLETE_TASK = "complete_task"
INTENT_LIST_TASKS = "list_tasks"
INTENT_WEEK_TASKS = "week_tasks"
INTENT_ADD_REMINDER = "add_reminder"
INTENT_LIST_REMINDERS = "list_reminders"
INTENT_ADD_NOTE = "add_note"
INTENT_SEARCH_NOTES = "search_notes"
INTENT_LIST_NOTES = "list_notes"
INTENT_TODAY = "today_summary"
INTENT_STATS = "stats"
INTENT_HELP = "help"
INTENT_DELETE_TASK = "delete_task"
INTENT_CREATE_FOLDER = "create_folder"
INTENT_ADD_TO_FOLDER = "add_to_folder"
INTENT_VIEW_FOLDER = "view_folder"
INTENT_SEARCH_FOLDER = "search_folder"
INTENT_LIST_FOLDERS = "list_folders"
INTENT_DELETE_FOLDER = "delete_folder"
INTENT_UNKNOWN = "unknown"

# Day mappings (Spanish)
DAYS_ES = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6
}


def normalize(text):
    return text.strip().lower()


def parse_date(text):
    """Extract date from natural language (Spanish)."""
    now = datetime.now()
    t = normalize(text)

    # "hoy"
    if "hoy" in t:
        return now.strftime("%Y-%m-%d")

    # "mañana" / "manana"
    if "mañana" in t or "manana" in t:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # "pasado mañana"
    if "pasado" in t and ("mañana" in t or "manana" in t):
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")

    # Day of week
    for day_name, day_num in DAYS_ES.items():
        if day_name in t:
            days_ahead = day_num - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # "en X días/horas"
    m = re.search(r"en\s+(\d+)\s+(día|dias|día|horas?|hora)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "hora" in unit:
            return (now + timedelta(hours=n)).strftime("%Y-%m-%d")
        else:
            return (now + timedelta(days=n)).strftime("%Y-%m-%d")

    # Explicit date dd/mm or dd-mm
    m = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def parse_time(text):
    """Extract time from natural language."""
    t = normalize(text)

    # "a las 3pm", "a las 15:00", "a las 3:30 pm"
    m = re.search(r"(?:a las?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        if ampm and ("pm" in ampm or "p.m" in ampm) and hour < 12:
            hour += 12
        elif ampm and ("am" in ampm or "a.m" in ampm) and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return f"{hour:02d}:{minute:02d}"

    # "en X horas/minutos"
    m = re.search(r"en\s+(\d+)\s+(hora|horas|minuto|minutos|min)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        now = datetime.now()
        if "min" in unit:
            target = now + timedelta(minutes=n)
        else:
            target = now + timedelta(hours=n)
        return target.strftime("%H:%M")

    return None


def parse_intent(text):
    """Parse user message into intent + entities."""
    t = normalize(text)
    result = {"raw": text, "intent": INTENT_UNKNOWN, "entities": {}}

    # Help
    if t in ("ayuda", "help", "/help", "/start", "que puedes hacer", "qué puedes hacer"):
        result["intent"] = INTENT_HELP
        return result

    # Stats
    if t in ("stats", "estadísticas", "estadisticas", "productividad"):
        result["intent"] = INTENT_STATS
        return result

    # Today summary
    if re.match(r"(que tengo hoy|qué tengo hoy|mi día|mi dia|resumen del día|resumen de hoy)", t):
        result["intent"] = INTENT_TODAY
        return result

    # Complete task
    m = re.match(r"(?:marca como )?(?:completad[ao]|hecho|done|listo|terminad[ao])\s*:?\s*(.+)", t)
    if m:
        result["intent"] = INTENT_COMPLETE_TASK
        result["entities"]["title_fragment"] = m.group(1).strip()
        return result
    if re.match(r"(?:completar|terminar|marcar)\s+(.+)", t):
        m = re.match(r"(?:completar|terminar|marcar)\s+(.+)", t)
        result["intent"] = INTENT_COMPLETE_TASK
        result["entities"]["title_fragment"] = m.group(1).strip()
        return result

    # Delete task
    m = re.match(r"(?:borrar?|eliminar?|quitar?|cancelar?)\s+(?:tarea|task)\s*:?\s*(.+)", t)
    if m:
        result["intent"] = INTENT_DELETE_TASK
        result["entities"]["title_fragment"] = m.group(1).strip()
        return result

    # List tasks
    if re.match(r"(tareas|pendientes|que tengo pendiente|qué tengo pendiente|mis tareas|todo|to-do|lista)", t):
        result["intent"] = INTENT_LIST_TASKS
        return result

    # Week tasks
    if re.match(r"(tareas? de la semana|esta semana|semana|que tengo esta semana|qué tengo esta semana)", t):
        result["intent"] = INTENT_WEEK_TASKS
        return result

    # Add reminder
    m = re.match(r"(?:recuérdame|recuerdame|recordarme|acuérdate|acuerdate|reminder)\s+(?:que\s+)?(.+)", t)
    if m:
        body = m.group(1).strip()
        result["intent"] = INTENT_ADD_REMINDER
        result["entities"]["text"] = body
        result["entities"]["date"] = parse_date(body)
        result["entities"]["time"] = parse_time(body)
        return result

    # List reminders
    if re.match(r"(recordatorios|mis recordatorios|reminders|alarmas)", t):
        result["intent"] = INTENT_LIST_REMINDERS
        return result

    # Add note
    m = re.match(r"(?:nota|guarda|guardar|anotar?|apuntar?)\s*:?\s+(.+)", t)
    if m:
        body = m.group(1).strip()
        result["intent"] = INTENT_ADD_NOTE
        result["entities"]["content"] = body
        # Extract category if specified
        cat_m = re.search(r"(?:categoría|categoria|en)\s+['\"]?(\w+)['\"]?$", body)
        if cat_m:
            result["entities"]["category"] = cat_m.group(1)
            result["entities"]["content"] = body[:cat_m.start()].strip()
        return result

    # Search notes
    m = re.match(r"(?:buscar? nota|notas? (?:sobre|de))\s+(.+)", t)
    if m:
        result["intent"] = INTENT_SEARCH_NOTES
        result["entities"]["query"] = m.group(1).strip()
        return result

    # List notes
    if re.match(r"(notas|mis notas)", t):
        result["intent"] = INTENT_LIST_NOTES
        return result

    # Create folder
    m = re.match(r"(?:crear? carpeta|nueva carpeta|carpeta nueva)\s*:?\s+(.+)", t)
    if m:
        result["intent"] = INTENT_CREATE_FOLDER
        result["entities"]["folder_name"] = m.group(1).strip()
        return result

    # Add to folder: "guardar en Clientes: Juan Perez - 555-1234"
    m = re.match(r"(?:guardar en|agregar en|añadir en|agregar a|guardar a|añadir a)\s+(\w+)\s*:\s*(.+)", t)
    if m:
        result["intent"] = INTENT_ADD_TO_FOLDER
        result["entities"]["folder_name"] = m.group(1).strip()
        result["entities"]["content"] = m.group(2).strip()
        return result

    # View folder: "ver carpeta Clientes"
    m = re.match(r"(?:ver carpeta|abrir carpeta|carpeta|ver)\s+(\w+)$", t)
    if m:
        result["intent"] = INTENT_VIEW_FOLDER
        result["entities"]["folder_name"] = m.group(1).strip()
        return result

    # Search in folder: "buscar en Clientes: Juan"
    m = re.match(r"(?:buscar en)\s+(\w+)\s*:?\s+(.+)", t)
    if m:
        result["intent"] = INTENT_SEARCH_FOLDER
        result["entities"]["folder_name"] = m.group(1).strip()
        result["entities"]["query"] = m.group(2).strip()
        return result

    # List folders
    if re.match(r"(carpetas|mis carpetas|folders)", t):
        result["intent"] = INTENT_LIST_FOLDERS
        return result

    # Delete folder: "eliminar carpeta Clientes"
    m = re.match(r"(?:eliminar carpeta|borrar carpeta|delete folder)\s+(.+)", t)
    if m:
        result["intent"] = INTENT_DELETE_FOLDER
        result["entities"]["folder_name"] = m.group(1).strip()
        return result

    # Add task (catch-all for task-like messages)
    m = re.match(r"(?:agregar? tarea|nueva tarea|tarea|task|añadir|add)\s*:?\s+(.+)", t)
    if m:
        body = m.group(1).strip()
        result["intent"] = INTENT_ADD_TASK
        result["entities"]["title"] = body
        result["entities"]["date"] = parse_date(body)
        return result

    # Fallback: if it looks like an instruction, treat as unknown (send to AI)
    result["intent"] = INTENT_UNKNOWN
    return result
