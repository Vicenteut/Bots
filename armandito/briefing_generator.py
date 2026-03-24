from tz_helper import now_bz
from datetime import datetime
from task_manager import get_pending_tasks, get_tasks_for_date, get_overdue_tasks, get_stats
from reminder_engine import get_user_reminders
from calendar_manager import get_all_events, format_events_text


def generate_morning_briefing(user_id, user_name=""):
    today = now_bz()
    date_str = today.strftime("%Y-%m-%d")
    day_names_es = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    month_names_es = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                      "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    day_name = day_names_es[today.weekday()]
    date_display = f"{day_name} {today.day} de {month_names_es[today.month]}"

    greeting = f"Buenos dias{' ' + user_name if user_name else ''}"

    lines = [f"{greeting}\n\nHOY — {date_display}\n"]

    # Calendar events
    try:
        events = get_all_events(date_str)
        if events:
            lines.append("Agenda:")
            lines.append(format_events_text(events))
            lines.append("")
    except Exception:
        pass

    # Today's tasks
    today_tasks = get_tasks_for_date(user_id, date_str)
    if today_tasks:
        lines.append("Tareas para hoy:")
        for t in today_tasks:
            priority_mark = " (!)" if t["priority"] in ("alta", "high") else ""
            lines.append(f"  - {t['title']}{priority_mark}")
        lines.append("")

    # Pending tasks (no date or future)
    pending = get_pending_tasks(user_id, limit=10)
    other_pending = [t for t in pending if t["due_date"] != date_str]
    if other_pending:
        lines.append(f"Pendientes ({len(other_pending)}):")
        for t in other_pending[:7]:
            due = f" ({t['due_date']})" if t["due_date"] else ""
            lines.append(f"  - {t['title']}{due}")
        if len(other_pending) > 7:
            lines.append(f"  ... y {len(other_pending) - 7} mas")
        lines.append("")

    # Overdue
    overdue = get_overdue_tasks(user_id)
    if overdue:
        lines.append(f"Vencidas ({len(overdue)}):")
        for t in overdue:
            lines.append(f"  - {t['title']} (vencio {t['due_date']})")
        lines.append("")

    # Reminders for today
    reminders = get_user_reminders(user_id)
    today_reminders = [r for r in reminders if r["remind_at"].startswith(date_str)]
    if today_reminders:
        lines.append("Recordatorios de hoy:")
        for r in today_reminders:
            time_str = r["remind_at"].split(" ")[1] if " " in r["remind_at"] else ""
            lines.append(f"  - {time_str} — {r['text']}")
        lines.append("")

    # Stats
    stats = get_stats(user_id)
    if stats["completed_week"] > 0:
        lines.append(f"Esta semana completaste {stats['completed_week']} tareas.")

    if not today_tasks and not other_pending and not overdue:
        lines.append("No tienes tareas pendientes. Buen dia!")

    return "\n".join(lines)


def generate_evening_wrapup(user_id, user_name=""):
    stats = get_stats(user_id)
    pending = get_pending_tasks(user_id, limit=5)
    overdue = get_overdue_tasks(user_id)

    lines = [f"Resumen del dia\n"]
    lines.append(f"Completado hoy: {stats['completed_today']} tareas")
    lines.append(f"Pendientes: {stats['pending']}")

    if overdue:
        lines.append(f"Vencidas: {len(overdue)}")

    if pending:
        lines.append("\nProximas tareas:")
        for t in pending[:5]:
            due = f" ({t['due_date']})" if t["due_date"] else ""
            lines.append(f"  - {t['title']}{due}")

    lines.append("\nQuieres reprogramar algo?")
    return "\n".join(lines)
