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
        if response:
            # Split long messages (Telegram limit: 4096 chars)
            if len(response) > 4000:
                for i in range(0, len(response), 4000):
                    await update.message.reply_text(response[i:i+4000])
            else:
                await update.message.reply_text(response)
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

        # Determine folder name from caption
        # Formats: "carpeta: Nombre" or "guardar en Nombre" or just "Nombre"
        folder_name = None
        description = ""

        m = re.match(r"(?:carpeta|guardar en|en)\s*:?\s*(\w+)\s*(.*)", caption, re.IGNORECASE)
        if m:
            folder_name = m.group(1).strip()
            description = m.group(2).strip()
        elif caption:
            # If just one word, use as folder name
            words = caption.split()
            if len(words) == 1:
                folder_name = words[0]
            else:
                # First word = folder, rest = description
                folder_name = words[0]
                description = " ".join(words[1:])

        if not folder_name:
            folder_name = "Fotos"

        # Create photos directory
        photos_dir = os.path.join("/root/armandito/photos", str(user_id), folder_name.lower())
        os.makedirs(photos_dir, exist_ok=True)

        # Download photo
        from datetime import datetime
from tz_helper import now_bz
        timestamp = now_bz().strftime("%Y%m%d_%H%M%S")
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

        # Determine folder from caption
        folder_name = None
        description = ""

        m = re.match(r"(?:carpeta|guardar en|en)\s*:?\s*(\w+)\s*(.*)", caption, re.IGNORECASE)
        if m:
            folder_name = m.group(1).strip()
            description = m.group(2).strip()
        elif caption:
            words = caption.split()
            folder_name = words[0]
            description = " ".join(words[1:]) if len(words) > 1 else ""

        if not folder_name:
            folder_name = "Archivos"

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
