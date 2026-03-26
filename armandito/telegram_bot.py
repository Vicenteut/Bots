"""Telegram bot interface for Armandito."""

import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from message_handler import handle_message, get_or_create_user
from briefing_generator import generate_morning_briefing, generate_evening_wrapup
from reminder_engine import get_pending_reminders, mark_sent, handle_recurrence
from database import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Sticky folder timeout in seconds
STICKY_FOLDER_TIMEOUT = 60


def extract_folder_from_caption(caption):
    """Extract folder name from natural language caption.

    Handles patterns like:
      - "guardar en Invoice"
      - "en carpeta Invoice"
      - "carpeta: Invoice"
      - "armandito guarda estos en Invoice"
      - "quiero que guardes esto en Invoice"
      - Single word: used as folder name
    Returns (folder_name, description) or (None, caption)
    """
    import re
    if not caption:
        return None, ""

    t = caption.strip()

    # Pattern 1: explicit "carpeta: X" or "carpeta X"
    m = re.search(r"carpeta\s*:?\s+(.+?)(?:\s*$)", t, re.IGNORECASE)
    if m:
        return m.group(1).strip(), ""

    # Pattern 2: "guardar/guarda/guardes ... en X" or "en carpeta X"
    m = re.search(r"(?:guardar?|guardes?|salvar?|almacenar?|meter?)\s+.*?\ben\s+(.+?)(?:\s*$)", t, re.IGNORECASE)
    if m:
        folder = m.group(1).strip()
        # Remove leading "carpeta" / "la carpeta"
        folder = re.sub(r"^(?:la\s+)?carpeta\s+", "", folder, flags=re.IGNORECASE)
        return folder, ""

    # Pattern 3: "en carpeta X" or "en X" at the end
    m = re.search(r"\ben\s+(?:la\s+)?(?:carpeta\s+)?(\S+)\s*$", t, re.IGNORECASE)
    if m:
        return m.group(1).strip(), ""

    # Pattern 4: "guardar en X: description"
    m = re.match(r"(?:carpeta|guardar en|en)\s*:?\s*(.+?)(?:\s*:\s*(.*))?$", t, re.IGNORECASE)
    if m:
        folder = m.group(1).strip()
        desc = (m.group(2) or "").strip()
        return folder, desc

    # Fallback: single word = folder name
    words = t.split()
    if len(words) == 1:
        return words[0], ""

    return None, t


def get_sticky_folder(context, user_id):
    """Get the sticky folder if still valid (within timeout)."""
    import time
    key = f"sticky_folder_{user_id}"
    ts_key = f"sticky_folder_ts_{user_id}"
    if key in context.bot_data and ts_key in context.bot_data:
        elapsed = time.time() - context.bot_data[ts_key]
        if elapsed < STICKY_FOLDER_TIMEOUT:
            return context.bot_data[key]
    return None


def set_sticky_folder(context, user_id, folder_name):
    """Set the sticky folder for subsequent files."""
    import time
    context.bot_data[f"sticky_folder_{user_id}"] = folder_name
    context.bot_data[f"sticky_folder_ts_{user_id}"] = time.time()


