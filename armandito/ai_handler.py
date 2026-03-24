from tz_helper import now_bz
"""AI fallback for messages that can't be parsed by regex."""

import os
import json
import httpx
from datetime import datetime

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("ARMANDITO_MODEL", "claude-haiku-4-5-20251001")

SYSTEM_PROMPT_TEMPLATE = """Eres Armandito, un asistente personal eficiente y cercano.
Respondes en espanol, de forma corta y directa. Usas emojis con moderacion.
La fecha y hora actual es: {current_datetime}
La zona horaria es America/Belize (CST, UTC-6).

Tienes acceso a estas funciones que el sistema ejecutara por ti:
- add_task: crear tarea (title, due_date YYYY-MM-DD, priority)
- complete_task: completar tarea (title_fragment)
- add_reminder: crear recordatorio (text, remind_at YYYY-MM-DD HH:MM)
- add_note: guardar nota (content, category)
- list_tasks: listar tareas pendientes
- list_notes: listar notas
- today_summary: resumen del dia
- create_event: crear evento en Google Calendar (title, start_dt YYYY-MM-DDTHH:MM, end_dt YYYY-MM-DDTHH:MM, location)
- list_events: ver eventos del calendario de hoy o una fecha (date YYYY-MM-DD)

IMPORTANTE: SI tienes acceso directo a Google Calendar. Cuando el usuario pida crear una cita, reunion, o evento, usa create_event. Cuando pregunte que tiene en su agenda, usa list_events.

- create_folder: crear carpeta (folder_name)
- add_to_folder: guardar info en carpeta (folder_name, content)
- view_folder: ver contenido de carpeta (folder_name)
- search_folder: buscar en carpeta (folder_name, query)
- list_folders: listar carpetas

Cuando el usuario pida algo que corresponda a una funcion, responde SOLO con JSON:
{"action": "nombre_funcion", "params": {...}, "reply": "mensaje para el usuario"}

Ejemplos:
- "agenda cita con el doctor manana a las 3" -> {"action": "create_event", "params": {"title": "Cita con el doctor", "start_dt": "2026-03-24T15:00", "end_dt": "2026-03-24T16:00"}, "reply": "Cita con el doctor agendada para manana a las 3:00 PM"}
- "que reuniones tengo hoy" -> {"action": "list_events", "params": {"date": "2026-03-23"}, "reply": "Aqui tienes tu agenda de hoy"}
- "barberia hoy a las 4" -> {"action": "create_event", "params": {"title": "Barberia", "start_dt": "2026-03-23T16:00", "end_dt": "2026-03-23T17:00"}, "reply": "Barberia agendada para hoy a las 4:00 PM"}

Si es conversacion general o no corresponde a ninguna funcion, responde solo texto normal.
No uses frases como "como modelo de lenguaje" ni similares.
NUNCA digas que no tienes acceso a Google Calendar. SI TIENES acceso."""


async def ask_ai(user_message, conversation_history=None):
    """Send message to Claude and get response."""
    if not ANTHROPIC_API_KEY:
        return {"type": "text", "content": "No tengo configurada la API de AI. Intenta con comandos directos como 'tareas', 'notas', 'recordatorios'."}

    current_dt = now_bz().strftime("%Y-%m-%d %H:%M")
    system = SYSTEM_PROMPT_TEMPLATE.replace("{current_datetime}", current_dt)

    messages = []
    if conversation_history:
        for msg in conversation_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 500,
                    "system": system,
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]

            # Try to parse as JSON action
            try:
                clean = text.strip()
                # Handle case where AI wraps JSON in markdown code blocks
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    clean = "\n".join(lines[1:])
                    clean = clean.rsplit("```", 1)[0].strip()
                action_data = json.loads(clean)
                if "action" in action_data:
                    return {"type": "action", "content": action_data}
            except (json.JSONDecodeError, KeyError):
                pass

            return {"type": "text", "content": text}

    except Exception as e:
        return {"type": "text", "content": f"Error conectando con AI: {str(e)[:100]}"}