BOT_TOKEN = os.getenv("ARMANDITO_BOT_TOKEN", "")
OWNER_TELEGRAM_ID = int(os.getenv("ARMANDITO_OWNER_ID", "0"))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = (
        f"Hola {user.first_name}! Soy Armandito, tu asistente personal.\n\n"
        "Puedo ayudarte a:\n"
        "  - Organizar tareas y pendientes\n"
        "  - Crear recordatorios\n"
        "  - Guardar notas e ideas\n"
        "  - Enviarte resumenes diarios\n\n"
        "Escribe 'ayuda' para ver todos los comandos."
    )
    await update.message.reply_text(welcome)


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, name = get_or_create_user(user.id, user.first_name)
    briefing = generate_morning_briefing(user_id, name)
    await update.message.reply_text(briefing)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from message_handler import HELP_TEXT
    await update.message.reply_text(HELP_TEXT)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    if not text:
        return

    try:
        response = await handle_message(user.id, user.first_name, text)
        if not response:
            return

        # Check if response is a dict (special action like sending files)
        if isinstance(response, dict) and response.get("type") == "send_files":
            await update.message.reply_text(response.get("text", "Enviando archivos..."))
            files = response.get("files", [])
            sent = 0
            for f in files:
                try:
                    filepath = f["filepath"]
                    if f["type"] == "photo":
                        await update.message.reply_photo(
                            photo=open(filepath, "rb"),
                            caption=f["filename"]
                        )
                    else:
                        await update.message.reply_document(
                            document=open(filepath, "rb"),
                            filename=f["filename"]
                        )
                    sent += 1
                except Exception as e:
                    logger.error(f"Error sending file {f['filepath']}: {e}")
                    await update.message.reply_text(f"No pude enviar: {f['filename']}")
            if sent > 0:
                await update.message.reply_text(f"Listo, {sent} archivo(s) enviado(s).")
        else:
            # Normal text response
            response_text = str(response)
            if len(response_text) > 4000:
                for i in range(0, len(response_text), 4000):
                    await update.message.reply_text(response_text[i:i+4000])
            else:
                await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text("Ocurrio un error. Intenta de nuevo.")


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages — save to folder if caption specifies one."""
    if not update.message or not update.message.photo:
        return

    user = update.effective_user
    caption = (update.message.caption or "").strip()

    try:
        from message_handler import get_or_create_user
        from folder_manager import add_to_folder, create_folder
        import re

        user_id, name = get_or_create_user(user.id, user.first_name)

        # Get highest resolution photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Determine folder name from caption (natural language)
        folder_name, description = extract_folder_from_caption(caption)

        # If no folder from caption, try sticky folder
        if not folder_name:
            folder_name = get_sticky_folder(context, user_id)

        # Default fallback
        if not folder_name:
            folder_name = "Fotos"
        else:
            # Set sticky folder for subsequent files
            set_sticky_folder(context, user_id, folder_name)

        # Create photos directory
        photos_dir = os.path.join("/root/armandito/photos", str(user_id), folder_name.lower())
        os.makedirs(photos_dir, exist_ok=True)

        # Download photo
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{photo.file_unique_id}.jpg"
        filepath = os.path.join(photos_dir, filename)
        await file.download_to_drive(filepath)

        # Save reference in folder
        content = f"[FOTO] {filepath}"
        if description:
            content += f" — {description}"

        create_folder(user_id, folder_name)
        add_to_folder(user_id, folder_name, content)

        response = f"Foto guardada en carpeta '{folder_name}'"
        if description:
            response += f"\nDescripcion: {description}"
        response += f"\n({len(update.message.photo)} resoluciones disponibles)"

        await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Error handling photo: {e}", exc_info=True)
        await update.message.reply_text("Error guardando la foto. Intenta de nuevo.")


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document/file messages — save to folder."""
    if not update.message or not update.message.document:
        return

    user = update.effective_user
    caption = (update.message.caption or "").strip()

    try:
        from message_handler import get_or_create_user
        from folder_manager import add_to_folder, create_folder
        import re

        user_id, name = get_or_create_user(user.id, user.first_name)

        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)

        # Determine folder from caption (natural language)
        folder_name, description = extract_folder_from_caption(caption)

        # If no folder from caption, try sticky folder
        if not folder_name:
            folder_name = get_sticky_folder(context, user_id)

        # Default fallback
        if not folder_name:
            folder_name = "Archivos"
        else:
            # Set sticky folder for subsequent files
            set_sticky_folder(context, user_id, folder_name)

        # Create directory
        docs_dir = os.path.join("/root/armandito/files", str(user_id), folder_name.lower())
        os.makedirs(docs_dir, exist_ok=True)

        # Download file
        filename = doc.file_name or f"file_{doc.file_unique_id}"
        filepath = os.path.join(docs_dir, filename)
        await file.download_to_drive(filepath)

        # Save reference in folder
        content = f"[ARCHIVO] {filename} — {filepath}"
        if description:
            content += f" — {description}"

        create_folder(user_id, folder_name)
        add_to_folder(user_id, folder_name, content)

        size_kb = doc.file_size / 1024 if doc.file_size else 0
        response = f"Archivo '{filename}' guardado en carpeta '{folder_name}'"
        if size_kb > 0:
            response += f" ({size_kb:.1f} KB)"

        await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Error handling document: {e}", exc_info=True)
        await update.message.reply_text("Error guardando el archivo. Intenta de nuevo.")


async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job: check and send pending reminders."""
    try:
        pending = get_pending_reminders()
        for r in pending:
            telegram_id = r["telegram_id"]
            name = r["name"] or ""
            text = f"Recordatorio: {r['text']}"

            try:
                await context.bot.send_message(chat_id=telegram_id, text=text)
                mark_sent(r["reminder_id"])
                handle_recurrence(r)
                logger.info(f"Reminder sent to {telegram_id}: {r['text'][:50]}")
            except Exception as e:
                logger.error(f"Failed to send reminder {r['reminder_id']}: {e}")
    except Exception as e:
        logger.error(f"Error in check_reminders: {e}")


async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    """Send morning briefing to owner."""
    if not OWNER_TELEGRAM_ID:
        return
    try:
        from database import get_db
        conn = get_db()
        user = conn.execute(
            "SELECT user_id, name FROM users WHERE telegram_id=?",
            (OWNER_TELEGRAM_ID,)
        ).fetchone()
        conn.close()

        if user:
            briefing = generate_morning_briefing(user["user_id"], user["name"])
            await context.bot.send_message(chat_id=OWNER_TELEGRAM_ID, text=briefing)
            logger.info("Morning briefing sent")
    except Exception as e:
        logger.error(f"Error sending morning briefing: {e}")


async def send_evening_wrapup(context: ContextTypes.DEFAULT_TYPE):
    """Send evening wrap-up to owner."""
    if not OWNER_TELEGRAM_ID:
        return
    try:
        from database import get_db
        conn = get_db()
        user = conn.execute(
            "SELECT user_id, name FROM users WHERE telegram_id=?",
            (OWNER_TELEGRAM_ID,)
        ).fetchone()
        conn.close()

        if user:
            wrapup = generate_evening_wrapup(user["user_id"], user["name"])
            await context.bot.send_message(chat_id=OWNER_TELEGRAM_ID, text=wrapup)
            logger.info("Evening wrap-up sent")
    except Exception as e:
        logger.error(f"Error sending evening wrapup: {e}")


def main():
    if not BOT_TOKEN:
        print("ERROR: ARMANDITO_BOT_TOKEN no configurado")
        print("Agrega tu token en .env: ARMANDITO_BOT_TOKEN=tu_token")
        return

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ayuda", cmd_help))

    # All text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Photos and documents
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))

    # Scheduled jobs
    job_queue = app.job_queue

    # Check reminders every 60 seconds
    job_queue.run_repeating(check_reminders, interval=60, first=10)

    # Morning briefing at 7:00 AM (configurable via BRIEFING_HOUR env)
    briefing_hour = int(os.getenv("BRIEFING_HOUR", "7"))
    from datetime import time as dtime
    job_queue.run_daily(send_morning_briefing, time=dtime(hour=briefing_hour, minute=0))

    # Evening wrap-up at 9:00 PM
    wrapup_hour = int(os.getenv("WRAPUP_HOUR", "21"))
    job_queue.run_daily(send_evening_wrapup, time=dtime(hour=wrapup_hour, minute=0))

    logger.info("Armandito iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
